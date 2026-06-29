"""SQS-driven case runner.

Establishes a trace id per case so every span and the final decision share one
correlation id, runs the graph, and persists the result. IO (loading the case,
persisting) is injected so the core is testable without AWS/DB.
"""

from __future__ import annotations

from typing import Callable

from .graph.build import build_graph
from .graph.state import CaseState
from .logging import get_logger
from .obs.trace import current_trace_id, new_trace_id, set_trace_id

_DEFAULT_GRAPH = build_graph()


def process_message(
    body: dict,
    load_case: Callable[[str], CaseState],
    persist: Callable[[str, CaseState], None],
    *,
    graph=None,
) -> CaseState:
    """Process one queue message end to end. Returns the final state.

    Any exception is logged and re-raised so the message returns to the queue
    (and ultimately the DLQ) rather than being silently dropped.
    """
    graph = graph or _DEFAULT_GRAPH
    case_id = body.get("case_id")
    if not case_id:
        raise ValueError("message missing case_id")

    trace_id = new_trace_id()
    set_trace_id(trace_id)
    log = get_logger("worker", case_id=case_id, trace_id=trace_id)

    try:
        state = load_case(case_id)
    except Exception:
        log.exception("failed to load case")
        raise

    state.setdefault("trace_id", trace_id)
    try:
        result = graph.invoke(state)
    except Exception:
        log.exception("graph execution failed")
        raise

    result.setdefault("trace_id", current_trace_id() or trace_id)
    try:
        persist(case_id, result)
    except Exception:
        log.exception("failed to persist decision")
        raise

    log.info("case complete", extra={"ctx": {"decision": result.get("decision")}})
    return result
