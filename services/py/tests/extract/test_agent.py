"""Extraction loop cases: retrieval retry, repair loop, gateway retry, security."""

import json

from reimb.errors import DocumentRetrievalError, GatewayError, SecurityError
from reimb.extract.agent import make_extract_node
from reimb.extract.s3_image import make_s3_fetcher

GOOD = json.dumps({"merchant": "X", "date": "2026-06-20", "amount": 12.5,
                   "currency": "USD", "confidence": 0.9})
LOWCONF = json.dumps({"merchant": "X", "date": "2026-06-20", "amount": 12.5,
                      "currency": "USD", "confidence": 0.2})


def _no_sleep(_):
    return None


class SeqGateway:
    """Yields queued contents; an Exception item is raised when reached."""

    def __init__(self, items):
        self.items = list(items)
        self.calls = 0

    def chat_content(self, model, messages, **kw):
        self.calls += 1
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _state(uris=("s3://b/r.jpg",), tau_x=0.8):
    return {"case_id": "c1", "documents": [{"uri": u} for u in uris],
            "rules": {"tau_x": tau_x}, "flags": []}


def test_extract_success_single_doc():
    node = make_extract_node(SeqGateway([GOOD]), lambda uri: "IMG", sleep=_no_sleep)
    out = node(_state())
    assert out["extracted"]["amount"] == 12.5
    assert out["confidence"] == 0.9
    assert out["receipts"][0]["amount"] == 12.5


def test_repair_loop_then_success():
    # invalid, invalid, valid -> succeeds within 2 repairs
    gw = SeqGateway(["not json", "{}", GOOD])
    node = make_extract_node(gw, lambda uri: "IMG", sleep=_no_sleep)
    out = node(_state())
    assert out["extracted"]["amount"] == 12.5
    assert gw.calls == 3


def test_repair_exhausted_flags_low_confidence():
    gw = SeqGateway([LOWCONF, LOWCONF, LOWCONF])
    node = make_extract_node(gw, lambda uri: "IMG", sleep=_no_sleep)
    out = node(_state())
    assert "extraction_low_confidence" in out["flags"]
    assert "extracted" not in out


def test_gateway_retry_then_success():
    gw = SeqGateway([GatewayError("503"), GOOD])
    node = make_extract_node(gw, lambda uri: "IMG", sleep=_no_sleep)
    out = node(_state())
    assert out["extracted"]["amount"] == 12.5
    assert gw.calls == 2


def test_retrieval_retry_then_success():
    attempts = {"n": 0}

    def flaky_fetch(uri):
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise DocumentRetrievalError("s3 down")
        return "IMG"

    node = make_extract_node(SeqGateway([GOOD]), flaky_fetch, sleep=_no_sleep)
    out = node(_state())
    assert out["extracted"]["amount"] == 12.5
    assert attempts["n"] == 2


def test_retrieval_exhausted_flags_failure():
    def always_down(uri):
        raise DocumentRetrievalError("s3 down")

    node = make_extract_node(SeqGateway([]), always_down, sleep=_no_sleep,
                             max_fetch_attempts=2)
    out = node(_state())
    assert "document_retrieval_failed" in out["flags"]
    assert out["receipts"] == []


def test_security_error_flags_invalid_uri():
    def reject(uri):
        raise SecurityError("bad uri")

    node = make_extract_node(SeqGateway([]), reject, sleep=_no_sleep)
    out = node(_state())
    assert "invalid_document_uri" in out["flags"]


def test_no_documents_flag():
    node = make_extract_node(SeqGateway([]), lambda uri: "IMG", sleep=_no_sleep)
    out = node({"case_id": "c1", "documents": [], "rules": {}, "flags": []})
    assert "no_documents" in out["flags"]


def test_s3_fetcher_rejects_bad_uri_via_guard():
    fetch = make_s3_fetcher(lambda b, k: b"bytes")
    try:
        fetch("http://evil/x")
        assert False, "expected SecurityError"
    except SecurityError:
        pass


def test_s3_fetcher_maps_infra_error_to_retrieval_error():
    def boom(b, k):
        raise RuntimeError("throttled")

    fetch = make_s3_fetcher(boom)
    try:
        fetch("s3://b/r.jpg")
        assert False, "expected DocumentRetrievalError"
    except DocumentRetrievalError:
        pass
