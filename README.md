# FitFindr

A multi-tool AI agent that helps you find secondhand clothing and figure out how to wear it. Describe what you're looking for — include size and price if you want to filter — and FitFindr searches a dataset of thrift listings, generates outfit combinations based on your wardrobe, and writes a shareable fit card for you.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate          # Mac/Linux
source .venv/Scripts/activate      # Windows (Git Bash)
pip install -r requirements.txt
```

Create a `.env` file in the project root (never commit this):
```
GROQ_API_KEY=your_key_here
```
Get a free key at [console.groq.com](https://console.groq.com) — no credit card required.

**Run the app:**
```bash
python app.py
```
Open the URL shown in your terminal (usually `http://localhost:7860`).

**Run tests:**
```bash
pytest tests/            # all 27 tests (needs GROQ_API_KEY for LLM tests)
pytest tests/ -m "not llm"  # 19 pure tests, no API key needed
```

**Run the agent from the terminal (no UI):**
```bash
python agent.py
```

---

## Tool Inventory

These are the exact function signatures in `tools.py`.

### `search_listings(description, size, max_price)`

**Purpose:** Searches the mock listings dataset for secondhand items matching the user's request. Scores every listing by keyword overlap across its fields and returns results sorted best-first. This is pure Python — no LLM call.

| Parameter | Type | Meaning |
|-----------|------|---------|
| `description` | `str` | Natural language keywords (e.g. `"vintage graphic tee"`). Used to score listings. |
| `size` | `str \| None` | Size string to filter by. Case-insensitive substring match — `"M"` matches `"S/M"` and `"M/L"`. Pass `None` to skip. |
| `max_price` | `float \| None` | Maximum price, inclusive. Listings above this price are excluded before scoring. Pass `None` to skip. |

**Returns:** `list[dict]` — matching listing dicts sorted by relevance score, highest first. Each dict contains: `id`, `title`, `description`, `category`, `style_tags` (list), `size`, `condition`, `price` (float), `colors` (list), `brand` (str or None), `platform`. Returns `[]` if nothing matches — never raises.

**Scoring weights (per keyword hit):** style_tags → 3 · brand → 3 · title → 2 · category → 2 · colors → 2 · description text → 1

---

### `suggest_outfit(new_item, wardrobe)`

**Purpose:** Given the thrifted item and the user's wardrobe, calls the Groq LLM to suggest 1–2 complete outfit combinations. If the wardrobe is empty, falls back to general styling advice without crashing.

| Parameter | Type | Meaning |
|-----------|------|---------|
| `new_item` | `dict` | A listing dict from `search_listings` — the item the user is considering. |
| `wardrobe` | `dict` | Wardrobe dict with an `items` key. Each item has `name`, `category`, `colors`, `style_tags`, optional `notes`. May be empty. |

**Returns:** `str` — a non-empty outfit suggestion. When the wardrobe has items, it names specific pieces by their wardrobe names. When empty, it describes what types of pieces pair well with the item. Returns a descriptive error string (not an exception) if the LLM call fails.

---

### `create_fit_card(outfit, new_item)`

**Purpose:** Generates a short, shareable OOTD-style caption for the thrifted find. Meant to read like a real social media post, not a product description. Uses temperature=1.0 so outputs vary for different inputs.

| Parameter | Type | Meaning |
|-----------|------|---------|
| `outfit` | `str` | The outfit suggestion string from `suggest_outfit`. |
| `new_item` | `dict` | The listing dict — used for title, price, platform, and style_tags. |

**Returns:** `str` — a 2–4 sentence caption that naturally mentions the item name, price, and platform. Returns a descriptive error message string if `outfit` is empty or whitespace-only — never raises.

---

## Planning Loop

The agent runs a deterministic, sequential loop with **one branching point**: whether `search_listings` returned any results.

```
parse query → search → [branch] → select → suggest outfit → fit card → return
                           │
                    results empty?
                           │ yes
                     set session["error"]
                     return early (suggest_outfit and
                     create_fit_card are never called)
```

**Step-by-step decisions:**

1. **Parse** — `_parse_query()` uses regex to extract `description`, `size`, and `max_price` from the user's natural language query. This always runs first.

2. **Search** — calls `search_listings(description, size, max_price)`. Stores results in `session["search_results"]`. **This is the only branching point.** If the list is empty, `session["error"]` is set with a specific message (naming the active filters) and the agent returns immediately. The agent will never call `suggest_outfit` with no item.

