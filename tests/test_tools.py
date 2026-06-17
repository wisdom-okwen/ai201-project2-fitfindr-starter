"""
tests/test_tools.py

Isolated tests for every tool in tools.py.

Tests are split into two groups:
  - Pure tests: no API key required — test data filtering, guard conditions,
    and anything that runs before an LLM call.
  - Integration tests: marked with @pytest.mark.skipif; skipped automatically
    when GROQ_API_KEY is not set so CI never fails on a missing key.

Run all tests:
    pytest tests/

Run only pure tests (no LLM):
    pytest tests/ -m "not llm"
"""

import os
import pytest

from tools import search_listings, suggest_outfit, create_fit_card
from utils.data_loader import (
    load_listings,
    get_example_wardrobe,
    get_empty_wardrobe,
)

# ── helpers ───────────────────────────────────────────────────────────────────

_requires_api = pytest.mark.skipif(
    not os.getenv("GROQ_API_KEY"),
    reason="GROQ_API_KEY not set — skipping LLM integration test",
)

# A real listing from the dataset used across multiple tests
def _get_listing(listing_id: str) -> dict:
    return next(l for l in load_listings() if l["id"] == listing_id)


# ═══════════════════════════════════════════════════════════════════════════════
# Tool 1: search_listings
# ═══════════════════════════════════════════════════════════════════════════════

class TestSearchListings:

    # ── Basic return type and non-empty result ─────────────────────────────────

    def test_returns_list(self):
        results = search_listings("vintage graphic tee")
        assert isinstance(results, list)

    def test_returns_results_for_known_query(self):
        results = search_listings("vintage graphic tee")
        assert len(results) > 0, "expected at least one match for 'vintage graphic tee'"

    def test_each_result_is_a_dict_with_required_fields(self):
        results = search_listings("vintage jacket")
        assert len(results) > 0
        required = {"id", "title", "description", "category", "style_tags",
                    "size", "condition", "price", "colors", "platform"}
        for item in results:
            assert required.issubset(item.keys()), f"missing fields in {item['id']}"

    # ── Relevance order ────────────────────────────────────────────────────────

    def test_graphic_tee_top_result_is_lst006(self):
        """lst_006 (Graphic Tee — 2003 Tour Bootleg) should outscore everything
        else for 'vintage graphic tee' because it matches on title, style_tags,
        and description."""
        results = search_listings("vintage graphic tee")
        assert results[0]["id"] == "lst_006"

    def test_cottagecore_cardigan_top_result_is_lst008(self):
        results = search_listings("cottagecore cardigan")
        assert results[0]["id"] == "lst_008"

    # ── Price filter ───────────────────────────────────────────────────────────

    def test_price_filter_excludes_over_limit(self):
        results = search_listings("jacket", max_price=30.0)
        assert all(item["price"] <= 30.0 for item in results), (
            "price filter failed — result above max_price"
        )

    def test_price_filter_inclusive_boundary(self):
        # lst_037 Straight Leg Black Jeans is exactly $30
        results = search_listings("black jeans", max_price=30.0)
        prices = [r["price"] for r in results]
        assert 30.0 in prices, "expected an item priced exactly at the boundary to be included"

    def test_price_filter_zero_budget_returns_empty(self):
        results = search_listings("vintage tee", max_price=0.0)
        assert results == []

    # ── Size filter ────────────────────────────────────────────────────────────

    def test_size_filter_excludes_wrong_sizes(self):
        results = search_listings("vintage top", size="M")
        for item in results:
            assert "m" in item["size"].lower(), (
                f"size filter failed: '{item['size']}' does not contain 'M'"
            )

    def test_size_filter_case_insensitive(self):
        results_upper = search_listings("tee", size="M")
        results_lower = search_listings("tee", size="m")
        assert len(results_upper) == len(results_lower)

    def test_size_filter_substring_match(self):
        # "S/M" listings should be returned when size="M"
        results = search_listings("mesh top", size="M")
        # lst_017 is size "S/M" — it should be included
        ids = [r["id"] for r in results]
        assert "lst_017" in ids, "S/M listing should match a search for size M"

    # ── No-match / empty-result cases ─────────────────────────────────────────

    def test_no_match_returns_empty_list(self):
        results = search_listings("designer ballgown", size="XXS", max_price=5.0)
        assert results == [], "impossible query should return [], not raise"

    def test_unrecognized_keywords_returns_empty_list(self):
        results = search_listings("xyzzy quux frobnicator")
        assert results == []

    def test_returns_empty_list_not_exception_on_no_match(self):
        # Should never raise — even for a ridiculous query
        try:
            results = search_listings("zzz", size="ZZZ", max_price=0.01)
            assert isinstance(results, list)
        except Exception as exc:
            pytest.fail(f"search_listings raised an exception: {exc}")

    # ── Combined filters ───────────────────────────────────────────────────────

    def test_price_and_size_both_applied(self):
        results = search_listings("vintage tee", size="L", max_price=25.0)
        for item in results:
            assert item["price"] <= 25.0
            assert "l" in item["size"].lower()

    def test_no_filters_returns_more_than_filtered(self):
        all_results = search_listings("vintage")
        filtered = search_listings("vintage", max_price=20.0)
        assert len(all_results) >= len(filtered)


