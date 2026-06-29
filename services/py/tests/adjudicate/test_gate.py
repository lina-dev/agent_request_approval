from reimb.adjudicate.gate import decide

RULES = {"A_auto": 2000.0, "tau_d": 0.85, "tau_low": 0.55, "require_receipt_proof": True}


def _state(amount=100.0, conf=0.95, flags=None):
    return {"claim": {"amount": amount}, "rules": RULES, "confidence": conf,
            "flags": flags or []}


def _p(verdict, citations=("M-01",), conf=0.95):
    return {"verdict": verdict, "confidence": conf, "rationale": "r",
            "policy_citations": list(citations)}


def test_clean_low_amount_auto_approves():
    assert decide(_p("APPROVE"), _state())["decision"] == "APPROVE"


def test_over_budget_escalates_even_if_llm_approves():
    assert decide(_p("APPROVE"), _state(amount=5000.0))["decision"] == "ESCALATE"


def test_missing_receipt_never_approves():
    assert decide(_p("APPROVE"), _state(flags=["missing_receipt"]))["decision"] == "ESCALATE"


def test_low_confidence_escalates():
    assert decide(_p("APPROVE", conf=0.6), _state(conf=0.6))["decision"] == "ESCALATE"


def test_ungrounded_deny_downgraded_to_escalate():
    assert decide(_p("DENY", citations=()), _state())["decision"] == "ESCALATE"


def test_grounded_hard_breach_denies():
    out = decide(_p("DENY", citations=("PROHIB-07",)), _state(flags=["prohibited_item"]))
    assert out["decision"] == "DENY"


def test_hard_breach_with_citation_is_binding_deny_even_if_llm_approves():
    out = decide(_p("APPROVE", citations=("PROHIB-07",)), _state(flags=["prohibited_item"]))
    assert out["decision"] == "DENY"


def test_validation_unavailable_escalates():
    assert decide(_p("APPROVE"), _state(flags=["validation_unavailable"]))["decision"] == "ESCALATE"


def test_invalid_verdict_defaults_to_escalate():
    out = decide({"verdict": "NONSENSE", "policy_citations": ["M-01"]}, _state())
    assert out["decision"] == "ESCALATE"


def test_result_is_traceable():
    out = decide(_p("APPROVE"), _state())
    assert out["policy_citations"] == ["M-01"]
    assert "flags" in out and "confidence" in out
