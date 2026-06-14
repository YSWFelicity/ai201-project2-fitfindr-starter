# FitFindr — planning.md

> Complete this document before writing any implementation code.
> Your spec and agent diagram are what you'll use to direct AI tools (Claude, Copilot, etc.) to generate your implementation — the more specific they are, the more useful the generated code will be.
> Your planning.md will be reviewed as part of your submission.
> Update it before starting any stretch features.

---

## Tools

List every tool your agent will use. For each tool, fill in all four fields.
You must have at least 3 tools. The three required tools are listed — add any additional tools below them.

### Tool 1: search_listings

**What it does:**
Searches the 40-item mock dataset (`utils.data_loader.load_listings()`) for secondhand listings that match the user's request. It applies hard filters (price ceiling, size) and then ranks the survivors by keyword relevance against the query, returning the best matches first. No LLM call — this is deterministic, local filtering and scoring.

**Input parameters:**
- `description` (str): Free-text keywords describing the item the user wants, e.g. `"vintage graphic tee"`. Used for relevance scoring against each listing's `title`, `description`, and `style_tags`.
- `size` (str | None): Size string to filter by (e.g. `"M"`, `"8"`), or `None` to skip size filtering. Matched case-insensitively as a substring so `"M"` matches `"S/M"` and `"M"` matches `"W30 L30"` only if intended — we normalize both sides to lowercase and test membership.
- `max_price` (float | None): Inclusive upper price bound, or `None` to skip price filtering. A listing priced exactly at `max_price` is kept.

**What it returns:**
A `list[dict]` of matching listings sorted by relevance score (highest first). Each dict is a raw listing record with the fields: `id`, `title`, `description`, `category`, `style_tags` (list), `size`, `condition` (`excellent`/`good`/`fair`), `price` (float), `colors` (list), `brand` (str or None), `platform` (`depop`/`thredUp`/`poshmark`). Listings whose relevance score is 0 (no keyword overlap) are dropped before returning.

**What happens if it fails or returns nothing:**
Returns an empty list `[]` — never raises. If the dataset file is missing/corrupt, the underlying `load_listings()` exception is allowed to surface (caught one level up by the agent loop and turned into a friendly error). An empty list signals the planning loop to short-circuit: it sets a helpful `session["error"]` ("No listings matched — try raising your price or broadening the description") and stops before calling `suggest_outfit`.

---

### Tool 2: suggest_outfit

**What it does:**
Takes a single listing the shopper is considering plus their wardrobe and asks the Groq LLM to propose 1–2 complete, wearable outfits. When the wardrobe has items, it styles the new piece *with specific named pieces* from the closet; when the wardrobe is empty, it falls back to general styling advice for that item type.

**Input parameters:**
- `new_item` (dict): A listing dict (the top search result), used to tell the model what the item is — we pass its `title`, `category`, `colors`, `style_tags`, and `description` into the prompt.
- `wardrobe` (dict): A wardrobe dict shaped `{"items": [ ... ]}` per `data/wardrobe_schema.json`. Each item has `id`, `name`, `category`, `colors`, `style_tags`, and optional `notes`. May be empty (`items == []`) — handled as a distinct branch.

**What it returns:**
A non-empty `str` containing the outfit suggestion(s) in casual, readable prose (e.g. "Pair this with your baggy dark-wash jeans and chunky white sneakers…"). The model is run at a moderate temperature (~0.7) so suggestions feel natural but stay grounded in the named wardrobe pieces.

**What happens if it fails or returns nothing:**
- **Empty wardrobe:** not an error — the prompt switches to "the user has no wardrobe entered yet; give general styling ideas for this item" and still returns a useful non-empty string.
- **LLM/API failure** (network error, missing `GROQ_API_KEY`, empty completion): caught inside the tool; returns a short, safe fallback string ("Couldn't generate outfit ideas right now — but this piece pairs well with simple basics in neutral tones.") so the caller always receives non-empty text and the chain can still produce a fit card. The agent loop treats a non-empty string as success.

