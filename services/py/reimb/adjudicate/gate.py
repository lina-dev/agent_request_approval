"""Binding threshold-policy gate.

The LLM proposal is ADVISORY; this pure function is BINDING. It can never be
talked into an auto-approval that violates the rules. Two hard guardrails:
  G1: a cited hard-policy breach is a binding DENY.
  G2: any DENY must carry a citation, else it is downgraded to ESCALATE.
Auto-approve requires ALL of: amount <= A_auto, confidence >= tau_d, receipt
proof present (when required), and no risk/breach flag.
"""

from __future__ import annotations

# Flags that, when present (and grounded), justify a binding denial.
HARD_BREACH = {"prohibited_item", "duplicate", "tampered", "math_fail"}

# Flags that make auto-approval impossible (force human review).
RISK = {
    "missing_receipt",
    "extraction_low_confidence",
    "amount_mismatch",
    "document_retrieval_failed",
    "invalid_document_uri",
    "no_documents",
    "validation_unavailable",
    "policy_retrieval_failed",
    "policy_retrieval_empty",
}
NON_APPROVE = HARD_BREACH | RISK

_VALID_VERDICTS = {"APPROVE", "DENY", "ESCALATE"}


def decide(proposal: dict, state: dict) -> dict:
    """Return the binding decision dict for *state* given the LLM *proposal*."""
    rules = state.get("rules", {})
    a_auto = float(rules.get("A_auto", 0.0))
    tau_d = float(rules.get("tau_d", 0.85))
    require_proof = bool(rules.get("require_receipt_proof", True))

    amount = float(state.get("claim", {}).get("amount", 0.0))
    conf = float(state.get("confidence", 0.0))
    flags = set(state.get("flags", []))
    citations = list(proposal.get("policy_citations", []) or [])
    verdict = proposal.get("verdict")
    if verdict not in _VALID_VERDICTS:
        verdict = "ESCALATE"

    out = {
        "confidence": conf,
        "rationale": proposal.get("rationale", ""),
        "policy_citations": citations,
        "flags": sorted(flags),
    }

    # G1: cited hard breach -> binding DENY.
    if (flags & HARD_BREACH) and citations:
        return {**out, "decision": "DENY"}

    # G2: any DENY must be grounded.
    if verdict == "DENY":
        return {**out, "decision": "DENY" if citations else "ESCALATE"}

    # Auto-approve gate: every condition must hold.
    can_auto = (
        amount <= a_auto
        and conf >= tau_d
        and not (flags & NON_APPROVE)
        and not (require_proof and "missing_receipt" in flags)
    )
    if can_auto and verdict == "APPROVE":
        return {**out, "decision": "APPROVE"}

    return {**out, "decision": "ESCALATE"}
