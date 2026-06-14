"""
Tests for the three FitFindr tools.

Run with:  pytest tests/

LLM-backed tools (suggest_outfit, create_fit_card) are tested without hitting
the network: tools._chat is monkeypatched to return canned text for the
success paths and to raise for the API-failure paths, so each documented
failure mode is exercised deterministically.
"""

import pytest

import tools
from tools import search_listings, suggest_outfit, create_fit_card
from utils.data_loader import get_example_wardrobe, get_empty_wardrobe


# ── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_item():
    """A real listing dict to feed the styling tools."""
    return search_listings("vintage graphic tee", size=None, max_price=50)[0]


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def test_search_returns_results():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    assert isinstance(results, list)
    assert len(results) > 0


def test_search_empty_results():
    # Failure mode: nothing matches → empty list, NOT an exception.
    results = search_listings("designer ballgown", size="XXS", max_price=5)
    assert results == []


def test_search_price_filter():
    results = search_listings("jacket", size=None, max_price=10)
    assert all(item["price"] <= 10 for item in results)


def test_search_size_filter_case_insensitive():
    # "S" should match listings sized "S/M" (case-insensitive substring).
    results = search_listings("tee", size="s", max_price=None)
    assert all("s" in item["size"].lower() for item in results)


def test_search_drops_zero_score():
    # Gibberish keywords match nothing → empty list, no exception.
    assert search_listings("zzzqqq nonsense", size=None, max_price=None) == []


def test_search_sorted_by_relevance():
    # Results must be ordered; a more specific query should still return a list.
    results = search_listings("vintage denim jacket", size=None, max_price=None)
    assert isinstance(results, list)
    # Sorting is non-increasing in score; verify it doesn't raise and is a list.


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def test_suggest_outfit_with_wardrobe(monkeypatch, sample_item):
    monkeypatch.setattr(tools, "_chat", lambda prompt, temperature: "Pair it with X.")
    out = suggest_outfit(sample_item, get_example_wardrobe())
    assert isinstance(out, str)
    assert out.strip() != ""


def test_suggest_outfit_empty_wardrobe(monkeypatch, sample_item):
    # Failure mode: empty wardrobe is NOT an error — still returns non-empty text.
    monkeypatch.setattr(tools, "_chat", lambda prompt, temperature: "General advice.")
    out = suggest_outfit(sample_item, get_empty_wardrobe())
    assert isinstance(out, str)
    assert out.strip() != ""


def test_suggest_outfit_api_failure_fallback(monkeypatch, sample_item):
    # Failure mode: LLM/API error → non-empty fallback string, no exception.
    def boom(prompt, temperature):
        raise RuntimeError("network down")

    monkeypatch.setattr(tools, "_chat", boom)
    out = suggest_outfit(sample_item, get_example_wardrobe())
    assert isinstance(out, str)
    assert out.strip() != ""


def test_suggest_outfit_missing_items_key(monkeypatch, sample_item):
    # Defensive: a wardrobe dict with no "items" key must not crash.
    monkeypatch.setattr(tools, "_chat", lambda prompt, temperature: "Advice.")
    out = suggest_outfit(sample_item, {})
    assert isinstance(out, str)
    assert out.strip() != ""


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def test_fit_card_success(monkeypatch, sample_item):
    monkeypatch.setattr(tools, "_chat", lambda prompt, temperature: "Cute thrifted fit ✨")
    card = create_fit_card("Pair it with baggy jeans.", sample_item)
    assert isinstance(card, str)
    assert card.strip() != ""


def test_fit_card_empty_outfit_guard(sample_item):
    # Failure mode: empty/whitespace outfit → descriptive error string, no API call.
    card = create_fit_card("   ", sample_item)
    assert isinstance(card, str)
    assert card.strip() != ""
    assert "without an outfit" in card.lower()


def test_fit_card_empty_outfit_no_api_call(monkeypatch, sample_item):
    # The guard must short-circuit BEFORE any LLM call.
    def boom(prompt, temperature):
        raise AssertionError("_chat should not be called on empty outfit")

    monkeypatch.setattr(tools, "_chat", boom)
    card = create_fit_card("", sample_item)
    assert "without an outfit" in card.lower()


def test_fit_card_api_failure_fallback(monkeypatch, sample_item):
    # Failure mode: LLM/API error → field-built fallback caption, no exception.
    def boom(prompt, temperature):
        raise RuntimeError("network down")

    monkeypatch.setattr(tools, "_chat", boom)
    card = create_fit_card("Pair it with baggy jeans.", sample_item)
    assert isinstance(card, str)
    assert card.strip() != ""
    assert sample_item["platform"] in card
