"""Lightweight tracing: per-node spans with a propagated trace id.

Each agent node is wrapped so we capture name, latency, status, and a
PII-redacted snapshot of its result. Spans are collected per trace, which makes
every decision reconstructable. In production the exporter is swapped for
Langfuse/OTel; here spans live in an in-memory collector that tests assert on.
"""

from __future__ import annotations

import functools
import time
import uuid
from contextvars import ContextVar
from typing import Any, Callable, Optional

from ..safety.pii import redact

# Current trace id for the case being processed (set by the worker).
_TRACE_ID: ContextVar[Optional[str]] = ContextVar("trace_id", default=None)

# In-memory span sink: {trace_id: [span, ...]}. Swapped for Langfuse in prod.
_SPANS: dict[str, list[dict]] = {}
# Flat list for simple assertions / latest-span access in tests.
_MEMORY_SPANS: list[dict] = []


def new_trace_id() -> str:
    return uuid.uuid4().hex


def set_trace_id(trace_id: str) -> None:
    _TRACE_ID.set(trace_id)


def current_trace_id() -> Optional[str]:
    return _TRACE_ID.get()


def get_spans(trace_id: str) -> list[dict]:
    return list(_SPANS.get(trace_id, []))


def reset() -> None:
    """Clear collected spans (test helper)."""
    _SPANS.clear()
    _MEMORY_SPANS.clear()


def _record(span: dict) -> None:
    tid = span.get("trace_id") or "no-trace"
    _SPANS.setdefault(tid, []).append(span)
    _MEMORY_SPANS.append(span)


def traced(name: str) -> Callable:
    """Decorate a graph node ``fn(state) -> dict`` to emit a span.

    The span records latency and a redacted view of the result. Exceptions are
    recorded as ``status="error"`` and re-raised so the caller's loop/handler
    decides what to do.
    """

    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        def wrap(state: dict, *args: Any, **kwargs: Any) -> Any:
            t0 = time.perf_counter()
            tid = current_trace_id()
            span: dict[str, Any] = {
                "trace_id": tid,
                "case_id": (state or {}).get("case_id"),
                "name": name,
                "status": "ok",
            }
            try:
                result = fn(state, *args, **kwargs)
                span["attributes"] = {"result": redact(str(result))[:2000]}
                return result
            except Exception as err:  # noqa: BLE001 - record then re-raise
                span["status"] = "error"
                span["attributes"] = {"error": redact(repr(err))}
                raise
            finally:
                span["latency_ms"] = round((time.perf_counter() - t0) * 1000, 3)
                _record(span)

        return wrap

    return deco
