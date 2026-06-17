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
Searches the mock listings dataset for items that match the user's natural language description, optionally filtered by size and maximum price. Returns a ranked list of matches sorted by keyword relevance score.

**Input parameters:**
- `description` (str): Keywords describing what the user is looking for (e.g., "vintage graphic tee"). Used to score every listing by overlap with title, style_tags, category, colors, and description text.
- `size` (str | None): Size string to filter by, or None to skip. Case-insensitive substring match (e.g., "M" matches "S/M" and "M/L"). Defaults to None.
- `max_price` (float | None): Maximum price ceiling (inclusive). Listings above this price are excluded. Defaults to None.

**What it returns:**
A list of listing dicts sorted by relevance score (highest first). Each dict contains: `id`, `title`, `description`, `category`, `style_tags` (list), `size`, `condition`, `price` (float), `colors` (list), `brand` (str or None), `platform`. Returns an empty list if nothing matches — does not raise.

**What happens if it fails or returns nothing:**
The agent sets `session["error"]` to a helpful message telling the user what to try differently (loosen size/price constraints, try different keywords), then returns early. `suggest_outfit` and `create_fit_card` are never called with empty input.

---

### Tool 2: suggest_outfit

**What it does:**
Given a thrifted item the user is considering and their current wardrobe, uses an LLM to suggest 1–2 complete outfit combinations. If the wardrobe is empty, falls back to general styling advice.

**Input parameters:**
- `new_item` (dict): A listing dict — the item the user found via `search_listings`. Must have at least `title`, `price`, `platform`, `category`, `style_tags`, `colors`, and `description`.
- `wardrobe` (dict): A wardrobe dict with an `items` key containing a list of wardrobe item dicts (each with `name`, `category`, `colors`, `style_tags`, optional `notes`). May be empty.

**What it returns:**
A non-empty string with outfit suggestions. When the wardrobe has items, the suggestions name specific wardrobe pieces. When empty, they describe what types of pieces would pair well.

**What happens if it fails or returns nothing:**
If the wardrobe is empty, the tool switches to a general-styling prompt instead of crashing. If the LLM call fails (exception), the tool returns a descriptive error string rather than propagating the exception. The agent can still continue to `create_fit_card` with whatever string was returned.

---

### Tool 3: create_fit_card

**What it does:**
Generates a short (2–4 sentence), shareable Instagram/TikTok-style OOTD caption that captures the outfit vibe, naturally mentions the item's price and platform, and sounds like a real person wrote it — not a product listing.

**Input parameters:**
- `outfit` (str): The outfit suggestion string returned by `suggest_outfit`.
- `new_item` (dict): The listing dict for the thrifted item (used for title, price, platform, style_tags).

**What it returns:**
A 2–4 sentence caption string. Generated with higher LLM temperature (1.0) so it sounds different each time for different inputs.

**What happens if it fails or returns nothing:**
If `outfit` is empty or whitespace-only, the tool returns a descriptive error message string (does not raise). This guards against being called after a failed `suggest_outfit`.

---

### Additional Tools (if any)

None for the required milestone. See stretch feature section if implemented.

---

## Planning Loop

**How does your agent decide which tool to call next?**

The loop runs sequentially through three stages gated by the previous stage's result:

1. **Parse**: Extract `description`, `size`, and `max_price` from the raw query using regex. Store in `session["parsed"]`. This always runs first.

2. **Search gate**: Call `search_listings(description, size, max_price)`. Store results in `session["search_results"]`. If the list is empty → set `session["error"]` with a helpful retry message and **return early**. The agent never proceeds to outfit suggestion without a real item. This is the primary branching point.

3. **Select**: Pick the top-scored result as `session["selected_item"]`. No branching here — if we have any results, we always use the first one.

4. **Outfit gate**: Call `suggest_outfit(selected_item, wardrobe)`. Store result in `session["outfit_suggestion"]`. The tool itself handles an empty wardrobe by switching prompts — no branching needed at the agent level.

5. **Fit card**: Call `create_fit_card(outfit_suggestion, selected_item)`. Store result in `session["fit_card"]`. The tool guards against empty outfit input internally.

6. **Return**: Return the completed session. The caller checks `session["error"]` to detect early termination.

The loop is not a free-form LLM planner — it is a deterministic sequence with a single early-exit branch on empty search results. This makes the behavior predictable and debuggable.

---

## State Management

**How does information from one tool get passed to the next?**

All state lives in a single `session` dict initialized by `_new_session()`. Fields:

| Key | Set by | Used by |
|-----|--------|---------|
| `query` | `_new_session` | parse step |
| `parsed` | parse step | `search_listings` call |
| `search_results` | `search_listings` | select step |
| `selected_item` | select step | `suggest_outfit`, `create_fit_card` |
| `wardrobe` | `_new_session` | `suggest_outfit` |
| `outfit_suggestion` | `suggest_outfit` | `create_fit_card` |
| `fit_card` | `create_fit_card` | caller / UI |
| `error` | search gate (if empty) | caller / UI |

No tool writes to the session dict directly — the agent loop assigns each tool's return value to the appropriate session key. This keeps tools pure (no side effects on shared state) and makes testing straightforward.

---

## Error Handling

For each tool, describe the specific failure mode you're handling and what the agent does in response.

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| search_listings | No results match the query (wrong size, too low price, unrecognized keywords) | Agent sets `session["error"]` = "No listings matched '[query]'. Try removing the size filter, raising your price ceiling, or using different keywords." Then returns session early. `suggest_outfit` is never called. |
| suggest_outfit | Wardrobe is empty | Tool switches to a general-styling prompt: "what types of pieces pair well with this item" instead of naming specific wardrobe items. Returns a non-empty string — no exception raised. |
| create_fit_card | `outfit` argument is empty or whitespace-only | Tool returns a descriptive error string: "Unable to generate a fit card — outfit suggestion was missing. Please try again." Does not raise an exception. |

