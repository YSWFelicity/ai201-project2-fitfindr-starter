"""
agent.py

The FitFindr planning loop. Orchestrates the three tools in response to a
natural language user query, passing state between them via a session dict.

Complete tools.py and test each tool in isolation before implementing this file.

Usage (once implemented):
    from agent import run_agent
    from utils.data_loader import get_example_wardrobe

    result = run_agent(
        query="vintage graphic tee under $30, size M",
        wardrobe=get_example_wardrobe(),
    )
    print(result["fit_card"])
    print(result["error"])   # None on success
"""

import re

from tools import search_listings, suggest_outfit, create_fit_card


# ── query parsing ─────────────────────────────────────────────────────────────

# Standalone size keywords we recognize without an explicit "size" cue.
_SIZE_KEYWORDS = ["xxs", "xs", "xl", "xxl", "s", "m", "l"]


def parse_query(query: str) -> dict:
    """
    Extract a search description, size, and max_price from a natural-language
    query using regex (per the Planning Loop step 1 in planning.md).

    Regex is chosen over an LLM call here for speed, determinism, and zero API
    cost on a step that's easy to do reliably.

    Returns:
        {"description": str, "size": str | None, "max_price": float | None}
    """
    text = query.strip()
    remaining = text

    # max_price: a dollar amount after "under/below/less than", or a bare $NN.
    max_price = None
    price_match = re.search(
        r"(?:under|below|less than|max|up to)\s*\$?\s*(\d+(?:\.\d+)?)",
        remaining,
        flags=re.IGNORECASE,
    )
    if price_match is None:
        price_match = re.search(r"\$\s*(\d+(?:\.\d+)?)", remaining)
    if price_match is not None:
        max_price = float(price_match.group(1))
        remaining = remaining[: price_match.start()] + remaining[price_match.end() :]

    # size: explicit "size <token>", or a standalone size keyword / shoe number.
    size = None
    size_match = re.search(r"size\s+([a-z0-9]+)", remaining, flags=re.IGNORECASE)
    if size_match is not None:
        size = size_match.group(1).upper()
        remaining = remaining[: size_match.start()] + remaining[size_match.end() :]
    else:
        for kw in _SIZE_KEYWORDS:
            kw_match = re.search(rf"\b{kw}\b", remaining, flags=re.IGNORECASE)
            if kw_match is not None:
                size = kw_match.group(0).upper()
                remaining = (
                    remaining[: kw_match.start()] + remaining[kw_match.end() :]
                )
                break

    # description: whatever keywords are left after stripping price/size phrases.
    description = re.sub(r"\s+", " ", remaining).strip(" ,.")

    return {"description": description, "size": size, "max_price": max_price}


# ── session state ─────────────────────────────────────────────────────────────

def _new_session(query: str, wardrobe: dict) -> dict:
    """
    Initialize and return a fresh session dict for one user interaction.

    The session dict is the single source of truth for everything that happens
    during a run — it stores the original query, parsed parameters, tool results,
    and any error that caused early termination.

    You may add fields to this dict as needed for your implementation.
    """
    return {
        "query": query,              # original user query
        "parsed": {},                # extracted description / size / max_price
        "search_results": [],        # list of matching listing dicts
        "selected_item": None,       # top result, passed into suggest_outfit
        "wardrobe": wardrobe,        # user's wardrobe dict
        "outfit_suggestion": None,   # string returned by suggest_outfit
        "fit_card": None,            # string returned by create_fit_card
        "error": None,               # set if the interaction ended early
    }


# ── planning loop ─────────────────────────────────────────────────────────────

def run_agent(query: str, wardrobe: dict) -> dict:
    """
    Main agent entry point. Runs the FitFindr planning loop for a single
    user interaction and returns the completed session dict.

    Args:
        query:    Natural language user request
                  (e.g., "vintage graphic tee under $30, size M")
        wardrobe: User's wardrobe dict — use get_example_wardrobe() or
                  get_empty_wardrobe() from utils/data_loader.py

    Returns:
        The session dict after the interaction completes. Check session["error"]
        first — if it is not None, the interaction ended early and the other
        output fields (outfit_suggestion, fit_card) will be None.

    TODO — implement this function using the planning loop you designed in planning.md:

        Step 1: Initialize the session with _new_session().

        Step 2: Parse the user's query to extract a description, size, and
                max_price. You can use regex, string splitting, or ask the LLM
                to parse it — document your choice in planning.md.
                Store the result in session["parsed"].

        Step 3: Call search_listings() with the parsed parameters.
                Store results in session["search_results"].
                If no results: set session["error"] to a helpful message and
                return the session early. Do NOT proceed to suggest_outfit
                with empty input.

        Step 4: Select the item to use (e.g., the top result).
                Store it in session["selected_item"].

        Step 5: Call suggest_outfit() with the selected item and wardrobe.
                Store the result in session["outfit_suggestion"].

        Step 6: Call create_fit_card() with the outfit suggestion and selected item.
                Store the result in session["fit_card"].

        Step 7: Return the session.

    Before writing code, complete the Planning Loop and State Management sections
    of planning.md — your implementation should match what you described there.
    """
    # Step 1 — initialize the session (single source of truth for this run).
    session = _new_session(query, wardrobe)

    # Step 2 — parse the query into description / size / max_price (regex).
    session["parsed"] = parse_query(query)

    # Step 3 — search, then GATE on emptiness.
    try:
        session["search_results"] = search_listings(
            session["parsed"]["description"],
            session["parsed"]["size"],
            session["parsed"]["max_price"],
        )
    except Exception:
        session["error"] = (
            "Couldn't load the listings catalog right now — please refresh and "
            "try again in a moment."
        )
        return session

    if not session["search_results"]:
        # No matches: short-circuit before styling an item we never found.
        parsed = session["parsed"]
        detail = f" '{parsed['description']}'" if parsed["description"] else ""
        if parsed["max_price"] is not None:
            detail += f" under ${parsed['max_price']:g}"
        session["error"] = (
            f"No listings matched{detail}. Try raising your price, dropping the "
            "size filter, or describing the item more broadly."
        )
        return session

    # Step 4 — select the top-scored listing to style.
    session["selected_item"] = session["search_results"][0]

    # Step 5 — suggest an outfit (always returns non-empty text; no gate needed).
    try:
        session["outfit_suggestion"] = suggest_outfit(
            session["selected_item"], session["wardrobe"]
        )
    except Exception:
        session["error"] = "Couldn't generate outfit ideas right now."
        return session

    if not session["outfit_suggestion"]:
        session["error"] = "Couldn't generate outfit ideas right now."
        return session

    # Step 6 — turn the outfit into a shareable fit card.
    try:
        session["fit_card"] = create_fit_card(
            session["outfit_suggestion"], session["selected_item"]
        )
    except Exception:
        session["error"] = "Couldn't generate a fit card right now."
        return session

    # Step 7 — done: error is None and all three output fields are populated.
    return session


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

    print("=== Happy path: graphic tee ===\n")
    session = run_agent(
        query="looking for a vintage graphic tee under $30",
        wardrobe=get_example_wardrobe(),
    )
    if session["error"]:
        print(f"Error: {session['error']}")
    else:
        print(f"Found: {session['selected_item']['title']}")
        print(f"\nOutfit: {session['outfit_suggestion']}")
        print(f"\nFit card: {session['fit_card']}")

    print("\n\n=== No-results path ===\n")
    session2 = run_agent(
        query="designer ballgown size XXS under $5",
        wardrobe=get_example_wardrobe(),
    )
    print(f"Error message: {session2['error']}")
