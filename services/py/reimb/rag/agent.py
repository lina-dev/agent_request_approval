"""POLICY_RETRIEVE node: fetch cited policy clauses for a claim.

Loop case: building/querying the retriever can fail transiently (embedding
gateway hiccup). We retry, and if retrieval ultimately yields nothing we flag
``policy_retrieval_empty`` so adjudication cannot silently proceed ungrounded.
"""

from __future__ import annotations

from typing import Callable

from ..errors import GatewayError
from ..logging import get_logger
from ..obs.trace import traced
from ..retry import RetryExhausted, retry_loop


def make_policy_node(
    retriever_for: Callable[[str], object],
    *,
    k: int = 5,
    max_attempts: int = 3,
    sleep: Callable[[float], None] | None = None,
):
    """``retriever_for(policy_version) -> HybridRetriever-like`` with .search()."""
    sleep_fn = sleep if sleep is not None else __import__("time").sleep

    @traced("policy_retrieve")
    def policy_retrieve(state: dict) -> dict:
        log = get_logger("rag", case_id=state.get("case_id"))
        claim = state.get("claim", {})
        version = state.get("policy_version", "")
        category = claim.get("category", "")
        query = (
            f"{category} policy limit and rules for a {claim.get('currency', '')} "
            f"{claim.get('amount', '')} {category} expense"
        ).strip()

        def _do() -> list[dict]:
            retriever = retriever_for(version)
            return retriever.search(query, k=k, category=category or None)

        try:
            clauses = retry_loop(_do, max_attempts=max_attempts,
                                 retry_on=(GatewayError,), sleep=sleep_fn)
        except RetryExhausted as err:
            log.info("policy retrieval exhausted",
                     extra={"ctx": {"last": repr(err.last)}})
            return {"citations": [], "retrieved_clauses": [],
                    "flags": _add(state, "policy_retrieval_failed")}

        if not clauses:
            log.info("policy retrieval empty", extra={"ctx": {"version": version}})
            return {"citations": [], "retrieved_clauses": [],
                    "flags": _add(state, "policy_retrieval_empty")}

        return {
            "citations": [c["clause_id"] for c in clauses],
            "retrieved_clauses": clauses,
        }

    return policy_retrieve


def _add(state: dict, flag: str) -> list[str]:
    flags = list(state.get("flags", []))
    if flag not in flags:
        flags.append(flag)
    return flags
