import pytest

from reimb.errors import ValidationInputError
from reimb.review.resume import apply_human_decision


def test_human_override_sets_actor_and_decision():
    state = {"case_id": "c1", "decision": "ESCALATE", "flags": ["amount_mismatch"]}
    out = apply_human_decision(state, {"verdict": "DENY", "rationale": "mismatch", "reviewer": "u-9"})
    assert out["decision"] == "DENY"
    assert out["final_actor"] == "human"
    assert out["reviewer"] == "u-9"
    # original signals preserved for the audit trail
    assert out["flags"] == ["amount_mismatch"]


def test_bad_verdict_rejected():
    with pytest.raises(ValidationInputError):
        apply_human_decision({"case_id": "c1"}, {"verdict": "MAYBE"})
