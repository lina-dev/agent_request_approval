"""Typed error hierarchy.

The split that matters for the agent loops: ``RetryableError`` (and its
subclasses) are transient and SHOULD be retried by ``reimb.retry.retry_loop``;
everything else is terminal and must be turned into a decision flag, never a
crash.
"""

from __future__ import annotations


class ReimbError(Exception):
    """Base class for all platform errors."""


# --- Transient / retryable -------------------------------------------------
class RetryableError(ReimbError):
    """Transient failure; the calling loop should retry with backoff."""


class DocumentRetrievalError(RetryableError):
    """Could not fetch a document (S3 hiccup, network, throttling)."""


class GatewayError(RetryableError):
    """Model gateway returned a transient error (timeout, 5xx, rate limit)."""


# --- Terminal --------------------------------------------------------------
class ExtractionError(ReimbError):
    """Extraction produced unusable output after exhausting repairs."""


class ValidationInputError(ReimbError):
    """The inbound request/state failed structural validation."""


class SecurityError(ReimbError):
    """A request tripped a security guard (bad URI, oversize, injection)."""


class AdjudicationError(ReimbError):
    """Adjudication could not produce a parseable proposal."""
