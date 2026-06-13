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
<!-- Describe what this tool does in 1–2 sentences -->

**Input parameters:**
<!-- List each parameter, its type, and what it represents -->
- `description` (str): ...
- `size` (str): ...
- `max_price` (float): ...

**What it returns:**
<!-- Describe the return value — what fields does a result contain? -->

**What happens if it fails or returns nothing:**
<!-- What should the agent do if no listings match? -->

---

### Tool 2: suggest_outfit

**What it does:**
<!-- Describe what this tool does in 1–2 sentences -->

**Input parameters:**
<!-- List each parameter, its type, and what it represents -->
- `new_item` (dict): ...
- `wardrobe` (dict): ...

**What it returns:**
<!-- Describe the return value -->

**What happens if it fails or returns nothing:**
<!-- What should the agent do if the wardrobe is empty or no outfit can be suggested? -->

---

### Tool 3: create_fit_card

**What it does:**
<!-- Describe what this tool does in 1–2 sentences -->

**Input parameters:**
<!-- List each parameter, its type, and what it represents -->
- `outfit` (...): ...

**What it returns:**
<!-- Describe the return value -->

**What happens if it fails or returns nothing:**
<!-- What should the agent do if the outfit data is incomplete? -->

---

### Additional Tools (if any)

<!-- Copy the block above for any tools beyond the required three -->

---

## Planning Loop

**How does your agent decide which tool to call next?**
<!-- Describe the logic your planning loop uses. What does it look at? What conditions change its behavior? How does it know when it's done? -->

---

## State Management

**How does information from one tool get passed to the next?**
<!-- Describe how your agent stores and accesses state within a session. What data is tracked? How is it passed between tool calls? -->

---

## Error Handling

For each tool, describe the specific failure mode you're handling and what the agent does in response.

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| search_listings | No results match the query | |
| suggest_outfit | Wardrobe is empty | |
| create_fit_card | Outfit input is missing or incomplete | |

---

## Architecture

<!-- Draw a diagram of your agent showing how the components connect:
     User input → Planning Loop → Tools (search_listings, suggest_outfit, create_fit_card)
                                                                          ↕
                                                                   State / Session
     Show what triggers each tool, how state flows between them, and where error paths branch off.
     ASCII art, a Mermaid diagram (https://mermaid.js.org/syntax/flowchart.html), or an embedded
     sketch are all fine. You'll share this diagram with an AI tool when asking it to implement
     the planning loop and each individual tool. -->

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

**Milestone 3 — Individual tool implementations:**

**Milestone 4 — Planning loop and state management:**

---

## A Complete Interaction (Step by Step)

Write out what a full user interaction looks like from start to finish — tool call by tool call. Use a specific example query.

**What FitFindr does:** FitFindr takes a shopper's natural-language request, finds real secondhand listings that match it, and then helps them picture and share the find as a styled outfit. The planning loop runs three tools in sequence — `search_listings` fires first on the parsed query, `suggest_outfit` fires only if at least one listing was found (using the top result), and `create_fit_card` fires only if a non-empty outfit suggestion came back. Each tool's failure short-circuits the chain: if `search_listings` returns nothing the loop stops and tells the user what to adjust (never calling `suggest_outfit` with empty input), an empty wardrobe makes `suggest_outfit` fall back to general styling advice instead of erroring, and a missing outfit makes `create_fit_card` return a descriptive error string rather than raising.

**Example user query:** "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers. What's out there and how would I style it?"

**Step 1 — Parse + search.** The loop parses the query into `description="vintage graphic tee"`, `size=None`, `max_price=30.0`, then calls `search_listings("vintage graphic tee", size=None, max_price=30.0)`. Items over $30 are dropped; the rest are scored on keyword overlap against title, description, and `style_tags`. The top matches are `lst_006` ("Graphic Tee — 2003 Tour Bootleg Style", $24, depop) and `lst_033` ("Vintage Band Tee — Faded Grey", $19, depop), both tagged `vintage` + `graphic tee`. The list is non-empty, so the loop continues.

**Step 2 — Select + suggest.** The loop selects the top-scored result (`lst_006`, the bootleg graphic tee) as `selected_item` and calls `suggest_outfit(new_item=lst_006, wardrobe=example_wardrobe)`. The wardrobe is non-empty, so the LLM is asked to build outfits from named pieces — it returns something like: "Pair this boxy graphic tee with your baggy dark-wash jeans and chunky white sneakers for an easy 90s streetwear fit. Layer your vintage black denim jacket over the top when it's cooler." The string is non-empty, so the loop continues.

**Step 3 — Fit card.** The loop calls `create_fit_card(outfit=<the suggestion above>, new_item=lst_006)`. It returns a casual, shareable caption naming the item, price, and platform once each — e.g. "found this 2003 bootleg graphic tee on depop for $24 and it goes SO hard with my baggy jeans 🤎 90s fit fully assembled, chunky sneakers required."

**Final output to user:** The completed session shows the selected listing (title, price, platform, condition), the outfit suggestion, and the fit-card caption, with `session["error"] == None`. (On the no-results path — e.g. "designer ballgown size XXS under $5" — the user instead sees only the error message suggesting they loosen the price or broaden the search, and no outfit or card is generated.)
