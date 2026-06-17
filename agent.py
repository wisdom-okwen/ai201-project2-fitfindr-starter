"""
agent.py

The FitFindr planning loop. Orchestrates the three tools in response to a
natural language user query, passing state between them via a session dict.

Usage:
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


# ── session state ─────────────────────────────────────────────────────────────

def _new_session(query: str, wardrobe: dict) -> dict:
    """
    Initialize and return a fresh session dict for one user interaction.

    The session dict is the single source of truth for everything that happens
    during a run — it stores the original query, parsed parameters, tool results,
    and any error that caused early termination.
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


# ── query parser ──────────────────────────────────────────────────────────────

def _parse_query(query: str) -> dict:
    """
    Extract description, size, and max_price from a natural language query
    using regex. Returns a dict with keys: description (str), size (str|None),
    max_price (float|None).

    Examples:
        "vintage graphic tee under $30, size M"
        → {"description": "vintage graphic tee", "size": "M", "max_price": 30.0}

        "looking for a 90s windbreaker in L under $50"
        → {"description": "90s windbreaker", "size": "L", "max_price": 50.0}
    """
    # ── Extract max_price ─────────────────────────────────────────────────────
    price_pattern = r'(?:under|max|less than|below|up to|for under|at most)\s*\$?\s*(\d+(?:\.\d+)?)'
    price_match = re.search(price_pattern, query, re.IGNORECASE)
    max_price = float(price_match.group(1)) if price_match else None

    # ── Extract size ──────────────────────────────────────────────────────────
    # Three sub-patterns in priority order:
    #   1. "size M" / "size S/M"
    #   2. "in L" / "in a XL"
    #   3. Standalone size code — negative lookbehind for apostrophe prevents
    #      matching the 'm' in "i'm" (apostrophe is a non-word char so \b fires
    #      there, but (?<![a-zA-Z']) kills those false positives)
    size_pattern = (
        r'(?:'
        r'(?:size\s+)([A-Za-z0-9]+(?:/[A-Za-z0-9]+)?)'
        r'|'
        r'(?:in\s+(?:a\s+)?)([A-Za-z]{1,3}(?:/[A-Za-z]{1,3})?)\b'
        r'|'
        r"(?<![a-zA-Z'])\b(XS|S|M|L|XL|XXL|XXXL)\b(?![a-zA-Z'])"
        r')'
    )
    size_match = re.search(size_pattern, query, re.IGNORECASE)
    size = None
    if size_match:
        raw = size_match.group(1) or size_match.group(2) or size_match.group(3)
        _non_sizes = {"a", "an", "the", "for", "or", "of", "on", "at", "be", "in"}
        if raw and raw.lower() not in _non_sizes:
            size = raw.upper()

    # ── Build clean description via re.sub (not span slicing) ─────────────────
    # Using substitution avoids offset bugs when multiple clauses are removed
    # from the same string in sequence.
    description = query

    # Remove price clause
    description = re.sub(
        r'(?:under|max|less than|below|up to|for under|at most)\s*\$?\s*\d+(?:\.\d+)?',
        ' ', description, flags=re.IGNORECASE,
    )

    # Remove "size X" and ", size X" size clauses
    description = re.sub(
        r'(?:,\s*)?size\s+[A-Za-z0-9]+(?:/[A-Za-z0-9]+)?',
        ' ', description, flags=re.IGNORECASE,
    )

    # Remove "in X" / "in a X" when X is a recognized size code
    description = re.sub(
        r'\bin\s+(?:a\s+)?(?:XS|S|M|L|XL|XXL|XXXL)\b',
        ' ', description, flags=re.IGNORECASE,
    )

    # Remove common filler phrases
    filler_patterns = [
        r"i'?m?\s+looking\s+for",
        r"looking\s+for",
        r"find\s+me",
        r"i\s+want",
        r"i\s+need",
        r"can\s+you\s+find",
        r"searching\s+for",
        r"any\s+good",
    ]
    for pattern in filler_patterns:
        description = re.sub(pattern, ' ', description, flags=re.IGNORECASE)

    # Normalize punctuation and whitespace, strip leading articles
    description = re.sub(r"[,;]+", " ", description)
    description = " ".join(description.split()).strip()
    description = re.sub(r"^(?:a|an|the)\s+", "", description, flags=re.IGNORECASE)

    return {
        "description": description,
        "size": size,
        "max_price": max_price,
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
        first — if it is not None, the interaction ended early.
    """
    # ── Step 1: Initialize session ────────────────────────────────────────────
    session = _new_session(query, wardrobe)

    # ── Step 2: Parse the query ───────────────────────────────────────────────
    parsed = _parse_query(query)
    session["parsed"] = parsed

    description = parsed["description"]
    size = parsed["size"]
    max_price = parsed["max_price"]

    # ── Step 3: Search for listings ───────────────────────────────────────────
    results = search_listings(description, size=size, max_price=max_price)
    session["search_results"] = results

    if not results:
        # Build a helpful error message based on which filters were active
        hints = []
        if size:
            hints.append(f"try removing the size filter (you searched for size '{size}')")
        if max_price is not None:
            hints.append(f"try raising your price ceiling (you set max ${max_price:.0f})")
        hints.append("try different or broader keywords")
        hint_text = "; ".join(hints)

        session["error"] = (
            f"No listings matched your search for \"{description}\". "
            f"Suggestions: {hint_text}."
        )
        return session

    # ── Step 4: Select the top result ─────────────────────────────────────────
    session["selected_item"] = results[0]

    # ── Step 5: Suggest an outfit ─────────────────────────────────────────────
    outfit = suggest_outfit(session["selected_item"], wardrobe)
    session["outfit_suggestion"] = outfit

    # ── Step 6: Generate a fit card ───────────────────────────────────────────
    fit_card = create_fit_card(outfit, session["selected_item"])
    session["fit_card"] = fit_card

    # ── Step 7: Return the completed session ──────────────────────────────────
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

    print("\n\n=== Empty wardrobe path ===\n")
    session3 = run_agent(
        query="vintage flannel shirt",
        wardrobe=get_empty_wardrobe(),
    )
    if session3["error"]:
        print(f"Error: {session3['error']}")
    else:
        print(f"Found: {session3['selected_item']['title']}")
        print(f"\nOutfit (empty wardrobe): {session3['outfit_suggestion']}")
        print(f"\nFit card: {session3['fit_card']}")
