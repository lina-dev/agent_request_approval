import pytest

from reimb.obs import trace
from reimb.obs.trace import get_spans, new_trace_id, set_trace_id, traced


def test_span_recorded_with_latency_and_redacted_result():
    @traced("extract")
    def node(state):
        return {"note": "email jo@acme.com"}

    node({"case_id": "c1"})
    span = trace._MEMORY_SPANS[-1]
    assert span["name"] == "extract"
    assert span["status"] == "ok"
    assert "latency_ms" in span
    assert "jo@acme.com" not in span["attributes"]["result"]


def test_error_span_recorded_and_reraised():
    @traced("boom")
    def node(state):
        raise ValueError("kaboom")

    with pytest.raises(ValueError):
        node({"case_id": "c2"})
    span = trace._MEMORY_SPANS[-1]
    assert span["status"] == "error"
    assert "kaboom" in span["attributes"]["error"]


def test_spans_grouped_by_trace_id():
    tid = new_trace_id()
    set_trace_id(tid)

    @traced("n1")
    def n1(state):
        return {}

    n1({"case_id": "c3"})
    assert any(s["name"] == "n1" for s in get_spans(tid))