3. **Select** — sets `session["selected_item"] = session["search_results"][0]`. The top-scored match is always used. No ranking UI is shown.

4. **Suggest outfit** — calls `suggest_outfit(selected_item, wardrobe)`. No branching here: the tool handles the empty-wardrobe case internally by switching prompts. The agent always gets back a non-empty string.

5. **Fit card** — calls `create_fit_card(outfit_suggestion, selected_item)`. The tool guards its own input (empty outfit → error string). The agent always gets back a string.

6. **Return** — the caller checks `session["error"]` first; if None, all three output fields are populated.

The loop is intentionally not a free-form LLM planner. The behavior is predictable: one path for success, one path for no results, no ambiguity.

---

## State Management

All state lives in a single `session` dict initialized by `_new_session()` at the start of `run_agent()`. No tool writes to the session directly — the agent loop assigns each tool's return value to the appropriate key.

| Key | Written by | Read by |
|-----|-----------|---------|
| `query` | `_new_session` | parse step |
| `parsed` | parse step | `search_listings` call |
| `search_results` | `search_listings` | select step |
| `selected_item` | select step | `suggest_outfit`, `create_fit_card` |
| `wardrobe` | `_new_session` | `suggest_outfit` |
| `outfit_suggestion` | `suggest_outfit` | `create_fit_card` |
| `fit_card` | `create_fit_card` | `handle_query` (UI) |
| `error` | search gate | `handle_query` (UI) |

State passing is explicit: `selected_item` is `search_results[0]` — the same dict object, not a copy — and that dict is the exact input to both `suggest_outfit` and `create_fit_card`. No values are re-entered or hardcoded between steps.

---

## Interaction Walkthrough

**User query:** `"vintage graphic tee under $30"`

**Step 1 — `_parse_query`**
- Input: `"vintage graphic tee under $30"`
- Why: always runs first to extract structured parameters from natural language
- Output: `{"description": "vintage graphic tee", "size": None, "max_price": 30.0}`

**Step 2 — `search_listings`**
- Tool: `search_listings("vintage graphic tee", size=None, max_price=30.0)`
- Why: the agent always searches first; results are required before anything else can run
- Output: 19 matching listings. Top result: `lst_006` — *Graphic Tee — 2003 Tour Bootleg Style*, $24, Depop, size L. It scores highest because "graphic", "tee", and "vintage" all match on title (weight 2) and style_tags (weight 3).
- Branch check: results non-empty → continue

**Step 3 — `suggest_outfit`**
- Tool: `suggest_outfit(lst_006_dict, example_wardrobe)`
- Input flows from Step 2: `selected_item = search_results[0]` (same object reference, no re-entry)
- Why: the item is selected and the wardrobe is populated, so specific outfit combinations are possible
- Output (actual from testing): *"Outfit 1: Pair the Graphic Tee with Baggy straight-leg jeans and Black combat boots. Styling tip: Tuck the Graphic Tee into the jeans to create a more defined silhouette. Outfit 2: Layer the Graphic Tee under the Oversized grey crewneck sweatshirt and pair with Wide-leg khaki trousers and Chunky white sneakers."*

**Step 4 — `create_fit_card`**
- Tool: `create_fit_card(outfit_suggestion, lst_006_dict)`
- Input flows from Step 3: `outfit_suggestion` string, same listing dict
- Why: outfit suggestion is non-empty, so the fit card can be generated
- Output (actual from testing): *"i just scored this sick graphic tee from depop for $24 and i'm obsessed — it's giving me total grunge vibes. i've been styling it two ways: tucked into baggy jeans with black combat boots for a more put-together look, or layered under an oversized grey crewneck with wide-leg khakis and chunky sneakers for a chill, casual feel."*

**Final output to user:**
- **Top listing found:** formatted card with title, price, platform, size, condition, colors, style tags, and description for lst_006
- **Outfit idea:** the multi-sentence suggestion naming specific wardrobe pieces
- **Your fit card:** the Instagram-style caption, ready to copy-paste

---

