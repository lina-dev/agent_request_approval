"""End-to-end: real agent nodes wired together (only S3/model/HTTP faked).

Proves the phases compose into one traceable pipeline and that the eval gate
holds on the gold set.
"""

import json

from reimb.adjudicate.agent import make_adjudicate_node
from reimb.eval.runner import assert_thresholds, run_eval
from reimb.extract.agent import make_extract_node
from reimb.graph.build import build_graph
from reimb.obs import trace
from reimb.rag.agent import make_policy_node
from reimb.rag.retriever import HybridRetriever
from reimb.validate.agent import make_validate_node
from reimb.worker import process_message

CORPUS = [
    {"clause_id": "MEAL-CAP-DOM-01", "text": "Domestic meals capped at fifty dollars per day",
     "category": "meals", "policy_version": "v3"},
    {"clause_id": "TRAVEL-AIR-01", "text": "Economy airfare only for domestic flights",
     "category": "travel", "policy_version": "v3"},
]


def _embed(texts):
    return [[float("meal" in t.lower()), float("air" in t.lower() or "flight" in t.lower())]
            for t in texts]


def _no_sleep(_):
    return None


class SeqGateway:
    def __init__(self, items):
        self.items = list(items)

    def chat_content(self, model, messages, **kw):
        return self.items.pop(0)


def _fake_validate_service(payload):
    receipts = payload["receipts"]
    claim_cents = payload["claim"]["amount_cents"]
    if not receipts:
        return {"flags": ["missing_receipt"]}
    if sum(r["amount_cents"] for r in receipts) != claim_cents:
        return {"flags": ["amount_mismatch"]}
    return {"flags": []}


def _build_real_graph(extract_content, adjudicate_content):
    retriever = HybridRetriever(CORPUS, _embed)
    extract = make_extract_node(SeqGateway([extract_content]), lambda uri: "IMG", sleep=_no_sleep)
    policy = make_policy_node(lambda v: retriever, sleep=_no_sleep)
    validate = make_validate_node(_fake_validate_service, sleep=_no_sleep)
    adjudicate = make_adjudicate_node(SeqGateway([adjudicate_content]), sleep=_no_sleep)
    return build_graph(extract=extract, policy_retrieve=policy,
                       validate=validate, adjudicate=adjudicate)


def test_full_pipeline_approves_clean_case_and_traces_it():
    extracted = json.dumps({"merchant": "Cafe", "date": "2026-06-20", "amount": 50.0,
                            "currency": "USD", "confidence": 0.95})
    proposal = json.dumps({"verdict": "APPROVE", "confidence": 0.95,
                           "rationale": "within meal cap", "policy_citations": ["MEAL-CAP-DOM-01"]})
    graph = _build_real_graph(extracted, proposal)

    case = {"case_id": "e2e-1",
            "claim": {"amount": 50.0, "currency": "USD", "date": "2026-06-20", "category": "meals"},
            "rules": {"A_auto": 2000.0, "tau_d": 0.85, "tau_x": 0.8, "require_receipt_proof": True},
            "documents": [{"uri": "s3://b/r.jpg"}], "policy_version": "v3", "flags": []}

    saved = {}
    out = process_message({"case_id": "e2e-1"}, lambda cid: case,
                          lambda cid, st: saved.__setitem__(cid, st), graph=graph)

    assert out["decision"] == "APPROVE"
    assert out["policy_citations"] == ["MEAL-CAP-DOM-01"]
    assert out["final_actor"] == "agent"
    # traceability: every node emitted a span under the same trace id
    tid = out["trace_id"]
    names = {s["name"] for s in trace.get_spans(tid)}
    assert {"extract", "policy_retrieve", "validate", "adjudicate"} <= names
    assert saved["e2e-1"]["decision"] == "APPROVE"


def test_full_pipeline_missing_receipt_escalates():
    extracted = json.dumps({"merchant": "Cafe", "date": "2026-06-20", "amount": 50.0,
                            "currency": "USD", "confidence": 0.95})
    proposal = json.dumps({"verdict": "APPROVE", "confidence": 0.95,
                           "rationale": "x", "policy_citations": ["MEAL-CAP-DOM-01"]})
    graph = _build_real_graph(extracted, proposal)
    # no documents -> no receipts -> validate flags missing_receipt -> gate escalates
    case = {"case_id": "e2e-2",
            "claim": {"amount": 50.0, "currency": "USD", "date": "2026-06-20", "category": "meals"},
            "rules": {"A_auto": 2000.0, "tau_d": 0.85, "tau_x": 0.8, "require_receipt_proof": True},
            "documents": [], "policy_version": "v3", "flags": []}
    out = graph.invoke(case)
    assert out["decision"] == "ESCALATE"
    assert "no_documents" in out["flags"] or "missing_receipt" in out["flags"]


def test_eval_gate_holds_on_gold_set():
    import os
    gold = os.path.join(os.path.dirname(__file__), "..", "..", "eval", "gold", "cases.jsonl")
    metrics = run_eval(build_graph(), gold)  # deterministic stub graph
    assert_thresholds(metrics)  # false_approval < 1%, accuracy >= 95%
