from reimb.graph.build import build_graph


def _state(amount, flags=None):
    return {"case_id": "c1", "claim": {"amount": amount, "currency": "USD", "date": "2026-06-20"},
            "rules": {"A_auto": 2000.0, "tau_d": 0.85, "require_receipt_proof": True},
            "documents": [], "flags": flags or []}


def test_graph_runs_clean_case_to_approve():
    g = build_graph()
    out = g.invoke(_state(50.0))
    assert out["decision"] == "APPROVE"
    assert out["final_actor"] == "agent"


def test_graph_over_budget_escalates():
    g = build_graph()
    out = g.invoke(_state(5000.0))
    assert out["decision"] == "ESCALATE"


def test_graph_hard_breach_denies():
    g = build_graph()
    out = g.invoke(_state(80.0, flags=["prohibited_item"]))
    assert out["decision"] == "DENY"


def test_parallel_branches_merge_flags_without_error():
    # the fork (policy_retrieve + validate) both touch flags via the reducer
    g = build_graph()
    out = g.invoke(_state(120.0))
    assert out["decision"] == "APPROVE"
    assert isinstance(out["flags"], list)
