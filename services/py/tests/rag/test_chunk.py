from reimb.rag.chunk import chunk_corpus


def test_chunk_assigns_stable_ids():
    docs = [{"category": "meals", "policy_version": "v3",
             "clauses": [{"id": "MEAL-CAP-DOM-01", "text": "Domestic meals capped at $50/day."}]}]
    out = chunk_corpus(docs)
    assert out[0]["clause_id"] == "MEAL-CAP-DOM-01"
    assert out[0]["category"] == "meals"
    assert out[0]["policy_version"] == "v3"


def test_skips_malformed_clauses():
    docs = [{"category": "x", "policy_version": "v1",
             "clauses": [{"id": "", "text": "no id"}, {"id": "OK-1", "text": "good"}]}]
    out = chunk_corpus(docs)
    assert [c["clause_id"] for c in out] == ["OK-1"]


def test_empty_input():
    assert chunk_corpus([]) == []
    assert chunk_corpus(None) == []
