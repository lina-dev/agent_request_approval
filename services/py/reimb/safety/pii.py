"""PII redaction applied before anything is logged or traced.

Deliberately conservative regexes with no external dependency so it can run in
the logging hot path. Production swaps in Presidio's analyzer behind the same
``redact`` signature for broader entity coverage.
"""

from __future__ import annotations

import re

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# 13-19 digits possibly separated by spaces/dashes (covers common card PANs)
_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_PHONE = re.compile(r"\b(?:\+?\d{1,2}[ -]?)?\(?\d{3}\)?[ -]?\d{3}[ -]?\d{4}\b")


def redact(text: str) -> str:
    """Mask common PII in *text*. Always returns a string."""
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    text = _EMAIL.sub("[REDACTED_EMAIL]", text)
    text = _SSN.sub("[REDACTED_SSN]", text)
    text = _CARD.sub("[REDACTED_CARD]", text)
    text = _PHONE.sub("[REDACTED_PHONE]", text)
    return text


def redact_mapping(data: dict) -> dict:
    """Return a shallow copy of *data* with string values redacted.

    Used to scrub structured log/trace attributes before emit.
    """
    out: dict = {}
    for k, v in (data or {}).items():
        if isinstance(v, str):
            out[k] = redact(v)
        elif isinstance(v, dict):
            out[k] = redact_mapping(v)
        else:
            out[k] = v
    return out