---

## Architecture

```
User input (query, wardrobe_choice)
        │
        ▼
┌─────────────────────────────────────────────────────┐
│                   run_agent()                       │
│                                                     │
│  1. _new_session(query, wardrobe)                   │
│        │                                            │
│  2. _parse_query(query)                             │
│        │  → session["parsed"]                       │
│        │    {description, size, max_price}          │
│        │                                            │
│  3. search_listings(description, size, max_price)   │
│        │  → session["search_results"]               │
│        │                                            │
│        ├── empty? ──► session["error"] set          │
│        │               RETURN EARLY ◄───────────────┤
│        │                                            │
│  4. select top result → session["selected_item"]    │
│        │                                            │
│  5. suggest_outfit(selected_item, wardrobe)         │
│        │  → session["outfit_suggestion"]            │
│        │  (empty wardrobe → general styling advice) │
│        │                                            │
│  6. create_fit_card(outfit_suggestion, selected_item│
│        │  → session["fit_card"]                     │
│        │  (empty outfit → error string returned)    │
│        │                                            │
│  7. return session                                  │
└─────────────────────────────────────────────────────┘
        │
        ▼
handle_query() in app.py
  → maps session fields to 3 UI output panels
```

---

## AI Tool Plan

**Milestone 3 — Individual tool implementations:**

- **Tool 1 (search_listings)**: Used Claude with the full Tool 1 spec (inputs, return schema, failure mode, scoring strategy). Gave it the `load_listings()` helper signature and the listings field list. Asked it to implement keyword scoring with per-field weights (style_tags > title > description > category/colors). Verified by running three test queries against the dataset: (a) "vintage graphic tee" → should return lst_006 and lst_033 near top; (b) "cottagecore cardigan" → should return lst_008; (c) "designer ballgown" → should return empty list.

- **Tool 2 (suggest_outfit)**: Used Claude with the Tool 2 spec and the `wardrobe_schema.json` example. Asked it to write two prompt branches (populated vs empty wardrobe) and call Groq. Verified by running with `get_example_wardrobe()` and `get_empty_wardrobe()` separately and reading the outputs.

- **Tool 3 (create_fit_card)**: Used Claude with the Tool 3 spec, the caption style guidelines, and the guard condition for empty outfit. Asked it to use temperature=1.0. Verified by running the same item twice with different outfit strings and confirming the outputs differ.

**Milestone 4 — Planning loop and state management:**

- Used Claude with the Architecture diagram above and the State Management table. Asked it to implement `run_agent()` and `_parse_query()`. Gave it the full session dict structure from `_new_session()`. Verified by running the CLI test at the bottom of `agent.py` and checking both the happy path and the no-results path.

---

## A Complete Interaction (Step by Step)

**Example user query:** "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers. What's out there and how would I style it?"

**Step 1 — Parse:**
The agent runs `_parse_query()` on the query. Regex finds `max_price = 30.0`. No explicit size filter is found. The description becomes `"vintage graphic tee"`. `session["parsed"] = {"description": "vintage graphic tee", "size": None, "max_price": 30.0}`.

**Step 2 — Search:**
`search_listings("vintage graphic tee", size=None, max_price=30.0)` loads all 40 listings, drops any priced over $30, then scores the remainder by keyword overlap. "vintage", "graphic", and "tee" score strongly against listings like lst_006 ("Graphic Tee — 2003 Tour Bootleg Style", $24) and lst_033 ("Vintage Band Tee — Faded Grey", $19). Both match on style_tags ("graphic tee", "vintage") and title words. lst_006 returns as the top result. `session["search_results"]` is a non-empty list, so the agent does not exit early.

**Step 3 — Select:**
`session["selected_item"] = session["search_results"][0]` → the lst_006 listing dict.

**Step 4 — Suggest outfit:**
`suggest_outfit(lst_006, example_wardrobe)` builds a prompt listing the 10 example wardrobe items and asks the LLM to combine the graphic tee with specific pieces. The LLM suggests: "Pair this boxy graphic tee with the baggy straight-leg jeans (w_001) and chunky white sneakers (w_007) for a laid-back 90s streetwear look. Tuck just the front corner for a little shape. Swap the sneakers for the black combat boots (w_008) to shift the vibe grungier." Stored in `session["outfit_suggestion"]`.

**Step 5 — Fit card:**
`create_fit_card(session["outfit_suggestion"], lst_006)` builds a caption prompt with the outfit details and item info, calls the LLM at temperature=1.0. Returns: `"found this faded graphic tee on depop for $24 and it was literally made for my baggy jeans era 🖤 combat boots or chunky sneakers, either way you can't lose. full look details in bio #thriftedfit #ootd"`. Stored in `session["fit_card"]`.

**Final output to user:**
- **Top listing found panel:** Title, price, platform, size, condition, colors, and description of lst_006.
- **Outfit idea panel:** The multi-sentence outfit suggestion naming wardrobe pieces.
- **Your fit card panel:** The Instagram-style caption ready to copy-paste.

**Error path (e.g., "designer ballgown size XXS under $5"):**
After filtering to `max_price=5.0`, `size="XXS"`, no listings survive. `session["error"]` is set to: "No listings matched your search. Try removing the size filter, raising your price ceiling, or using broader keywords." The agent returns early — `suggest_outfit` and `create_fit_card` are never called. The UI shows the error in the first panel and leaves the other two panels empty.
