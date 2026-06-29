import pytest

from reimb.errors import SecurityError, ValidationInputError
from reimb.safety.guard import validate_decide_request, validate_s3_uri


def test_valid_s3_uri():
    assert validate_s3_uri("s3://bucket/path/r1.jpg") == ("bucket", "path/r1.jpg")


@pytest.mark.parametrize("uri", [
    "http://evil/x", "s3:///nobucket", "s3://b/", "", "s3://b/../etc/passwd",
])
def test_bad_s3_uri_rejected(uri):
    with pytest.raises(SecurityError):
        validate_s3_uri(uri)


def _req(**over):
    base = {
        "case_id": "c1", "policy_version": "v3",
        "documents": [{"uri": "s3://b/r.jpg"}],
        "claim": {"amount": 10.0, "currency": "USD"},
        "rules": {"tau_d": 0.85},
    }
    base.update(over)
    return base


def test_valid_request_passes():
    validate_decide_request(_req())


def test_missing_case_id_rejected():
    with pytest.raises(ValidationInputError):
        validate_decide_request(_req(case_id=""))


def test_negative_amount_rejected():
    with pytest.raises(ValidationInputError):
        validate_decide_request(_req(claim={"amount": -1, "currency": "USD"}))


def test_oversize_amount_is_security_error():
    with pytest.raises(SecurityError):
        validate_decide_request(_req(claim={"amount": 9_999_999, "currency": "USD"}))


def test_too_many_documents_rejected():
    with pytest.raises(SecurityError):
        validate_decide_request(_req(documents=[{"uri": "s3://b/r.jpg"}] * 51))


def test_bad_currency_rejected():
    with pytest.raises(ValidationInputError):
        validate_decide_request(_req(claim={"amount": 5, "currency": "dollars"}))


def test_out_of_range_threshold_rejected():
    with pytest.raises(ValidationInputError):
        validate_decide_request(_req(rules={"tau_d": 1.5}))
