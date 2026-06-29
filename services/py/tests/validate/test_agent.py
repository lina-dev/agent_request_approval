from reimb.errors import GatewayError
from reimb.validate.agent import make_validate_node


def _no_sleep(_):
    return None


def _state(receipts):
    return {"case_id": "c1",
            "claim": {"amount": 50.0, "currency": "USD", "date": "2026-06-20"},
            "receipts": receipts, "flags": []}


def test_merges_flags_from_service():
    captured = {}

    def post(payload):
        captured.update(payload)
        return {"flags": ["missing_receipt"]}

    node = make_validate_node(post, sleep=_no_sleep)
    out = node(_state([]))
    assert "missing_receipt" in out["flags"]
    # money sent as integer cents
    assert captured["claim"]["amount_cents"] == 5000


def test_clean_case_no_new_flags():
    node = make_validate_node(lambda p: {"flags": []}, sleep=_no_sleep)
    out = node(_state([{"amount": 50.0, "date": "2026-06-20"}]))
    assert out["flags"] == []


def test_service_unavailable_fails_safe():
    def down(payload):
        raise GatewayError("connection refused")

    node = make_validate_node(down, sleep=_no_sleep, max_attempts=2)
    out = node(_state([{"amount": 50.0, "date": "2026-06-20"}]))
    assert "validation_unavailable" in out["flags"]
