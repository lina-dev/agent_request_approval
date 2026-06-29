"""VALIDATE node: deterministic checks via the Go validation service.

Money is sent as integer cents to avoid float drift. If the service is
transiently unavailable we retry; if it stays down we fail SAFE by flagging
``validation_unavailable`` (which forces escalation) rather than approving
blind.
"""

from __future__ import annotations

from typing import Callable

from ..errors import GatewayError
from ..logging import get_logger
from ..obs.trace import traced
from ..retry import RetryExhausted, retry_loop


def _cents(amount: object) -> int:
    try:
        return int(round(float(amount) * 100))
    except (TypeError, ValueError):
        return 0


def make_validate_node(
    post: Callable[[dict], dict],
    *,
    max_attempts: int = 3,
    sleep: Callable[[float], None] | None = None,
):
    """``post(payload) -> {"flags": [...]}`` posts to the Go /validate endpoint."""
    sleep_fn = sleep if sleep is not None else __import__("time").sleep

    @traced("validate")
    def validate(state: dict) -> dict:
        log = get_logger("validate", case_id=state.get("case_id"))
        claim = state.get("claim", {})
        receipts = state.get("receipts", []) or []
        payload = {
            "claim": {
                "amount_cents": _cents(claim.get("amount")),
                "currency": claim.get("currency", "USD"),
                "date": claim.get("date", ""),
                "category": claim.get("category", ""),
            },
            "receipts": [
                {"amount_cents": _cents(r.get("amount")), "date": r.get("date", "")}
                for r in receipts
            ],
        }
        try:
            resp = retry_loop(lambda: post(payload), max_attempts=max_attempts,
                              retry_on=(GatewayError,), sleep=sleep_fn)
        except RetryExhausted as err:
            log.info("validation service unavailable",
                     extra={"ctx": {"last": repr(err.last)}})
            return {"flags": _merge(state, ["validation_unavailable"])}

        new_flags = resp.get("flags", []) if isinstance(resp, dict) else []
        return {"flags": _merge(state, new_flags)}

    return validate


def _merge(state: dict, new: list[str]) -> list[str]:
    flags = list(state.get("flags", []))
    for f in new:
        if f not in flags:
            flags.append(f)
    return flags
