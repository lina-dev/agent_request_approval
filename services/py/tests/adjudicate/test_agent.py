import json

from reimb.adjudicate.agent import make_adjudicate_node
from reimb.obs.trace import new_trace_id, set_trace_id


def _no_sleep(_):
    return None


class SeqGateway:
    def __init__(self, items):
        self.items = list(items)

    def chat_content(self, model, messages, **kw):
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _state(amount=100.0, flags=None):
    return {"case_id": "c1", "claim": {"amount": amount},
            "rules": {"A_auto": 2000.0, "tau_d": 0.85, "require_receipt_proof": True},
            "confidence": 0.95, "flags": flags or [], "retrieved_clauses": []}


def test_applies_gate_and_is_traceable():
    set_trace_id(new_trace_id())
    proposal = json.dumps({"verdict": "APPROVE", "confidence": 0.95,
                           "rationale": "within policy", "policy_citations": ["M-01"]})
    node = make_adjudicate_node(SeqGateway([proposal]), sleep=_no_sleep)
    out = node(_state())
    assert out["decision"] == "APPROVE"
    assert out["final_actor"] == "agent"
    assert out["trace_id"]  # decision carries the trace id


def test_unparseable_proposal_degrades_to_escalate():
    node = make_adjudicate_node(SeqGateway(["not json"]), sleep=_no_sleep)
    out = node(_state())
    assert out["decision"] == "ESCALATE"


def test_gate_overrides_llm_over_budget():
    proposal = json.dumps({"verdict": "APPROVE", "confidence": 0.99,
                           "rationale": "ok", "policy_citations": ["M-01"]})
    node = make_adjudicate_node(SeqGateway([proposal]), sleep=_no_sleep)
    out = node(_state(amount=9999.0))
    assert out["decision"] == "ESCALATE"
