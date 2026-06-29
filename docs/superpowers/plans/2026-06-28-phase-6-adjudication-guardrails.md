# Phase 6: Adjudication + Guardrails Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `adjudicate` stub with the real decision engine: an LLM produces a reasoned, cited verdict, then a deterministic threshold-policy + guardrail layer makes the binding APPROVE / DENY / ESCALATE decision.

**Architecture:** The adjudicator LLM (via gateway) consumes extracted fields + retrieved clauses + validation flags and returns a structured proposal `{verdict, confidence, rationale, policy_citations}`. A pure-Python **policy gate** then enforces the spec's hard rules — the LLM proposal is advisory; the gate is binding. Two guardrails: (1) auto-approve requires receipt proof + amount ≤ A_auto + confidence ≥ tau_d + no fraud flag; (2) any DENY must carry a cited clause or it is downgraded to ESCALATE.

**Tech Stack:** Python (Pydantic, the Phase-1 gateway). Pure functions for the gate — fully unit-testable without an LLM.

## Global Constraints

- The **policy gate is binding**, the LLM is advisory. The LLM can never auto-approve over `A_auto`.
- Ungrounded DENY (no citation) is forced to ESCALATE.
- Missing receipt / low-confidence extraction / fraud flag ⇒ never APPROVE.
- Thresholds (`A_auto`, `tau_d`, `tau_low`) read from `rules`.

---

## File structure

```
/services/py/reimb/adjudicate/proposal.py   # LLM proposal schema + call
/services/py/reimb/adjudicate/gate.py        # binding threshold-policy gate
/services/py/reimb/adjudicate/agent.py       # adjudicate node = propose + gate
/services/py/tests/adjudicate/test_gate.py
/services/py/tests/adjudicate/test_agent.py
```

---

### Task 1: Binding policy gate (pure, the safety core)

**Files:**
- Create: `services/py/reimb/adjudicate/gate.py`
- Test: `services/py/tests/adjudicate/test_gate.py`

**Interfaces:**
- Produces: `decide(proposal: dict, state: dict) -> dict` returning
  `{decision, confidence, rationale, policy_citations}` with `decision ∈ {APPROVE,DENY,ESCALATE}`.

- [ ] **Step 1: Write the failing tests (the decision matrix)**

```python
# services/py/tests/adjudicate/test_gate.py
from reimb.adjudicate.gate import decide

BASE_RULES = {"A_auto": 2000.0, "tau_d": 0.85, "tau_low": 0.55, "require_receipt_proof": True}

def state(amount=100.0, conf=0.95, flags=None):
    return {"claim": {"amount": amount}, "rules": BASE_RULES,
            "confidence": conf, "flags": flags or []}

def test_clean_low_amount_auto_approves():
    p = {"verdict": "APPROVE", "confidence": 0.95, "rationale": "ok", "policy_citations": ["M-01"]}
    assert decide(p, state())["decision"] == "APPROVE"

def test_over_budget_escalates_even_if_llm_approves():
    p = {"verdict": "APPROVE", "confidence": 0.99, "rationale": "ok", "policy_citations": ["M-01"]}
    assert decide(p, state(amount=5000.0))["decision"] == "ESCALATE"

def test_missing_receipt_never_approves():
    p = {"verdict": "APPROVE", "confidence": 0.99, "rationale": "ok", "policy_citations": ["M-01"]}
    assert decide(p, state(flags=["missing_receipt"]))["decision"] == "ESCALATE"

def test_ungrounded_deny_downgraded_to_escalate():
    p = {"verdict": "DENY", "confidence": 0.9, "rationale": "no", "policy_citations": []}
    assert decide(p, state())["decision"] == "ESCALATE"

def test_grounded_hard_breach_denies():
    p = {"verdict": "DENY", "confidence": 0.9, "rationale": "prohibited", "policy_citations": ["PROHIB-07"]}
    assert decide(p, state(flags=["prohibited_item"]))["decision"] == "DENY"

def test_low_confidence_escalates():
    p = {"verdict": "APPROVE", "confidence": 0.6, "rationale": "maybe", "policy_citations": ["M-01"]}
    assert decide(p, state(conf=0.6))["decision"] == "ESCALATE"
```

- [ ] **Step 2: Run (expect fail)**

Run: `cd services/py && python -m pytest tests/adjudicate/test_gate.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement the gate**

```python
# services/py/reimb/adjudicate/gate.py
HARD_BREACH = {"prohibited_item", "duplicate", "tampered", "math_fail"}
NON_APPROVE = {"missing_receipt", "extraction_low_confidence", "amount_mismatch"} | HARD_BREACH

