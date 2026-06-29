import pytest

from reimb.worker import process_message


def _loader(cid):
    return {"case_id": cid, "claim": {"amount": 50.0, "currency": "USD", "date": "2026-06-20"},
            "rules": {"A_auto": 2000.0, "tau_d": 0.85, "require_receipt_proof": True},
            "documents": [], "flags": []}


def test_process_message_persists_traceable_decision():
    saved = {}
    out = process_message({"case_id": "c1"}, _loader, lambda cid, st: saved.__setitem__(cid, st))
    assert saved["c1"]["decision"] == "APPROVE"
    assert saved["c1"]["trace_id"]  # traceability id attached
    assert out["decision"] == "APPROVE"


def test_missing_case_id_raises():
    with pytest.raises(ValueError):
        process_message({}, _loader, lambda c, s: None)


def test_loader_failure_propagates_to_requeue():
    def bad_loader(cid):
        raise RuntimeError("db down")

    with pytest.raises(RuntimeError):
        process_message({"case_id": "c1"}, bad_loader, lambda c, s: None)