# ═══════════════════════════════════════════════════════════════════════════════
# Tool 2: suggest_outfit
# ═══════════════════════════════════════════════════════════════════════════════

class TestSuggestOutfit:

    # ── Guard: empty wardrobe must not crash and must return something ─────────

    @_requires_api
    @pytest.mark.llm
    def test_empty_wardrobe_returns_nonempty_string(self):
        item = _get_listing("lst_003")  # Oversized Flannel
        result = suggest_outfit(item, get_empty_wardrobe())
        assert isinstance(result, str)
        assert result.strip() != "", "empty wardrobe path must return non-empty string"

    @_requires_api
    @pytest.mark.llm
    def test_empty_wardrobe_does_not_name_specific_wardrobe_pieces(self):
        """When wardrobe is empty, the LLM should not reference named items from
        the example wardrobe — it has no wardrobe to draw from."""
        item = _get_listing("lst_003")
        result = suggest_outfit(item, get_empty_wardrobe())
        example_piece_names = [
            "Baggy straight-leg jeans",
            "White ribbed tank top",
            "Black crossbody bag",
            "Vintage black denim jacket",
        ]
        for name in example_piece_names:
            assert name not in result, (
                f"empty-wardrobe path should not mention '{name}'"
            )

    # ── Happy path: populated wardrobe ────────────────────────────────────────

    @_requires_api
    @pytest.mark.llm
    def test_populated_wardrobe_returns_nonempty_string(self):
        item = _get_listing("lst_006")  # Graphic Tee
        result = suggest_outfit(item, get_example_wardrobe())
        assert isinstance(result, str)
        assert result.strip() != ""

    @_requires_api
    @pytest.mark.llm
    def test_populated_wardrobe_references_wardrobe_items(self):
        """The LLM should name at least one wardrobe piece from the example
        wardrobe when it has items to work with."""
        item = _get_listing("lst_006")
        result = suggest_outfit(item, get_example_wardrobe())
        wardrobe_item_names = [w["name"] for w in get_example_wardrobe()["items"]]
        mentioned = any(name in result for name in wardrobe_item_names)
        assert mentioned, "expected at least one wardrobe piece to be named in suggestion"


# ═══════════════════════════════════════════════════════════════════════════════
# Tool 3: create_fit_card
# ═══════════════════════════════════════════════════════════════════════════════

class TestCreateFitCard:

    # ── Guard: empty outfit must not crash ────────────────────────────────────

    def test_empty_outfit_returns_error_string(self):
        item = _get_listing("lst_006")
        result = create_fit_card("", item)
        assert isinstance(result, str)
        assert result.strip() != "", "empty outfit guard must return a non-empty error string"

    def test_whitespace_only_outfit_returns_error_string(self):
        item = _get_listing("lst_006")
        result = create_fit_card("   \t\n  ", item)
        assert isinstance(result, str)
        assert result.strip() != ""

    def test_empty_outfit_does_not_raise(self):
        item = _get_listing("lst_006")
        try:
            result = create_fit_card("", item)
            assert isinstance(result, str)
        except Exception as exc:
            pytest.fail(f"create_fit_card raised an exception on empty outfit: {exc}")

    # ── Happy path ────────────────────────────────────────────────────────────

    @_requires_api
    @pytest.mark.llm
    def test_returns_nonempty_string_for_valid_input(self):
        item = _get_listing("lst_006")
        outfit = "Pair with baggy jeans, chunky sneakers, 90s vibe."
        result = create_fit_card(outfit, item)
        assert isinstance(result, str)
        assert result.strip() != ""

    @_requires_api
    @pytest.mark.llm
    def test_caption_mentions_price(self):
        item = _get_listing("lst_006")  # price = $24
        outfit = "Pair with baggy jeans and chunky sneakers."
        result = create_fit_card(outfit, item)
        assert "24" in result, "fit card should mention the item price ($24)"

    @_requires_api
    @pytest.mark.llm
    def test_caption_mentions_platform(self):
        item = _get_listing("lst_006")  # platform = depop
        outfit = "Pair with baggy jeans and chunky sneakers."
        result = create_fit_card(outfit, item)
        assert "depop" in result.lower(), "fit card should mention the platform"

    @_requires_api
    @pytest.mark.llm
    def test_different_outfits_produce_different_captions(self):
        """temperature=1.0 should produce variation. Two different outfit strings
        should almost never produce the exact same caption."""
        item = _get_listing("lst_006")
        outfit_a = "Pair with baggy straight-leg jeans and chunky white sneakers for a 90s vibe."
        outfit_b = "Layer under oversized grey crewneck with wide-leg khakis and combat boots."
        result_a = create_fit_card(outfit_a, item)
        result_b = create_fit_card(outfit_b, item)
        assert result_a != result_b, "different outfit inputs should produce different captions"
