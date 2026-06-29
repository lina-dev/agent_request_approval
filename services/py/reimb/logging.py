"""Structured JSON logging with automatic PII redaction.

Every log line is one JSON object carrying ``case_id``/``trace_id`` when
available, so logs are queryable and decisions are traceable end to end.
String fields are redacted before emit.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from .safety.pii import redact

_CONFIGURED = False


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        # structured extras attached via logger.info(msg, extra={"ctx": {...}})
        ctx = getattr(record, "ctx", None)
        if isinstance(ctx, dict):
            for k, v in ctx.items():
                payload[k] = redact(v) if isinstance(v, str) else v
        if record.exc_info:
            payload["error"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, sort_keys=True)


def configure(level: int = logging.INFO) -> None:
    """Install the JSON handler once (idempotent)."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger("reimb")
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    root.propagate = False
    _CONFIGURED = True


def get_logger(name: str, **ctx: Any) -> logging.LoggerAdapter:
    """Return a logger bound to a context dict (case_id, trace_id, ...)."""
    configure()
    base = logging.getLogger(f"reimb.{name}")
    return logging.LoggerAdapter(base, {"ctx": ctx})