---

### Tool 3: create_fit_card

**What it does:**
Turns the outfit suggestion plus the item details into a short, shareable social caption — the kind of thing you'd post under an OOTD photo. One Groq LLM call at a higher temperature (~0.9) so repeated runs feel fresh rather than templated.

**Input parameters:**
- `outfit` (str): The outfit suggestion string returned by `suggest_outfit()`. This is the raw material the caption riffs on.
- `new_item` (dict): The listing dict, so the caption can name the item, its `price`, and its `platform` naturally (each mentioned once).

**What it returns:**
A 2–4 sentence `str` suitable as an Instagram/TikTok caption — casual and authentic in voice, mentioning the item name, price, and platform once each, and capturing the outfit's vibe in specific terms. Emoji are allowed but not required.

**What happens if it fails or returns nothing:**
- **Empty/whitespace-only `outfit`:** guarded *before* any API call — returns a descriptive error string ("Can't make a fit card without an outfit suggestion.") rather than raising. The agent loop never reaches this tool on the empty-outfit path because `suggest_outfit` always returns non-empty text, but the guard makes the tool safe to call independently.
- **LLM/API failure:** caught inside the tool; returns a simple fallback caption built from the item fields ("Thrifted this {title} on {platform} for ${price} ✨") so the user still gets shareable text.

---

### Additional Tools (if any)

No additional tools. FitFindr ships with exactly the three required tools above. (A possible stretch tool — `parse_query` to extract `description`/`size`/`max_price` via the LLM — is currently handled inline in the planning loop with regex, see the Planning Loop section, so it is not a separate tool.)

---

## Planning Loop

**How does your agent decide which tool to call next?**

The planning loop is a **fixed, condition-gated pipeline** rather than an open-ended LLM-driven loop — the three tools have a natural dependency order (you can't style an item you haven't found, and you can't caption an outfit you haven't styled), so the "plan" is deterministic and each step's *output* decides whether the next step runs.

The loop runs inside `run_agent(query, wardrobe)` and reads/writes a single `session` dict:

