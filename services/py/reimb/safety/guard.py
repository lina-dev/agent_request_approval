"""Input security guards: validate the request and S3 URIs before use.

These run at the platform boundary so malformed or hostile input never reaches
the agents, S3, or the model gateway.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from ..errors import SecurityError, ValidationInputError

# Reasonable upper bounds to stop abuse / runaway cost.
MAX_DOCUMENTS = 50
MAX_AMOUNT = 1_000_000.0          # a single expense line above this is nonsense
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_S3_KEY_RE = re.compile(r"^[A-Za-z0-9!_.*'()/\-]+$")  # conservative S3 key charset


def validate_s3_uri(uri: str) -> tuple[str, str]:
    """Validate and split an ``s3://bucket/key`` URI.

    Guards against path traversal and SSRF-style scheme abuse. Returns
    ``(bucket, key)`` or raises ``SecurityError``.
    """
    if not isinstance(uri, str) or not uri:
        raise SecurityError("empty document URI")
    parsed = urlparse(uri)
    if parsed.scheme != "s3":
        raise SecurityError(f"unsupported URI scheme: {parsed.scheme!r}")
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    if not bucket or not key:
        raise SecurityError("S3 URI must include bucket and key")
    if ".." in key or key.startswith("/"):
        raise SecurityError("S3 key path traversal rejected")
    if not _S3_KEY_RE.match(key):
        raise SecurityError("S3 key contains illegal characters")
    return bucket, key


def validate_decide_request(req: dict) -> None:
    """Structurally validate an inbound /decisions request.

    Raises ``ValidationInputError`` (client error) or ``SecurityError``.
    """
    if not isinstance(req, dict):
        raise ValidationInputError("request must be an object")
    if not req.get("case_id"):
        raise ValidationInputError("case_id is required")
    if not req.get("policy_version"):
        raise ValidationInputError("policy_version is required")

    documents = req.get("documents")
    if not isinstance(documents, list):
        raise ValidationInputError("documents must be a list")
    if len(documents) > MAX_DOCUMENTS:
        raise SecurityError(f"too many documents (> {MAX_DOCUMENTS})")
    for doc in documents:
        if not isinstance(doc, dict) or "uri" not in doc:
            raise ValidationInputError("each document needs a uri")
        validate_s3_uri(doc["uri"])  # security check per URI

    claim = req.get("claim")
    if not isinstance(claim, dict):
        raise ValidationInputError("claim must be an object")
    amount = claim.get("amount")
    if not isinstance(amount, (int, float)) or amount < 0:
        raise ValidationInputError("claim.amount must be a non-negative number")
    if amount > MAX_AMOUNT:
        raise SecurityError("claim.amount exceeds sane bound")
    currency = claim.get("currency", "USD")
    if not _CURRENCY_RE.match(str(currency)):
        raise ValidationInputError("claim.currency must be a 3-letter ISO code")

    rules = req.get("rules", {})
    if not isinstance(rules, dict):
        raise ValidationInputError("rules must be an object")
    for key in ("tau_d", "tau_x", "tau_low"):
        if key in rules and not 0.0 <= float(rules[key]) <= 1.0:
            raise ValidationInputError(f"rules.{key} must be in [0,1]")
    if "A_auto" in rules and float(rules["A_auto"]) < 0:
        raise ValidationInputError("rules.A_auto must be >= 0")
