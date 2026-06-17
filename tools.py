"""
tools.py

The three required FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str
"""

import os

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

load_dotenv()

# Common English stopwords to exclude from keyword scoring
_STOPWORDS = {
    "a", "an", "the", "for", "in", "of", "with", "and", "or", "is",
    "i", "i'm", "looking", "find", "me", "want", "need", "get", "some",
    "to", "that", "this", "it", "on", "at", "by", "be", "my", "im",
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


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def _score_listing(listing: dict, keywords: set[str]) -> int:
    """
    Score a single listing by keyword overlap across all searchable fields.

    Weights (per keyword hit):
        style_tags  → 3  (curated descriptors, highest signal)
        title       → 2  (short, dense signal)
        category    → 2
        colors      → 2
        brand       → 3
        description → 1  (longer prose, lower density)
    """
    score = 0

    # Title: split on whitespace and punctuation
    title_words = set(listing["title"].lower().replace("—", " ").replace("-", " ").split())
    score += len(keywords & title_words) * 2

    # Style tags: check whether any keyword appears anywhere in the tag text
    tags_text = " ".join(listing["style_tags"]).lower()
    for kw in keywords:
        if kw in tags_text:
            score += 3

    # Description prose
    desc_words = set(listing["description"].lower().split())
    score += len(keywords & desc_words) * 1

    # Category
    category_lower = listing["category"].lower()
    for kw in keywords:
        if kw in category_lower:
            score += 2

    # Colors
    colors_text = " ".join(listing["colors"]).lower()
    for kw in keywords:
        if kw in colors_text:
            score += 2

    # Brand
    if listing.get("brand"):
        brand_lower = listing["brand"].lower()
        for kw in keywords:
            if kw in brand_lower:
                score += 3

    return score


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
    """
    listings = load_listings()

    # ── Filter by price ───────────────────────────────────────────────────────
    if max_price is not None:
        listings = [l for l in listings if l["price"] <= max_price]

    # ── Filter by size ────────────────────────────────────────────────────────
    if size is not None:
        size_lower = size.lower().strip()
        listings = [
            l for l in listings
            if size_lower in l["size"].lower()
        ]

    # ── Keyword scoring ───────────────────────────────────────────────────────
    raw_words = set(description.lower().split())
    keywords = raw_words - _STOPWORDS
    if not keywords:
        # If all words were stopwords, fall back to using every word
        keywords = raw_words

    scored = []
    for listing in listings:
        s = _score_listing(listing, keywords)
        if s > 0:
            scored.append((s, listing))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [listing for _, listing in scored]


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(new_item: dict, wardrobe: dict) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key. May be empty.

    Returns:
        A non-empty string with outfit suggestions. Falls back to general
        styling advice when the wardrobe is empty. Returns a descriptive
        error string if the LLM call fails — does NOT raise.
    """
    item_summary = (
        f"{new_item['title']} "
        f"(${new_item['price']:.0f}, {new_item.get('condition', 'unknown')} condition, "
        f"from {new_item.get('platform', 'unknown')})"
    )
    item_detail = (
        f"Category: {new_item.get('category', 'unknown')}\n"
        f"Style tags: {', '.join(new_item.get('style_tags', []))}\n"
        f"Colors: {', '.join(new_item.get('colors', []))}\n"
        f"Description: {new_item.get('description', '')}"
    )

    wardrobe_items = wardrobe.get("items", [])

    if not wardrobe_items:
        # Empty wardrobe — give general styling advice
        prompt = (
            f"You are a fashion stylist specializing in thrifted and vintage clothing.\n\n"
            f"A user just found this item: {item_summary}\n\n"
            f"{item_detail}\n\n"
            f"The user hasn't told you what else is in their closet. Suggest 1–2 complete "
            f"outfit ideas that would work well with this piece. Describe the types of items "
            f"that pair well (e.g., 'a high-waisted wide-leg trouser' rather than a specific "
            f"owned piece). Include one practical styling tip per outfit.\n\n"
            f"Keep it under 150 words total."
        )
    else:
        wardrobe_lines = []
        for item in wardrobe_items:
            line = (
                f"- {item['name']} ({item['category']}, "
                f"colors: {', '.join(item['colors'])}, "
                f"style: {', '.join(item['style_tags'])})"
            )
            if item.get("notes"):
                line += f" — {item['notes']}"
            wardrobe_lines.append(line)
        wardrobe_text = "\n".join(wardrobe_lines)

        prompt = (
            f"You are a fashion stylist specializing in thrifted and vintage clothing.\n\n"
            f"A user just found this thrifted item: {item_summary}\n\n"
            f"{item_detail}\n\n"
            f"Their wardrobe:\n{wardrobe_text}\n\n"
            f"Suggest 1–2 specific outfit combinations using the new item paired with "
            f"pieces already in their wardrobe. Name the specific wardrobe items you're "
            f"pairing with (use the names exactly as listed). Include one brief styling tip "
            f"per outfit (tucking, rolling sleeves, layering order, etc.).\n\n"
            f"Keep it under 150 words total."
        )

    try:
        client = _get_groq_client()
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=350,
        )
        return response.choices[0].message.content.strip()
    except Exception as exc:
        return f"Outfit suggestion unavailable right now ({exc}). Try again in a moment."


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.

    Returns:
        A 2–4 sentence string usable as an Instagram/TikTok caption.
        Returns a descriptive error string if outfit is empty or the LLM fails.
    """
    if not outfit or not outfit.strip():
        return (
            "Unable to generate a fit card — no outfit suggestion was provided. "
            "Make sure search_listings and suggest_outfit ran successfully first."
        )

    item_summary = (
        f"{new_item['title']} "
        f"(${new_item['price']:.0f} from {new_item.get('platform', 'unknown')})"
    )
    style_vibe = ", ".join(new_item.get("style_tags", []))

    prompt = (
        f"Write a 2–4 sentence Instagram/TikTok OOTD caption for a thrifted outfit.\n\n"
        f"Item found: {item_summary}\n"
        f"Style vibe: {style_vibe}\n"
        f"Outfit: {outfit}\n\n"
        f"Rules:\n"
        f"- Sound like a real person's OOTD post, NOT a product description or ad copy\n"
        f"- Be casual, specific, and authentic — use natural lowercase if it fits\n"
        f"- Mention the item name, price, and platform naturally (once each, worked into the text)\n"
        f"- Capture the overall outfit energy with specific descriptors\n"
        f"- 2–4 sentences maximum\n"
        f"- You may include 1–2 hashtags or a casual sign-off if it sounds right\n\n"
        f"Output ONLY the caption text — no intro, no label, no explanation."
    )

    try:
        client = _get_groq_client()
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=1.0,
            max_tokens=150,
        )
        return response.choices[0].message.content.strip()
    except Exception as exc:
        return f"Fit card generation failed ({exc}). Try again in a moment."