def decide(proposal: dict, state: dict) -> dict:
    rules = state["rules"]
    amount = state["claim"]["amount"]
    conf = state.get("confidence", 0.0)
    flags = set(state.get("flags", []))
    citations = proposal.get("policy_citations", [])
    out = {"confidence": conf, "rationale": proposal.get("rationale", ""),
           "policy_citations": citations}

    # Guardrail 1: hard policy breach with a citation -> binding DENY
    if flags & HARD_BREACH and citations:
        return {**out, "decision": "DENY"}

    # Guardrail 2: any DENY must be grounded, else escalate
    if proposal.get("verdict") == "DENY":
        return {**out, "decision": "DENY" if citations else "ESCALATE"}

    # Auto-approve only if ALL hold
    can_auto = (
        amount <= rules["A_auto"]
        and conf >= rules["tau_d"]
        and not (flags & NON_APPROVE)
        and (not rules.get("require_receipt_proof") or "missing_receipt" not in flags)
    )
    if can_auto and proposal.get("verdict") == "APPROVE":
        return {**out, "decision": "APPROVE"}

    return {**out, "decision": "ESCALATE"}
```

- [ ] **Step 4: Run to verify pass**

Run: `cd services/py && python -m pytest tests/adjudicate/test_gate.py -q`
Expected: PASS (all 6).

- [ ] **Step 5: Commit**

```bash
git add services/py/reimb/adjudicate/gate.py services/py/tests/adjudicate/test_gate.py
git commit -m "feat(adjudicate): binding threshold-policy gate with guardrails"
```

---

### Task 2: LLM proposal + adjudicate node

**Files:**
- Create: `services/py/reimb/adjudicate/proposal.py`, `services/py/reimb/adjudicate/agent.py`
- Test: `services/py/tests/adjudicate/test_agent.py`

**Interfaces:**
- Consumes: `Gateway.chat` (Phase 1), `decide` (Task 1).
- Produces: `make_adjudicate_node(gateway)` returning node that sets `decision/confidence/rationale/policy_citations`.

- [ ] **Step 1: Write the failing test (gateway mocked)**

```python
# services/py/tests/adjudicate/test_agent.py
import json
from reimb.adjudicate.agent import make_adjudicate_node

class FakeGateway:
    def __init__(self, content): self.content = content
    def chat(self, model, messages, **kw):
        return {"choices": [{"message": {"content": self.content}}]}

def test_adjudicate_applies_gate():
    proposal = json.dumps({"verdict": "APPROVE", "confidence": 0.95,
                           "rationale": "within policy", "policy_citations": ["M-01"]})
    node = make_adjudicate_node(FakeGateway(proposal))
    out = node({"claim": {"amount": 100.0}, "extracted": {}, "retrieved_clauses": [],
                "rules": {"A_auto": 2000.0, "tau_d": 0.85, "tau_low": 0.55,
                          "require_receipt_proof": True},
                "confidence": 0.95, "flags": []})
    assert out["decision"] == "APPROVE"
```

- [ ] **Step 2: Run (expect fail), then implement**

```python
# services/py/reimb/adjudicate/proposal.py
import json

_SYS = ("You adjudicate reimbursement claims. Given extracted fields, retrieved policy "
        "clauses, and validation flags, return strict JSON: "
        "{verdict: APPROVE|DENY|ESCALATE, confidence: 0..1, rationale: str, "
        "policy_citations: [clause_id]}. Cite only provided clause ids. JSON only.")

def propose(gateway, state) -> dict:
    user = {"extracted": state.get("extracted"),
            "clauses": state.get("retrieved_clauses", []),
            "flags": state.get("flags", []),
            "claim": state["claim"]}
    msgs = [{"role": "system", "content": _SYS},
            {"role": "user", "content": json.dumps(user)}]
    content = gateway.chat("adjudicator", msgs)["choices"][0]["message"]["content"]
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {"verdict": "ESCALATE", "confidence": 0.0,
                "rationale": "unparseable adjudication", "policy_citations": []}
```

```python
# services/py/reimb/adjudicate/agent.py
from .proposal import propose
from .gate import decide

def make_adjudicate_node(gateway):
    def adjudicate(state) -> dict:
        proposal = propose(gateway, state)
        return decide(proposal, state)
    return adjudicate
```

- [ ] **Step 3: Run to pass, wire into graph, add conditional routing edges, commit**

Run: `python -m pytest tests/adjudicate -q` → PASS. In `build.py`, replace stub `adjudicate` with `make_adjudicate_node(gateway)`; the post-adjudicate edge routes on `state["decision"]` to terminal nodes (APPROVE/DENY/ESCALATE handled in P7).
```bash
git add services/py/reimb/adjudicate services/py/tests/adjudicate services/py/reimb/graph/build.py
git commit -m "feat(adjudicate): LLM proposal + binding gate node"
```

---

## Acceptance check

```bash
cd services/py && python -m pytest tests/adjudicate -q
```
Expected: gate decision-matrix (6 cases) + node integration pass. Over-budget LLM "approve" still escalates; ungrounded deny escalates.

## Self-review notes

- Covers spec §3 response, §5 threshold policy + both hard guardrails, §8 output guardrails (gate).
- The LLM-as-advisory / gate-as-binding split is the core safety property and is the most-tested unit.
