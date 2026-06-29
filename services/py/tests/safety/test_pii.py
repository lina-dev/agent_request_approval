from reimb.safety.pii import redact, redact_mapping


def test_redacts_email_card_ssn_phone():
    out = redact("jo@acme.com 4111 1111 1111 1111 ssn 123-45-6789 tel 415-555-1212")
    assert "jo@acme.com" not in out
    assert "4111" not in out
    assert "123-45-6789" not in out
    assert "415-555-1212" not in out
    assert "[REDACTED_EMAIL]" in out


def test_redact_handles_non_string():
    assert redact(None) == ""
    assert redact(12345) == "12345"


def test_redact_mapping_nested():
    out = redact_mapping({"a": "mail jo@acme.com", "b": {"c": "x@y.io"}, "n": 3})
    assert "jo@acme.com" not in out["a"]
    assert "x@y.io" not in out["b"]["c"]
    assert out["n"] == 3
