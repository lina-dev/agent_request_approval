from reimb.extract.schema import parse_or_none


def test_valid_parses_and_uppercases_currency():
    rf = parse_or_none({
        "merchant": "Cafe X", "date": "2026-06-20", "amount": 12.5,
        "currency": "usd", "tax": 1.0,
        "line_items": [{"desc": "latte", "amount": 12.5}], "confidence": 0.91,
    })
    assert rf is not None
    assert rf.amount == 12.5
    assert rf.currency == "USD"


def test_missing_required_returns_none():
    assert parse_or_none({"merchant": "X"}) is None


def test_negative_amount_returns_none():
    assert parse_or_none({"merchant": "X", "date": "2026-06-20", "amount": -5,
                          "currency": "USD", "confidence": 0.9}) is None


def test_out_of_range_confidence_returns_none():
    assert parse_or_none({"merchant": "X", "date": "2026-06-20", "amount": 5,
                          "currency": "USD", "confidence": 1.4}) is None


def test_non_dict_returns_none():
    assert parse_or_none("nope") is None
    assert parse_or_none(None) is None
