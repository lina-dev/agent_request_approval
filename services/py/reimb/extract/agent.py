"""Extraction agent: receipt image -> structured fields, with three loops.

Loop cases (the "agents run in a loop when they fail to retrieve data"):
  1. Document-retrieval loop  - S3 fetch fails transiently -> retry with backoff.
  2. Gateway loop             - model call times out / 5xx / 429 -> retry.
  3. Extraction-repair loop   - output is non-JSON, schema-invalid, or below the
                                confidence floor -> re-prompt with a corrective
                                hint, up to ``max_repairs`` times.
Exhausting a loop never crashes the graph: it appends a flag the adjudicator
reads (`document_retrieval_failed`, `extraction_low_confidence`) and escalates.
"""

from __future__ import annotations

import json
from typing import Callable

from ..errors import DocumentRetrievalError, GatewayError, SecurityError
from ..logging import get_logger
from ..obs.trace import traced
from ..retry import RetryExhausted, retry_loop
from .schema import ReceiptFields, parse_or_none

_PROMPT = (
    "Extract receipt fields as STRICT JSON with keys: merchant, date (yyyy-mm-dd), "
    "amount (number), currency (3-letter), tax (number), line_items "
    "(list of {desc, amount}), confidence (0..1). Output JSON only, no prose."
)
_REPAIR_HINT = (
    "Your previous output was not valid JSON, was missing required fields, or "
    "reported low confidence. Re-read the image and return STRICT JSON only."
)


def make_extract_node(
    gateway,
    fetch_image: Callable[[str], str],
    *,
    max_repairs: int = 2,
    max_fetch_attempts: int = 3,
    max_gateway_attempts: int = 3,
    sleep: Callable[[float], None] | None = None,
):
    """Build the EXTRACT node. ``sleep`` is injectable for fast tests."""
    sleep_fn = sleep if sleep is not None else __import__("time").sleep

    def _call_model(messages: list[dict]) -> str:
        # Gateway loop: retry transient GatewayError.
        return retry_loop(
            lambda: gateway.chat_content("extractor", messages),
            max_attempts=max_gateway_attempts,
            retry_on=(GatewayError,),
            sleep=sleep_fn,
        )

    def _fetch(uri: str) -> str:
        # Retrieval loop: retry transient DocumentRetrievalError.
        return retry_loop(
            lambda: fetch_image(uri),
            max_attempts=max_fetch_attempts,
            retry_on=(DocumentRetrievalError,),
            sleep=sleep_fn,
        )

    def _extract_one(uri: str, tau_x: float, log) -> ReceiptFields | None:
        img = _fetch(uri)  # may raise RetryExhausted / SecurityError
        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": _PROMPT},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{img}"}},
            ],
        }]
        # Repair loop: 1 initial try + max_repairs corrections.
        for attempt in range(max_repairs + 1):
            content = _call_model(messages)
            parsed = None
            try:
                parsed = parse_or_none(json.loads(content))
            except (json.JSONDecodeError, TypeError):
                parsed = None
            if parsed is not None and parsed.confidence >= tau_x:
                return parsed
            log.info("extraction repair", extra={"ctx": {"attempt": attempt}})
            messages.append({"role": "user", "content": _REPAIR_HINT})
        return None

    @traced("extract")
    def extract(state: dict) -> dict:
        log = get_logger("extract", case_id=state.get("case_id"))
        tau_x = float(state.get("rules", {}).get("tau_x", 0.80))
        documents = state.get("documents", []) or []
        flags = list(state.get("flags", []))

        if not documents:
            log.info("no documents to extract")
            return {"flags": flags + ["no_documents"], "receipts": []}

        receipts: list[dict] = []
        confidences: list[float] = []
        for doc in documents:
            uri = doc.get("uri", "")
            try:
                rf = _extract_one(uri, tau_x, log)
            except SecurityError as err:
                log.info("rejected document uri", extra={"ctx": {"err": str(err)}})
                flags.append("invalid_document_uri")
                continue
            except RetryExhausted as err:
                log.info("document retrieval exhausted",
                         extra={"ctx": {"uri": uri, "last": repr(err.last)}})
                flags.append("document_retrieval_failed")
                continue
            if rf is None:
                flags.append("extraction_low_confidence")
                continue
            receipts.append(rf.model_dump())
            confidences.append(rf.confidence)

        if not receipts:
            # Every document failed -> nothing to adjudicate on.
            return {"flags": _dedup(flags), "receipts": []}

        primary = receipts[0]
        return {
            "extracted": primary,
            "receipts": receipts,
            "confidence": min(confidences),
            "flags": _dedup(flags),
        }

    return extract


def _dedup(items: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for i in items:
        seen.setdefault(i, None)
    return list(seen.keys())
