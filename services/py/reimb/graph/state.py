"""Case state for the decision graph.

``flags`` uses a union reducer because the POLICY_RETRIEVE and VALIDATE branches
run in parallel and both append flags; the reducer merges their updates without
duplicates instead of raising a concurrent-write error.
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict


def union_flags(existing: list[str] | None, update: list[str] | None) -> list[str]:
    """Order-preserving de-duplicated union of two flag lists."""
    out: list[str] = []
    for item in (existing or []) + (update or []):
        if item not in out:
            out.append(item)
    return out


class CaseState(TypedDict, total=False):
    case_id: str
    claim: dict[str, Any]
    rules: dict[str, Any]
    documents: list[dict[str, Any]]
    policy_version: str
    # produced along the way
    extracted: dict[str, Any]
    receipts: list[dict[str, Any]]
    confidence: float
    citations: list[str]
    retrieved_clauses: list[dict[str, Any]]
    flags: Annotated[list[str], union_flags]
    # terminal decision
    decision: str
    rationale: str
    policy_citations: list[str]
    final_actor: str
    reviewer: str
    trace_id: str
