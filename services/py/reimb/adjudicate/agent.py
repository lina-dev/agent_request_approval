"""ADJUDICATE node: LLM proposal -> binding gate -> traceable decision."""

from __future__ import annotations

from typing import Callable

from ..logging import get_logger
from ..obs.trace import current_trace_id, traced
from .gate import decide
from .proposal import propose


def make_adjudicate_node(gateway, *, sleep: Callable[[float], None] | None = None):
    @traced("adjudicate")
    def adjudicate(state: dict) -> dict:
        log = get_logger("adjudicate", case_id=state.get("case_id"))
        proposal = propose(gateway, state, sleep=sleep)
        result = decide(proposal, state)
        result["trace_id"] = current_trace_id()
        result["final_actor"] = "agent"
        log.info("adjudicated", extra={"ctx": {
            "decision": result["decision"],
            "confidence": result["confidence"],
            "citations": result["policy_citations"],
        }})
        return result

    return adjudicate
