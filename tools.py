"""
tools.py

The three required FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Complete and test each tool before moving to agent.py.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str
"""

import os
import re

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

load_dotenv()

# Default Groq chat model used by the styling tools.
_GROQ_MODEL = "llama-3.3-70b-versatile"

# Words that carry no signal for keyword-overlap scoring in search_listings.
_STOPWORDS = {
    "a", "an", "and", "the", "for", "with", "of", "to", "in", "on", "or",
    "my", "me", "i", "looking", "want", "need", "some", "something", "that",
    "this", "is", "are", "it", "under", "below", "less", "than", "size",
}


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


def _chat(prompt: str, temperature: float) -> str:
    """Send a single user prompt to the Groq chat model and return the text."""
    client = _get_groq_client()
    completion = client.chat.completions.create(
        model=_GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )
    return (completion.choices[0].message.content or "").strip()


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    Args:
        description: Keywords describing what the user is looking for
                     (e.g., "vintage graphic tee").
        size:        Size string to filter by, or None to skip size filtering.
                     Matching is case-insensitive (e.g., "M" matches "S/M").
        max_price:   Maximum price (inclusive), or None to skip price filtering.

    Returns:
        A list of matching listing dicts, sorted by relevance (best match first).
        Returns an empty list if nothing matches — does NOT raise an exception.

    Each listing dict has the following fields:
        id, title, description, category, style_tags (list), size,
        condition, price (float), colors (list), brand, platform

    TODO:
        1. Load all listings with load_listings().
        2. Filter by max_price and size (if provided).
        3. Score each remaining listing by keyword overlap with `description`.
        4. Drop any listings with a score of 0 (no relevant matches).
        5. Sort by score, highest first, and return the listing dicts.

    Before writing code, fill in the Tool 1 section of planning.md.
    """
    listings = load_listings()

    # Tokenize the query into meaningful keywords for relevance scoring.
    query_tokens = {
        tok
        for tok in re.findall(r"[a-z0-9]+", description.lower())
        if tok not in _STOPWORDS
    }

    size_filter = size.strip().lower() if size else None

    scored: list[tuple[int, dict]] = []
    for listing in listings:
        # Hard filter: price ceiling (inclusive).
        if max_price is not None and listing["price"] > max_price:
            continue

        # Hard filter: size (case-insensitive substring match).
        if size_filter is not None and size_filter not in listing["size"].lower():
            continue

        # Build the searchable text for this listing.
        haystack_tokens = set(
            re.findall(
                r"[a-z0-9]+",
                " ".join(
                    [
                        listing["title"],
                        listing["description"],
                        " ".join(listing["style_tags"]),
                    ]
                ).lower(),
            )
        )

        # Score by keyword overlap; weight style_tag matches a bit higher.
        score = len(query_tokens & haystack_tokens)
        tag_tokens = {
            tok for tag in listing["style_tags"] for tok in re.findall(r"[a-z0-9]+", tag.lower())
        }
        score += len(query_tokens & tag_tokens)

        if score > 0:
            scored.append((score, listing))

    # Sort by score, highest first (stable: ties keep dataset order).
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [listing for _, listing in scored]


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(new_item: dict, wardrobe: dict) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty — handle this gracefully.

    Returns:
        A non-empty string with outfit suggestions.
        If the wardrobe is empty, offer general styling advice for the item
        rather than raising an exception or returning an empty string.

    TODO:
        1. Check whether wardrobe['items'] is empty.
        2. If empty: call the LLM with a prompt for general styling ideas
           (what kinds of items pair well, what vibe it suits, etc.).
        3. If not empty: format the wardrobe items into a prompt and ask
           the LLM to suggest specific outfit combinations using the new item
           and named pieces from the wardrobe.
        4. Return the LLM's response as a string.

    Before writing code, fill in the Tool 2 section of planning.md.
    """
    # Describe the new item compactly for the prompt.
    item_desc = (
        f"- Title: {new_item.get('title', 'Unknown item')}\n"
        f"- Category: {new_item.get('category', 'unknown')}\n"
        f"- Colors: {', '.join(new_item.get('colors', [])) or 'unspecified'}\n"
        f"- Style tags: {', '.join(new_item.get('style_tags', [])) or 'none'}\n"
        f"- Description: {new_item.get('description', '')}"
    )

    items = wardrobe.get("items", []) if wardrobe else []

    if not items:
        # Empty wardrobe → general styling advice for the item type.
        prompt = (
            "You are a friendly personal stylist. A shopper is considering this "
            "secondhand item but has not entered any wardrobe yet:\n\n"
            f"{item_desc}\n\n"
            "Give general styling advice for this piece: what kinds of items pair "
            "well with it, what vibe it suits, and how to build 1-2 outfits around "
            "it from scratch. Keep it to a short, friendly paragraph. End by gently "
            "noting that adding a wardrobe will let you suggest outfits using their "
            "own pieces."
        )
    else:
        # Format the wardrobe items so the model can name specific pieces.
        wardrobe_lines = []
        for it in items:
            colors = ", ".join(it.get("colors", []))
            tags = ", ".join(it.get("style_tags", []))
            line = f"- {it.get('name', 'item')}"
            details = " · ".join(p for p in [it.get("category", ""), colors, tags] if p)
            if details:
                line += f" ({details})"
            wardrobe_lines.append(line)
        wardrobe_text = "\n".join(wardrobe_lines)

        prompt = (
            "You are a friendly personal stylist. A shopper is considering this "
            "secondhand item:\n\n"
            f"{item_desc}\n\n"
            "Here is their current wardrobe:\n"
            f"{wardrobe_text}\n\n"
            "Suggest 1-2 complete, wearable outfits that combine the new item with "
            "SPECIFIC named pieces from their wardrobe above. Refer to wardrobe "
            "pieces by name. Keep it casual and concrete — a couple of short, "
            "readable sentences per outfit."
        )

    try:
        text = _chat(prompt, temperature=0.7)
        if text:
            return text
        raise ValueError("Empty completion from model.")
    except Exception:
        return (
            "Couldn't reach the styling model just now, but this piece pairs "
            "easily with simple basics — neutral bottoms and clean sneakers. "
            "(Outfit ideas will be richer once the connection is back.)"
        )


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.

    Returns:
        A 2–4 sentence string usable as an Instagram/TikTok caption.
        If outfit is empty or missing, return a descriptive error message
        string — do NOT raise an exception.

    The caption should:
    - Feel casual and authentic (like a real OOTD post, not a product description)
    - Mention the item name, price, and platform naturally (once each)
    - Capture the outfit vibe in specific terms
    - Sound different each time for different inputs (use higher LLM temperature)

    TODO:
        1. Guard against an empty or whitespace-only outfit string.
        2. Build a prompt that gives the LLM the item details and the outfit,
           and asks for a caption matching the style guidelines above.
        3. Call the LLM and return the response.

    Before writing code, fill in the Tool 3 section of planning.md.
    """
    # Guard: no outfit to caption.
    if not outfit or not outfit.strip():
        return (
            "Can't generate a fit card without an outfit suggestion — try "
            "finding an item first so I have a look to caption."
        )

    title = new_item.get("title", "this piece")
    price = new_item.get("price")
    platform = new_item.get("platform", "secondhand")
    price_str = f"${price:g}" if isinstance(price, (int, float)) else "a steal"

    prompt = (
        "Write a short, shareable Instagram/TikTok caption for a thrifted "
        "outfit, like a real OOTD post (NOT a product description).\n\n"
        f"Item: {title}\n"
        f"Price: {price_str}\n"
        f"Platform: {platform}\n"
        f"Outfit: {outfit}\n\n"
        "Requirements:\n"
        "- 2 to 4 sentences, casual and authentic in voice.\n"
        f"- Mention the item name, the price ({price_str}), and the platform "
        f"({platform}) naturally, each exactly once.\n"
        "- Capture the outfit's vibe in specific terms.\n"
        "- Emoji are welcome but optional. Return only the caption text."
    )

    try:
        text = _chat(prompt, temperature=0.9)
        if text:
            return text
        raise ValueError("Empty completion from model.")
    except Exception:
        return f"Thrifted this {title} on {platform} for {price_str} ✨ secondhand and styled."
