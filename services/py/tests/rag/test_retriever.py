import pytest

from reimb.rag.retriever import HybridRetriever

CLAUSES = [
    {"clause_id": "MEAL-CAP-DOM-01", "text": "Domestic meals capped at fifty dollars per day",
     "category": "meals", "policy_version": "v3"},
    {"clause_id": "TRAVEL-AIR-01", "text": "Economy airfare only for domestic flights",
     "category": "travel", "policy_version": "v3"},
    {"clause_id": "HOTEL-01", "text": "Hotel lodging capped at two hundred per night",
     "category": "lodging", "policy_version": "v3"},
]


def fake_embed(texts):
    return [[float("meal" in t.lower()),
             float("air" in t.lower() or "flight" in t.lower()),
             float("hotel" in t.lower() or "lodging" in t.lower())] for t in texts]


def test_meal_query_returns_meal_clause_first():
    r = HybridRetriever(CLAUSES, fake_embed)
    top = r.search("what is the meal limit per day", k=1)
    assert top[0]["clause_id"] == "MEAL-CAP-DOM-01"


def test_category_filter_restricts_results():
    r = HybridRetriever(CLAUSES, fake_embed)
    top = r.search("limit", k=3, category="travel")
    assert all(c["category"] == "travel" for c in top)


def test_empty_query_returns_empty():
    r = HybridRetriever(CLAUSES, fake_embed)
    assert r.search("   ", k=3) == []


def test_requires_clauses():
    with pytest.raises(ValueError):
        HybridRetriever([], fake_embed)
