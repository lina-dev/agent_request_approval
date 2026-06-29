"""Assemble the decision graph.

Topology (fixed, versioned):
    START -> intake -> extract -> {policy_retrieve, validate} -> adjudicate -> END

Nodes are injectable. Defaults are deterministic stubs that still run the real
binding gate, so the graph is runnable (and the eval suite scorable) without a
live model; production injects the real agent nodes.
"""

from __future__ import annotations

from typing import Callable, Optional

from langgraph.graph import END, START, StateGraph

from ..adjudicate.gate import decide
from ..obs.trace import traced
from .state import CaseState


# --- default deterministic stubs ------------------------------------------
@traced("intake")
def _stub_intake(state: CaseState) -> dict:
    return {"flags": list(state.get("flags", []))}


@traced("extract")
def _stub_extract(state: CaseState) -> dict:
    claim = state.get("claim", {})
    receipt = {"merchant": "stub", "date": claim.get("date", ""),
               "amount": claim.get("amount", 0.0),
               "currency": claim.get("currency", "USD"), "confidence": 0.95}
    return {"extracted": receipt, "receipts": [receipt], "confidence": 0.95}


@traced("policy_retrieve")
def _stub_policy(state: CaseState) -> dict:
    return {"citations": ["STUB-01"], "retrieved_clauses": [
        {"clause_id": "STUB-01", "text": "stub policy clause"}]}


@traced("validate")
def _stub_validate(state: CaseState) -> dict:
    flags = list(state.get("flags", []))
    receipts = state.get("receipts", []) or []
    claim_amt = round(float(state.get("claim", {}).get("amount", 0.0)) * 100)
    if not receipts:
        flags.append("missing_receipt")
    elif sum(round(float(r.get("amount", 0.0)) * 100) for r in receipts) != claim_amt:
        flags.append("amount_mismatch")
    return {"flags": flags}


@traced("adjudicate")
def _stub_adjudicate(state: CaseState) -> dict:
    flags = set(state.get("flags", []))
    clean = not flags
    proposal = {
        "verdict": "APPROVE" if clean else "ESCALATE",
        "confidence": state.get("confidence", 0.0),
        "rationale": "stub adjudication",
        "policy_citations": state.get("citations", []),
    }
    result = decide(proposal, state)
    result["final_actor"] = "agent"
    return result


def build_graph(
    *,
    intake: Optional[Callable] = None,
    extract: Optional[Callable] = None,
    policy_retrieve: Optional[Callable] = None,
    validate: Optional[Callable] = None,
    adjudicate: Optional[Callable] = None,
    checkpointer=None,
):
    g = StateGraph(CaseState)
    g.add_node("intake", intake or _stub_intake)
    g.add_node("extract", extract or _stub_extract)
    g.add_node("policy_retrieve", policy_retrieve or _stub_policy)
    g.add_node("validate", validate or _stub_validate)
    g.add_node("adjudicate", adjudicate or _stub_adjudicate)

    g.add_edge(START, "intake")
    g.add_edge("intake", "extract")
    # fork
    g.add_edge("extract", "policy_retrieve")
    g.add_edge("extract", "validate")
    # join -> adjudicate runs once both branches complete
    g.add_edge("policy_retrieve", "adjudicate")
    g.add_edge("validate", "adjudicate")
    g.add_edge("adjudicate", END)

    return g.compile(checkpointer=checkpointer)
