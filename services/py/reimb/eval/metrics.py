"""Compute the spec's success metrics from predicted vs gold decisions."""

from __future__ import annotations

_KEYS = ("decision_accuracy", "false_approval_rate", "false_denial_rate",
         "auto_decision_rate", "escalation_rate")


def compute_metrics(results: list[dict]) -> dict:
    """Each result: ``{"predicted": str, "gold": str}``.

    - false_approval_rate: predicted APPROVE but gold DENY (the costly error).
    - false_denial_rate:   predicted DENY but gold APPROVE.
    - auto_decision_rate:  fraction NOT escalated (straight-through).
    """
    n = len(results)
    if n == 0:
        return {k: 0.0 for k in _KEYS}
    correct = sum(r["predicted"] == r["gold"] for r in results)
    false_appr = sum(r["predicted"] == "APPROVE" and r["gold"] == "DENY" for r in results)
    false_deny = sum(r["predicted"] == "DENY" and r["gold"] == "APPROVE" for r in results)
    escalated = sum(r["predicted"] == "ESCALATE" for r in results)
    return {
        "decision_accuracy": correct / n,
        "false_approval_rate": false_appr / n,
        "false_denial_rate": false_deny / n,
        "auto_decision_rate": (n - escalated) / n,
        "escalation_rate": escalated / n,
    }
