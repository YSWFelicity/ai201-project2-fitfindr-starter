# FitFindr 🛍️

FitFindr takes a shopper's natural-language request, finds matching secondhand
listings, and then helps them picture and share the find as a styled outfit. It
runs three tools in a fixed, condition-gated planning loop and exposes them
through a small Gradio UI.

```
ai201-project2-fitfindr-starter/
├── app.py                     # Gradio UI + handle_query() (maps session → 3 panels)
├── agent.py                   # run_agent() planning loop + parse_query() + session state
├── tools.py                   # The three tools: search_listings / suggest_outfit / create_fit_card
├── planning.md                # Full design doc (planning loop, state, error handling, AI plan)
├── data/
│   ├── listings.json          # 40 mock secondhand listings
│   └── wardrobe_schema.json   # Wardrobe format + example/empty wardrobes
├── utils/data_loader.py       # load_listings(), get_example_wardrobe(), get_empty_wardrobe()
└── tests/                     # pytest suite
```

## Setup & Run

```bash
pip install -r requirements.txt
```

The two styling tools call the Groq API. Put your key in a `.env` file in the
project root (free key at [console.groq.com](https://console.groq.com)):

```
GROQ_API_KEY=your_key_here
```

Then launch the app and open the localhost URL shown in your terminal
(usually <http://localhost:7860>):

```bash
python app.py
```

You can also exercise the loop directly from the CLI with `python agent.py`
(runs a happy-path query and the no-results path).

---

## Tool Inventory

The three required tools live in [tools.py](tools.py). Each is a standalone
function that can be called and tested in isolation.

### 1. `search_listings` — find matching listings

| | |
|---|---|
| **Inputs** | `description: str` (keywords, e.g. `"vintage graphic tee"`), `size: str \| None` (filter, case-insensitive substring match — `"M"` matches `"S/M"`; `None` skips), `max_price: float \| None` (inclusive ceiling; `None` skips) |
| **Output** | `list[dict]` — matching listing dicts sorted by relevance (best first). **Returns `[]` when nothing matches — never raises.** Each dict has `id, title, description, category, style_tags, size, condition, price, colors, brand, platform`. |
| **Purpose** | Filter the 40-item mock catalog by hard constraints (price, size), then rank the rest by keyword overlap against each listing's `title` / `description` / `style_tags` (style-tag hits weighted higher). Zero-score listings are dropped. This is the only tool that always runs; its result gates the rest of the loop. |

Regex/keyword scoring is used here instead of an LLM call — it's fast,
deterministic, and free on a step that's easy to do reliably.

### 2. `suggest_outfit` — style the item

| | |
|---|---|
| **Inputs** | `new_item: dict` (a listing dict, normally the top search result), `wardrobe: dict` (has an `"items"` list; may be empty) |
| **Output** | `str` — a non-empty outfit suggestion. Names specific wardrobe pieces when the wardrobe is non-empty; gives general styling advice when it's empty. |
| **Purpose** | Turn a found listing into wearable outfit ideas. Branches on whether the wardrobe has items: non-empty → "combine the new piece with these named pieces" prompt (Groq, temp ~0.7); empty → general styling advice plus a nudge to add a wardrobe. Always returns usable text so the loop can continue. |

### 3. `create_fit_card` — write a shareable caption

| | |
|---|---|
| **Inputs** | `outfit: str` (the suggestion from `suggest_outfit`), `new_item: dict` (the listing being styled) |
| **Output** | `str` — a 2–4 sentence OOTD-style caption that mentions the item name, price, and platform once each. Returns a descriptive error string (does **not** raise) if `outfit` is empty/whitespace. |
| **Purpose** | Produce a casual, social-ready caption for the find (Groq, temp ~0.9 so repeated calls vary). Guards against an empty outfit before any API call. |

---

## Planning Loop

The agent does **not** use an open-ended, LLM-driven "decide the next tool"
loop. The three tools have a natural dependency order — you can't style an item
you haven't found, and you can't caption an outfit you haven't styled — so the
plan is a **fixed, condition-gated pipeline** in [`run_agent()`](agent.py#L107).
Each step's *output* decides whether the next step runs.

```
(1) PARSE query (regex) ─► description / size / max_price
            │
            ▼
(2) search_listings(parsed)
            │
   results == [] ──► set session["error"], RETURN EARLY  ◄── primary branch point
            │ results found
            ▼
    select top result → selected_item
            │
            ▼
(3) suggest_outfit(selected_item, wardrobe)   (always returns non-empty text)
            │
            ▼
(4) create_fit_card(outfit, selected_item)
            │
            ▼
    RETURN session (error is None, all three fields populated)
```

1. **Parse** the query into `description` / `size` / `max_price` with regex.
2. **Search, then gate on results.** Call `search_listings`. **If the list is
   empty, set `session["error"]` and return early** — `suggest_outfit` is never
   called with empty input. This is the one place the chain short-circuits on a
   normal (non-exception) path.
3. **Select** the top-scored listing as `selected_item`.
4. **Suggest** an outfit. This tool always returns non-empty text, so it doesn't
   gate the next step (the loop still defensively checks for a truthy string).
5. **Card** — turn the outfit into a shareable caption.
6. **Return** the session: done when either it returned early with an `error`,
   or all three output fields are populated and `error is None`.

Every tool call is wrapped in `try/except` so an unexpected exception becomes
`session["error"]` + an early return — the loop never crashes its Gradio caller.

---

## State Management

All state for one interaction lives in a single **`session` dict** created by
[`_new_session(query, wardrobe)`](agent.py#L83). It is the single source of
truth; the tools are stateless and the loop threads data between them by reading
one field and writing the next.

| Field | Written by | Read by | Purpose |
|-------|-----------|---------|---------|
| `query` | `_new_session` | parse step | original user text |
| `parsed` | parse step | `search_listings` | `{description, size, max_price}` |
| `search_results` | `search_listings` | result gate | ranked listing dicts |
| `selected_item` | result gate (top result) | `suggest_outfit`, `create_fit_card`, UI | the listing being styled |
| `wardrobe` | `_new_session` | `suggest_outfit` | the user's closet (example or empty) |
| `outfit_suggestion` | `suggest_outfit` | `create_fit_card`, UI | styling text |
| `fit_card` | `create_fit_card` | UI | shareable caption |
| `error` | any step on failure | UI / early return | non-`None` ⇒ interaction ended early |

**Data flow:** `parsed` → `search_listings` returns a list → loop picks
`search_results[0]` as `selected_item` → `selected_item` (+ `wardrobe`) →
`suggest_outfit` → `outfit_suggestion` (+ `selected_item`) → `create_fit_card` →
`fit_card`.

**Scope/lifetime:** one `session` per `run_agent` call (one user query). Nothing
persists across queries — each Gradio submit builds a fresh session, so there's
no cross-request leakage. The `error` field doubles as the control signal: both
the loop and `app.py: handle_query` branch on `session["error"] is None`.

---

## Error Handling (per tool)

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| `search_listings` | **No results match** (empty list) | Loop sets `session["error"]` and returns early — the styling tools are **never called**. Message echoes the actual parsed terms so the user knows which filter to loosen; the other two UI panels stay blank. |
| `search_listings` | Catalog file missing / unreadable (`load_listings()` raises) | Loop `try/except` sets `session["error"] = "Couldn't load the listings catalog right now — please refresh and try again in a moment."` and returns early. Framed as an infra fault (retry), not a bad query. |
| `suggest_outfit` | **Empty wardrobe** (`items == []`) | *Not an error.* Tool switches to general-advice mode and returns non-empty text plus a nudge to add a wardrobe. Loop proceeds normally. |
| `suggest_outfit` | LLM/API failure (no key, network, empty completion) | Tool catches it and returns a still-useful fallback string ("…pairs easily with simple basics — neutral bottoms and clean sneakers…"). Loop continues, so the user still gets a listing and a fit card. |
| `create_fit_card` | Outfit input missing / whitespace-only | Guarded before any API call; returns a descriptive error string, no exception. |
| `create_fit_card` | LLM/API failure | Catches it and returns a fallback caption built from the real item fields (title / platform / price), so the user still gets shareable text. |

### Concrete example from testing

Running the deliberate no-results query through the full app:

```python
>>> import app
>>> app.handle_query("designer ballgown size XXS under $5", "Example wardrobe")
("No listings matched 'designer ballgown' under $5. Try raising your price, "
 "dropping the size filter, or describing the item more broadly.", "", "")
```

The parse step extracted `description="designer ballgown"`, `size="XXS"`,
`max_price=5.0`; `search_listings` returned `[]`; the loop hit the empty-results
gate, set `session["error"]`, and returned early. `suggest_outfit` and
`create_fit_card` were never called, so `outfit_suggestion` and `fit_card`
stayed `None` and the 👗 / ✨ panels rendered blank — exactly the intended
short-circuit. The empty-query guard in `handle_query` behaves the same way:
`handle_query("", "Example wardrobe")` returns
`("Please describe what you're looking for.", "", "")` without ever invoking the
agent.

---

## Spec Reflection

**What the spec got right.** Forcing three tools with a clear input/output
contract made the dependency order obvious, which is why a fixed pipeline beat an
LLM-driven planner here: the "decision" is fully determined by data
(found-anything? have-an-outfit?), so an LLM router would have added cost and
nondeterminism for no benefit. Requiring an empty-list-not-exception contract on
`search_listings` and an always-non-empty return from `suggest_outfit` is what
let the loop stay simple — only one normal-path branch (empty results) and a thin
`try/except` safety net around everything else.

**Where I deviated / extended.** The spec leaves query parsing open ("regex,
string splitting, or LLM"). I chose regex (`parse_query`) for speed, determinism,
and zero API cost — the trade-off is that it's brittle to unusual phrasings (it
keys off "under/below/less than" and a small set of size tokens), which is
acceptable for this dataset but would need an LLM fallback in production. I also
added defensive `try/except` wrappers in the loop that the spec didn't strictly
require, because the styling tools make network calls and Gradio shouldn't crash
on an API hiccup.

**Limitations.** Keyword-overlap search has no synonym/semantic understanding
("tee" won't match a listing that only says "t-shirt"), and the no-results
message is the main mitigation. There's no pagination or "show me more" — the
loop always styles `search_results[0]`. State is per-request only; there's no
session history or learning across queries.

---

## AI Usage

I used **Claude (in Claude Code)** as the primary code generator, working from
the specs in `planning.md` rather than vague prompts. Claude could read the
actual repo files, so generated code matched the existing docstrings and
signatures. My acceptance bar was always a test, not the generation itself.

**Instance 1 — `search_listings` (Milestone 3).**
*Input I gave the AI:* the **Tool 1** section of `planning.md` (parameter names
and types, the return-fields list, and the explicit "returns `[]`, never raises"
contract), plus the `load_listings()` signature from `utils/data_loader.py`.
*What it produced:* a pure-Python function that filtered by `max_price`/`size`
and scored listings by keyword overlap on `title`/`description`/`style_tags`.
*What I changed/overrode:* the first version treated the size filter as an exact
string match, which dropped `"M"` against the dataset's `"S/M"` values. I
overrode it to a case-insensitive **substring** match (`size_filter in
listing["size"].lower()`). I also added a stopword set and a small extra weight
for style-tag matches, because the raw overlap score ranked a description that
merely mentioned "vintage" above an actual graphic tee. I verified with three
queries (a tee search under $30, the `designer ballgown` no-match, and a
size-filtered `jeans` search) before trusting it.

**Instance 2 — the planning loop / state management (Milestone 4).**
*Input I gave the AI:* the **Planning Loop**, **State Management**, and
**Architecture** sections of `planning.md` (including the architecture diagram
and the `session`-field table), plus the `_new_session` dict and the numbered
TODO already in `agent.py`. *What it produced:* a `run_agent` that parsed the
query, threaded results through the `session` dict per the state table, and gated
each tool on the prior step's output. *What I changed/overrode:* the draft only
gated on empty results but didn't wrap the tool calls, so an API exception would
have propagated out to Gradio. I added the `try/except` → `session["error"]` +
early-return pattern around each call (matching the Error Handling table). I also
overrode the no-results message to **interpolate the actual parsed terms**
(`description` and `max_price`) instead of a generic string, so the user can see
which filter to loosen. I verified by running `python agent.py` (happy path
populates all three fields with `error is None`; the ballgown query returns early
with a non-`None` error and `None` for the styling fields) and then confirmed the
no-results example in the Gradio UI shows the error in panel 1 with the other two
blank.