1. **Parse.** Extract `description`, `size`, and `max_price` from the natural-language `query`.
   - `max_price`: regex for a dollar amount after "under/below/less than" or a bare `$NN` (e.g. `under $30` → `30.0`).
   - `size`: regex for `size <token>` or a standalone size keyword (`XS/S/M/L/XL` or a shoe number); else `None`.
   - `description`: the query with the matched price/size phrases stripped out, leaving the item keywords.
   - Store all three in `session["parsed"]`. (Regex is the default; chosen over an LLM call here for speed, determinism, and zero API cost on a step that's easy to do reliably.)

2. **Search → gate on results.** Call `search_listings(**parsed)`; store in `session["search_results"]`.
   - **If empty:** set `session["error"]` to a helpful message and **return early** — do not call `suggest_outfit` with empty input. This is the primary branch point.
   - **If non-empty:** select the top-scored listing as `session["selected_item"]` and continue.

3. **Suggest.** Call `suggest_outfit(selected_item, wardrobe)`; store in `session["outfit_suggestion"]`. This tool always returns non-empty text (empty wardrobe → general advice; API failure → fallback string), so it does not gate the next step — but the loop still defensively checks for a truthy string.

4. **Card.** Call `create_fit_card(outfit_suggestion, selected_item)`; store in `session["fit_card"]`.

5. **Done.** Return the `session`. The loop knows it's finished when either (a) it returned early with an `error`, or (b) all three fields (`selected_item`, `outfit_suggestion`, `fit_card`) are populated and `error is None`.

Every tool call is wrapped so an unexpected exception is converted into `session["error"]` and an early return — the loop never crashes the caller (Gradio).

**Explicit branch logic (implementable as-is):**

```text
session = _new_session(query, wardrobe)

# Step 1 — parse
session["parsed"] = parse_query(query)
#   parse_query returns {"description": str, "size": str|None, "max_price": float|None}

# Step 2 — search, then GATE on emptiness
try:
    session["search_results"] = search_listings(
        session["parsed"]["description"],
        session["parsed"]["size"],
        session["parsed"]["max_price"],
    )
except Exception:
    session["error"] = "Couldn't load listings right now."
    return session

if len(session["search_results"]) == 0:          # BRANCH A: no matches
    session["error"] = (
        "No listings matched. Try raising your price or broadening the description."
    )
    return session                                # early return — DO NOT call suggest_outfit

session["selected_item"] = session["search_results"][0]   # BRANCH B: take top result

# Step 3 — suggest outfit (always returns non-empty text; no gate needed)
session["outfit_suggestion"] = suggest_outfit(
    session["selected_item"], session["wardrobe"]
)

# Step 4 — fit card
session["fit_card"] = create_fit_card(
    session["outfit_suggestion"], session["selected_item"]
)

# Step 5 — done
return session            # success when error is None and fit_card is set
```

---

## State Management

**How does information from one tool get passed to the next?**

All state for one interaction lives in a single **`session` dict**, created by `_new_session(query, wardrobe)` in `agent.py`. It is the single source of truth — tools themselves are stateless pure-ish functions; the loop is what threads data between them by reading one field and writing the next.

| Field | Written by | Read by | Purpose |
|-------|-----------|---------|---------|
| `query` | `_new_session` | parse step | original user text |
| `parsed` | parse step | `search_listings` | `{"description", "size", "max_price"}` |
| `search_results` | `search_listings` | result gate | ranked list of listing dicts |
| `selected_item` | result gate (top result) | `suggest_outfit`, `create_fit_card` | the listing being styled |
| `wardrobe` | `_new_session` | `suggest_outfit` | the user's closet (example or empty) |
| `outfit_suggestion` | `suggest_outfit` | `create_fit_card`, UI | styling text |
| `fit_card` | `create_fit_card` | UI | shareable caption |
| `error` | any step on failure | UI / early return | non-None ⇒ interaction ended early |

**Flow of data between calls:** `parsed` → `search_listings` returns a list → loop picks `search_results[0]` as `selected_item` → `selected_item` (+ `wardrobe`) → `suggest_outfit` returns text into `outfit_suggestion` → `outfit_suggestion` (+ `selected_item`) → `create_fit_card` returns text into `fit_card`.

**Scope/lifetime:** one `session` per `run_agent` call (one user query). Nothing persists across queries — each Gradio submit builds a fresh session, so there is no cross-request leakage and the function is safe to call repeatedly. The `error` field doubles as the control signal: the loop and the UI both branch on `session["error"] is None`.

---

## Error Handling

For each tool, describe the specific failure mode you're handling and what the agent does in response.

| Tool | Failure mode | Agent response (exact message + what it offers instead) |
|------|-------------|----------------|
| search_listings | No results match the query (empty list) | Loop sets `session["error"]` and returns early — `suggest_outfit`/`create_fit_card` are **never called**. User sees, in the 🛍️ panel: **"No listings matched 'designer ballgown' under $5. Try raising your price, dropping the size filter, or describing the item more broadly (e.g. 'gown' instead of 'designer ballgown')."** The message echoes the actual parsed terms so the user knows which filter to loosen; other two panels blank. |
| search_listings | Dataset file missing / unreadable (`load_listings()` raises) | Loop's try/except sets `session["error"]` = **"Couldn't load the listings catalog right now — please refresh and try again in a moment."** and returns early. This is an infrastructure fault, not a bad query, so it does **not** suggest changing the search; it tells the user to retry. |
| suggest_outfit | Wardrobe is empty (`items == []`) | **Not an error** — no message, no early return. Tool switches to general-advice mode and returns e.g. **"You don't have a wardrobe saved yet, so here's how to style it from scratch: this graphic tee leans 90s streetwear — pair it with baggy or wide-leg denim, chunky sneakers, and a cropped jacket. Add a wardrobe to get picks using your own pieces."** — which also nudges the user toward adding a wardrobe. Loop proceeds to `create_fit_card`. |
| suggest_outfit | LLM/API failure (no key, network, empty completion) | Tool catches the exception and returns a non-empty fallback that's still useful: **"Couldn't reach the styling model just now, but this piece pairs easily with simple basics — neutral bottoms and clean sneakers. (Outfit ideas will be richer once the connection is back.)"** Loop continues so the user still gets a listing and a fit card. |
| create_fit_card | Outfit input missing or whitespace-only | Guarded before any API call; returns the string **"Can't generate a fit card without an outfit suggestion — try finding an item first so I have a look to caption."** No exception. (The loop won't normally reach this since `suggest_outfit` always returns non-empty text; the guard protects direct/standalone calls.) |
| create_fit_card | LLM/API failure | Tool catches it and returns a fallback caption built from the real item fields so the user still gets shareable text: **"Thrifted this Graphic Tee — 2003 Tour Bootleg Style on depop for $24 ✨ secondhand and styled."** (item title / platform / price interpolated from `new_item`). |

---

## Architecture

```
                        ┌──────────────────────────────────────────────────────┐
                        │                     session dict                      │
                        │  query · parsed · search_results · selected_item ·     │
                        │  wardrobe · outfit_suggestion · fit_card · error       │
                        └──────────────────────────────────────────────────────┘
                            ▲ read/write at every step (single source of truth)
                            │
  User query ──► [ app.py: handle_query ] ──► [ agent.py: run_agent ]
  + wardrobe choice                                  │
                                                     ▼
                                          (1) PARSE query (regex)
                                              description / size / max_price
                                                     │
                                                     ▼
                                          (2) search_listings(parsed) ──► load_listings()  [data/listings.json]
                                                     │
                                  results == [] ─────┼───────────────► set session["error"], RETURN EARLY ──┐
                                                     │ results found                                          │
                                                     ▼                                                        │
                                          select top result → selected_item                                  │
                                                     │                                                        │
                                                     ▼                                                        │
                                          (3) suggest_outfit(selected_item, wardrobe) ──► Groq LLM            │
                                              empty wardrobe → general advice                                 │
                                              API error      → fallback string  (always non-empty)            │
                                                     │                                                        │
                                                     ▼                                                        │
                                          (4) create_fit_card(outfit, selected_item) ──► Groq LLM             │
                                              empty outfit → error string (guarded)                           │
                                              API error    → fallback caption                                 │
                                                     │                                                        │
                                                     ▼                                                        ▼
                                          RETURN session (error is None)                          RETURN session (error set)
                                                     │                                                        │
                                                     └──────────────────────┬─────────────────────────────────┘
                                                                            ▼
                              [ app.py: handle_query maps session → 3 UI panels ]
                              success: listing | outfit | fit_card
                              error:   error message in panel 1, others blank
```

**Triggering:** each tool fires only when the prior step's output passes its gate. `search_listings` always runs; `suggest_outfit` runs only if `search_results` is non-empty; `create_fit_card` runs only if an outfit string came back. The empty-results branch is the one place the chain short-circuits. The `session` dict (top) is read and written at every numbered step.

---

## AI Tool Plan

<!-- For each part of the implementation below, describe:
     - Which AI tool you plan to use (Claude, Copilot, ChatGPT, etc.)
     - What you'll give it as input (which sections of this planning.md, your agent diagram)
     - What you expect it to produce
     - How you'll verify the output matches your spec before moving on

     "I'll use AI to help me code" is not a plan.
     "I'll give Claude my Tool 1 spec (inputs, return value, failure mode) and ask it to implement
     search_listings() using load_listings() from the data loader — then test it against 3 queries
     before trusting it" is a plan. -->

**Tooling choice:** I'll use **Claude (in Claude Code)** as the primary code generator because it can read the actual repo files (`tools.py`, `agent.py`, `utils/data_loader.py`, the JSON data) and match the existing docstrings/signatures, and Copilot inline for small edits while testing. Every generated function is verified against this spec before I move on — generation is cheap, my acceptance bar is the test.

**Milestone 3 — Individual tool implementations:**

- **`search_listings`** — Input to AI: the Tool 1 spec above (params, return fields, the empty-list-not-exception contract) + the `load_listings()` signature from `utils/data_loader.py`. Expected output: a pure-Python function that filters by `max_price`/`size`, scores by keyword overlap on `title`/`description`/`style_tags`, drops zero-score listings, and sorts descending. **Verify before trusting:** run against (a) `"vintage graphic tee"` max_price 30 → expect tee listings, none over $30; (b) `"designer ballgown"` max_price 5 → expect `[]`; (c) `"jeans"` size `"M"` → confirm size filter narrows results. Assert no exception on any of the three.

- **`suggest_outfit`** — Input to AI: the Tool 2 spec + one example listing dict and the example wardrobe shape from `data/wardrobe_schema.json`, plus the `_get_groq_client()` helper already in `tools.py`. Expected output: branches on `wardrobe["items"]` empty vs. non-empty, builds the prompt, calls Groq at temp ~0.7, returns a string, and try/excepts API errors into a fallback. **Verify:** call with example wardrobe → output names real wardrobe pieces ("baggy jeans", "chunky sneakers"); call with empty wardrobe → output is general advice, still non-empty; temporarily unset `GROQ_API_KEY` → returns fallback string, no crash.

- **`create_fit_card`** — Input to AI: the Tool 3 spec + a sample outfit string + sample listing dict. Expected output: empty-outfit guard first, then a Groq call at temp ~0.9 returning a 2–4 sentence caption that names item/price/platform once each. **Verify:** call with `""` → descriptive error string, no API call; call twice with the same real input → captions differ (temperature working); confirm price and platform appear exactly once.

**Milestone 4 — Planning loop and state management:**

- Input to AI: the **Planning Loop**, **State Management**, and **Architecture** sections above + the `_new_session` dict and the step-by-step TODO already in `agent.py`. Expected output: `run_agent` that parses the query (regex per the Planning Loop step 1), threads results through the `session` dict exactly as the State table specifies, gates `suggest_outfit`/`create_fit_card` on the prior step, and wraps each call so exceptions become `session["error"]` + early return.
- **Verify before trusting:** run `python agent.py` — the built-in happy-path query must populate `selected_item`/`outfit_suggestion`/`fit_card` with `error is None`; the `"designer ballgown size XXS under $5"` query must return early with a non-None `error` and `outfit_suggestion`/`fit_card` left `None`. Then wire `app.py: handle_query` (empty-query guard, wardrobe selection, map session → 3 panels) and confirm the no-results example shows the error in panel 1 with the other two blank.

---

## A Complete Interaction (Step by Step)

Write out what a full user interaction looks like from start to finish — tool call by tool call. Use a specific example query.

**What FitFindr does:** FitFindr takes a shopper's natural-language request, finds real secondhand listings that match it, and then helps them picture and share the find as a styled outfit. The planning loop runs three tools in sequence — `search_listings` fires first on the parsed query, `suggest_outfit` fires only if at least one listing was found (using the top result), and `create_fit_card` fires only if a non-empty outfit suggestion came back. Each tool's failure short-circuits the chain: if `search_listings` returns nothing the loop stops and tells the user what to adjust (never calling `suggest_outfit` with empty input), an empty wardrobe makes `suggest_outfit` fall back to general styling advice instead of erroring, and a missing outfit makes `create_fit_card` return a descriptive error string rather than raising.

**Example user query:** "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers. What's out there and how would I style it?"

**Step 0 — Init.** `run_agent` builds a fresh `session` via `_new_session(query, example_wardrobe)`. All output fields start empty: `parsed={}`, `search_results=[]`, `selected_item=None`, `outfit_suggestion=None`, `fit_card=None`, `error=None`.

**Step 1 — Parse (no tool).** The loop runs `parse_query(query)`. Regex pulls `under $30` → `max_price=30.0`; no `size <token>` or standalone size keyword → `size=None`; the price phrase is stripped, leaving `description="vintage graphic tee"` (the styling sentence is ignored for search). **Writes** `session["parsed"] = {"description": "vintage graphic tee", "size": None, "max_price": 30.0}`.

**Step 2 — First tool: `search_listings`.** Called as `search_listings("vintage graphic tee", size=None, max_price=30.0)`. It loads all 40 listings, drops anything over $30, skips the size filter (`size is None`), then scores each remaining listing by keyword overlap against `title`/`description`/`style_tags` and drops zero-score items. **Returns** a `list[dict]` of full listing records, best first:
`[ {id:"lst_006", title:"Graphic Tee — 2003 Tour Bootleg Style", price:24.0, platform:"depop", size:"L", condition:"good", style_tags:["graphic tee","vintage","grunge","streetwear","band tee"], ...}, {id:"lst_033", title:"Vintage Band Tee — Faded Grey", price:19.0, platform:"depop", ...}, ... ]`.
**Gate:** `len(results) > 0` → True. **Writes** `session["search_results"] = results`. **Next:** select top result.

**Step 3 — Select.** `session["selected_item"] = session["search_results"][0]` → the full `lst_006` dict. No tool call; this is the loop wiring the search output into the next tool's input.

**Step 4 — Second tool: `suggest_outfit`.** Called as `suggest_outfit(new_item=<lst_006 dict>, wardrobe=example_wardrobe)`. `wardrobe["items"]` has 10 entries (non-empty), so it builds the "style with named pieces" prompt and calls Groq (~0.7). **Returns** a non-empty `str`, e.g. *"Pair this boxy graphic tee with your baggy dark-wash jeans and chunky white sneakers for an easy 90s streetwear fit. Layer your vintage black denim jacket over the top when it's cooler."* **Writes** `session["outfit_suggestion"] = <that string>`. (Non-empty, so the loop proceeds — no gate failure.) **Next:** make the card.

**Step 5 — Third tool: `create_fit_card`.** Called as `create_fit_card(outfit=<the Step 4 string>, new_item=<lst_006 dict>)`. The outfit string is non-empty (guard passes), so it calls Groq (~0.9). **Returns** a 2–4 sentence caption naming item/price/platform once each, e.g. *"found this 2003 bootleg graphic tee on depop for $24 and it goes SO hard with my baggy jeans 🤎 90s fit fully assembled, chunky sneakers required."* **Writes** `session["fit_card"] = <that string>`.

**Step 6 — Return.** `error is None` and all three fields are populated, so `run_agent` returns the `session`.

**What the user sees (success).** `app.py: handle_query` maps the session to the three UI panels:
- 🛍️ **Top listing found:** "Graphic Tee — 2003 Tour Bootleg Style — $24 · depop · condition: good"
- 👗 **Outfit idea:** the Step 4 suggestion text.
- ✨ **Your fit card:** the Step 5 caption.

**Contrast — the no-results path.** For `"designer ballgown size XXS under $5"`: parse → `description="designer ballgown"`, `size="XXS"`, `max_price=5.0`; `search_listings` returns `[]` (nothing under $5 / no ballgowns). The gate at Step 2 fires the error branch: `session["error"] = "No listings matched. Try raising your price or broadening the description."` and `run_agent` returns immediately. `suggest_outfit` and `create_fit_card` are never called; `selected_item`, `outfit_suggestion`, `fit_card` stay `None`. The UI shows the error string in the 🛍️ panel and leaves the 👗 and ✨ panels blank.
