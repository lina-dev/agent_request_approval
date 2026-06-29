"""Apply a human reviewer's decision to an escalated case."""

from __future__ import annotations

from ..errors import ValidationInputError

_ALLOWED = {"APPROVE", "DENY"}


def apply_human_decision(state: dict, human: dict) -> dict:
    """Merge a reviewer verdict, marking the case ``final_actor="human"``.

    Raises ``ValidationInputError`` on a bad verdict so callers return 400.
    """
    verdict = (human or {}).get("verdict")
    if verdict not in _ALLOWED:
        raise ValidationInputError("human verdict must be APPROVE or DENY")
    return {
        **state,
        "decision": verdict,
        "rationale": human.get("rationale", state.get("rationale", "")),
        "final_actor": "human",
        "reviewer": human.get("reviewer"),
    }
