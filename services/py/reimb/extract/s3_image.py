"""Fetch receipt image bytes from S3 and base64-encode them.

Network/throttling failures are surfaced as ``DocumentRetrievalError`` (a
``RetryableError``) so the extraction loop retries them. The URI is validated by
the security guard first.
"""

from __future__ import annotations

import base64
from typing import Callable

from ..errors import DocumentRetrievalError
from ..safety.guard import validate_s3_uri


def make_s3_fetcher(get_object: Callable[[str, str], bytes]) -> Callable[[str], str]:
    """Build a ``fetch(uri) -> base64 str`` using an injected ``get_object``.

    ``get_object(bucket, key) -> bytes`` is the only AWS-touching dependency, so
    the fetcher is fully testable with a fake.
    """

    def fetch(uri: str) -> str:
        bucket, key = validate_s3_uri(uri)  # SecurityError on bad URI (terminal)
        try:
            raw = get_object(bucket, key)
        except Exception as err:  # transient infra error -> retryable
            raise DocumentRetrievalError(f"S3 get failed for {uri}: {err!r}") from err
        if not raw:
            raise DocumentRetrievalError(f"S3 object empty for {uri}")
        return base64.b64encode(raw).decode()

    return fetch


def boto3_get_object(bucket: str, key: str) -> bytes:  # pragma: no cover - thin AWS glue
    import boto3

    obj = boto3.client("s3").get_object(Bucket=bucket, Key=key)
    return obj["Body"].read()