## Error Handling and Fail Points

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| `search_listings` | No listings survive the price/size filters or match the keywords | `session["error"]` is set to: *"No listings matched your search for "[description]". Suggestions: try removing the size filter (you searched for size '[size]'); try raising your price ceiling (you set max $[price]); try different or broader keywords."* The agent returns immediately — `suggest_outfit` and `create_fit_card` are never called. |
| `suggest_outfit` | Wardrobe `items` list is empty | The tool switches to a general-styling prompt that asks the LLM to describe what *types* of pieces pair well, without referencing any specific owned items. Returns a non-empty suggestion string. The agent continues to `create_fit_card` normally. |
| `create_fit_card` | `outfit` argument is empty or whitespace-only | The tool returns `"Unable to generate a fit card — no outfit suggestion was provided. Make sure search_listings and suggest_outfit ran successfully first."` without making any LLM call. |

**Concrete test evidence (from `pytest tests/ -v`):**

- `test_no_match_returns_empty_list` — `search_listings("designer ballgown", size="XXS", max_price=5.0)` returns `[]`, no exception raised.
- `test_empty_wardrobe_returns_nonempty_string` — `suggest_outfit(item, get_empty_wardrobe())` returns general styling advice, not an error.
- `test_empty_outfit_does_not_raise` — `create_fit_card("", item)` returns the descriptive error string without raising `Exception`.

---

## Spec Reflection

**One way `planning.md` helped during implementation:**

Writing the state management table before touching `agent.py` forced a concrete answer to "who owns what data." Because I specified that `selected_item` is `search_results[0]` — not a copy — I wrote the agent loop with a direct assignment rather than accidentally duplicating or re-fetching data. The table also made the early-exit branch obvious: as soon as `search_results` was written and found empty, I knew exactly what to set and what to skip. Without the table, it would have been easy to add an ad-hoc "check if results is None" somewhere mid-function.

**One divergence from the spec, and why:**

The original spec described two separate gate checks: one for `search_listings` returning empty, and a second gate after `suggest_outfit` before calling `create_fit_card`. The implementation removed the second gate entirely. `suggest_outfit` always returns a non-empty string (it falls back to general advice for an empty wardrobe and catches LLM exceptions), so there is genuinely nothing to branch on before `create_fit_card`. The guard was moved inside `create_fit_card` itself, which is the right place — the tool owns its own preconditions. Keeping a gate in the agent loop that could never trigger would have been dead code and would have implied a failure mode that doesn't exist.

---

## AI Usage

**Instance 1 — implementing `search_listings`**

I gave Claude the Tool 1 spec block from `planning.md` (exact parameter names and types, the field list from `listings.json`, the return value description, and the failure mode) along with the `load_listings()` function signature. I asked it to implement the function using per-field keyword scoring with the weights I had defined (style_tags → 3, title → 2, etc.).

What it produced was correct in structure but used a single flat `in` check across concatenated field strings rather than separate per-field scoring. I overrode this because concatenating fields loses the weight distinctions — a keyword match in a style_tag should score differently than one buried in a 50-word description. I kept the overall structure and rewrote `_score_listing()` to apply weights field-by-field.

**Instance 2 — implementing `_parse_query` in `agent.py`**

I gave Claude the Architecture diagram from `planning.md` and asked it to implement `_parse_query()` with regex extraction of `description`, `size`, and `max_price`. The generated code used span-based slicing to strip each matched clause from the description string (e.g., `description[:match.start()] + description[match.end():]`).

I caught a bug in code review: stripping the price clause first changes the string length, so the size span computed on the original query no longer points to the right position. I replaced the span-slicing approach with sequential `re.sub()` calls on the `description` variable directly — each substitution operates on whatever the string currently looks like, so ordering doesn't cause offset errors. I also discovered a second bug (the `\b(M)\b` pattern matching the `m` in `i'm`) through running the parser against test cases; the fix was adding a negative lookbehind `(?<![a-zA-Z'])` to the standalone-size alternative.

---

## Project Structure

```
fitfindr/
├── data/
│   ├── listings.json          # 40 mock secondhand listings
│   └── wardrobe_schema.json   # Wardrobe format + example wardrobe (10 items)
├── tests/
│   ├── conftest.py            # Registers the "llm" pytest mark
│   └── test_tools.py          # 27 tests: 19 pure + 8 LLM integration
├── utils/
│   └── data_loader.py         # load_listings(), get_example_wardrobe(), get_empty_wardrobe()
├── tools.py                   # The three agent tools
├── agent.py                   # Planning loop: run_agent(), _parse_query()
├── app.py                     # Gradio UI: handle_query()
├── planning.md                # Spec, architecture diagram, AI tool plan
└── requirements.txt
```
