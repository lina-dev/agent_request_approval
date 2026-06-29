from reimb.errors import GatewayError
from reimb.rag.agent import make_policy_node


def _no_sleep(_):
    return None


class FakeRetriever:
    def __init__(self, clauses):
        self._clauses = clauses

    def search(self, q, k=5, category=None):
        return self._clauses


def _state():
    return {"case_id": "c1", "claim": {"category": "meals", "amount": 80, "currency": "USD"},
            "policy_version": "v3", "flags": []}


def test_policy_node_sets_citations():
    clauses = [{"clause_id": "MEAL-CAP-DOM-01", "text": "Domestic meals capped at $50/day"}]
    node = make_policy_node(lambda v: FakeRetriever(clauses), sleep=_no_sleep)
    out = node(_state())
    assert out["citations"] == ["MEAL-CAP-DOM-01"]
    assert out["retrieved_clauses"] == clauses


def test_empty_retrieval_flags():
    node = make_policy_node(lambda v: FakeRetriever([]), sleep=_no_sleep)
    out = node(_state())
    assert out["citations"] == []
    assert "policy_retrieval_empty" in out["flags"]


def test_retrieval_retry_then_success():
    attempts = {"n": 0}
    clauses = [{"clause_id": "OK-1", "text": "ok"}]

    def factory(version):
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise GatewayError("embed down")
        return FakeRetriever(clauses)

    node = make_policy_node(factory, sleep=_no_sleep)
    out = node(_state())
    assert out["citations"] == ["OK-1"]
    assert attempts["n"] == 2


def test_retrieval_exhausted_flags_failure():
    def factory(version):
        raise GatewayError("embed down")

    node = make_policy_node(factory, sleep=_no_sleep, max_attempts=2)
    out = node(_state())
    assert "policy_retrieval_failed" in out["flags"]
