"""Prompt-injection defense for untrusted document text.

Core principle (spec §8): extracted receipt text is DATA, never instructions.
We (1) detect overt override attempts so they can be flagged, and (2) fence the
text structurally so the model is told explicitly to treat it as data.
"""

from __future__ import annotations

import re

_PATTERNS = [
    r"ignore\s+(all\s+|the\s+|any\s+)?previous\s+instructions",
    r"disregard\s+(the\s+)?(system|above|prior)",
    r"\bapprove\s+this\b",
    r"\bauto[- ]?approve\b",
    r"you\s+are\s+now\b",
    r"new\s+instructions?\s*:",
    r"system\s+prompt",
    r"</?\s*(system|untrusted_document)\s*>",  # attempts to spoof our fences
]
_RE = re.compile("|".join(_PATTERNS), re.IGNORECASE)

_OPEN = "<UNTRUSTED_DOCUMENT>"
_CLOSE = "</UNTRUSTED_DOCUMENT>"


def is_suspicious(text: str) -> bool:
    """True if *text* contains an apparent instruction-override attempt."""
    if not text or not isinstance(text, str):
        return False
    return bool(_RE.search(text))


def fence_document_text(text: str) -> str:
    """Wrap untrusted text so the model treats it as data, not instructions.

    Any attempt to spoof the fence delimiters inside the text is neutralized
    first so the wrapper cannot be broken out of.
    """
    safe = (text or "").replace(_OPEN, "").replace(_CLOSE, "")
    return f"{_OPEN}\n{safe}\n{_CLOSE}"
