from reimb.eval.metrics import compute_metrics


def test_metrics_computation():
    results = [
        {"predicted": "APPROVE", "gold": "DENY"},     # false approval
        {"predicted": "APPROVE", "gold": "APPROVE"},
        {"predicted": "ESCALATE", "gold": "DENY"},
        {"predicted": "DENY", "gold": "DENY"},
    ]
    m = compute_metrics(results)
    assert m["false_approval_rate"] == 0.25
    assert m["decision_accuracy"] == 0.5
    assert m["auto_decision_rate"] == 0.75
    assert m["escalation_rate"] == 0.25


def test_empty_results():
    m = compute_metrics([])
    assert m["decision_accuracy"] == 0.0
    assert m["false_approval_rate"] == 0.0
