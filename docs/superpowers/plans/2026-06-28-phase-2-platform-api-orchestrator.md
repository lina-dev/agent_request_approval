# Phase 2: Platform API + Orchestrator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose `POST /decisions` (Go), enqueue cases to SQS, and run a LangGraph state machine (Python) that walks a case through stub nodes to a decision — proving the end-to-end skeleton before real agents land.

**Architecture:** A Go HTTP service validates the request, writes documents' references + claim to a case record, and enqueues the `case_id` on SQS. A Python worker consumes SQS, loads case state, and runs the LangGraph graph (INTAKE → EXTRACT → fork[POLICY_RETRIEVE, VALIDATE] → ADJUDICATE → route). In this phase nodes are stubs returning fixed values; later phases replace each stub. LangGraph uses a Postgres checkpointer so HITL pauses survive restarts.

**Tech Stack:** Go (net/http, aws-sdk-go-v2), Python (LangGraph, psycopg, boto3), Postgres, SQS.

## Global Constraints

- Request/response schema is the spec §3 contract — do not deviate from field names.
- Rules (`A_auto`, `tau_*`, `require_receipt_proof`) come from the request, never hardcoded.
- The graph topology is fixed and versioned; nodes are swappable, edges are not.
- Case state persisted in Postgres (`cases` table) + LangGraph checkpointer.

---

## File structure

```
/services/go/internal/api/decisions.go      # POST /decisions handler
/services/go/internal/api/decisions_test.go
/services/go/internal/case/store.go          # cases table CRUD
/services/go/internal/queue/sqs.go           # enqueue
/services/py/reimb/graph/state.py            # CaseState TypedDict
/services/py/reimb/graph/build.py            # LangGraph graph (stub nodes)
/services/py/reimb/graph/nodes_stub.py       # stub node fns
/services/py/reimb/worker.py                 # SQS consumer → run graph
/services/py/tests/graph/test_graph.py
/infra/modules/data/main.tf                  # RDS Postgres + SQS queue
```

---

### Task 1: RDS Postgres + SQS (Terraform)

**Files:**
- Create: `infra/modules/data/main.tf`, `variables.tf`, `outputs.tf`
- Modify: `infra/main.tf`

**Interfaces:**
- Produces: outputs `db_endpoint`, `cases_queue_url`.

- [ ] **Step 1: Write the module**

```hcl
# infra/modules/data/main.tf
resource "aws_db_instance" "pg" {
  identifier        = "${var.name}-pg"
  engine            = "postgres"
  engine_version    = "16"
  instance_class    = "db.t4g.medium"
  allocated_storage = 20
  db_name           = "reimb"
  username          = "reimb"
  manage_master_user_password = true
  skip_final_snapshot = true
}

resource "aws_sqs_queue" "cases_dlq" { name = "${var.name}-cases-dlq" }

resource "aws_sqs_queue" "cases" {
  name                       = "${var.name}-cases"
  visibility_timeout_seconds = 300
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.cases_dlq.arn, maxReceiveCount = 5
  })
}
```

```hcl
# infra/modules/data/outputs.tf
output "db_endpoint" { value = aws_db_instance.pg.endpoint }
output "cases_queue_url" { value = aws_sqs_queue.cases.url }
```

- [ ] **Step 2: Validate & commit**

Run: `cd infra && terraform validate`
```bash
git add infra/modules/data infra/main.tf
git commit -m "infra: RDS Postgres and cases SQS queue with DLQ"
```

---

### Task 2: `POST /decisions` handler (Go) — validation + enqueue

**Files:**
- Create: `services/go/internal/api/decisions.go`
- Test: `services/go/internal/api/decisions_test.go`

**Interfaces:**
- Produces: `Handler{Store, Queue}.Decide(w, r)`; request type `DecideRequest`, response `{case_id, status:"accepted"}` (202).
- Consumes: `case.Store.Create(ctx, Case) error`, `queue.Enqueue(ctx, caseID string) error` (interfaces, mocked in test).

- [ ] **Step 1: Write the failing test**

```go
// services/go/internal/api/decisions_test.go
package api

import (
	"bytes"; "context"; "encoding/json"; "net/http"; "net/http/httptest"; "testing"
)

type fakeStore struct{ created string }
func (f *fakeStore) Create(_ context.Context, id string, _ []byte) error { f.created = id; return nil }
type fakeQueue struct{ enq string }
func (f *fakeQueue) Enqueue(_ context.Context, id string) error { f.enq = id; return nil }

func TestDecideAcceptsAndEnqueues(t *testing.T) {
	body := `{"case_id":"c1","documents":[],"claim":{"amount":10,"currency":"USD"},
	          "rules":{"A_auto":2000,"tau_d":0.85},"policy_version":"v3"}`
	h := &Handler{Store: &fakeStore{}, Queue: &fakeQueue{}}
	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/decisions", bytes.NewBufferString(body))
	h.Decide(rr, req)
	if rr.Code != http.StatusAccepted {
		t.Fatalf("code = %d, want 202", rr.Code)
	}
	var resp map[string]string
	json.Unmarshal(rr.Body.Bytes(), &resp)
	if resp["case_id"] != "c1" || resp["status"] != "accepted" {
		t.Fatalf("unexpected response %v", resp)
	}
}
```

- [ ] **Step 2: Run test (expect failure)**

Run: `cd services/go && go test ./internal/api/...`
Expected: FAIL — `undefined: Handler`.

- [ ] **Step 3: Implement the handler**

```go
// services/go/internal/api/decisions.go
package api

import (
	"context"; "encoding/json"; "io"; "net/http"
)

type Store interface { Create(ctx context.Context, id string, raw []byte) error }
type Queue interface { Enqueue(ctx context.Context, id string) error }

type Handler struct { Store Store; Queue Queue }

type DecideRequest struct {
	CaseID        string          `json:"case_id"`
	Documents     json.RawMessage `json:"documents"`
	Claim         json.RawMessage `json:"claim"`
	Rules         json.RawMessage `json:"rules"`
	PolicyVersion string          `json:"policy_version"`
}

func (h *Handler) Decide(w http.ResponseWriter, r *http.Request) {
	raw, _ := io.ReadAll(r.Body)
	var req DecideRequest
	if err := json.Unmarshal(raw, &req); err != nil || req.CaseID == "" {
		http.Error(w, "invalid request", http.StatusBadRequest); return
	}
	ctx := r.Context()
	if err := h.Store.Create(ctx, req.CaseID, raw); err != nil {
		http.Error(w, "store error", http.StatusInternalServerError); return
	}
	if err := h.Queue.Enqueue(ctx, req.CaseID); err != nil {
		http.Error(w, "queue error", http.StatusInternalServerError); return
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusAccepted)
	json.NewEncoder(w).Encode(map[string]string{"case_id": req.CaseID, "status": "accepted"})
}
```

- [ ] **Step 4: Run test to verify pass**

Run: `cd services/go && go test ./internal/api/...`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/go/internal/api
git commit -m "feat(api): POST /decisions validates and enqueues case"
```

---

### Task 3: LangGraph state + graph with stub nodes

**Files:**
- Create: `services/py/reimb/graph/state.py`, `nodes_stub.py`, `build.py`
- Test: `services/py/tests/graph/test_graph.py`

**Interfaces:**
- Produces: `build_graph() -> CompiledGraph`; `CaseState` keys:
  `case_id, claim, rules, extracted, citations, flags, decision, confidence, rationale`.

- [ ] **Step 1: Write the failing test**

```python
# services/py/tests/graph/test_graph.py
from reimb.graph.build import build_graph

def test_graph_runs_to_decision():
    g = build_graph()
    out = g.invoke({
        "case_id": "c1",
        "claim": {"amount": 10.0, "currency": "USD"},
        "rules": {"A_auto": 2000.0, "tau_d": 0.85, "require_receipt_proof": True},
        "flags": [],
    })
    assert out["decision"] in {"APPROVE", "DENY", "ESCALATE"}
    assert "rationale" in out
```

- [ ] **Step 2: Run test (expect failure)**

Run: `cd services/py && python -m pytest tests/graph -q`
Expected: FAIL — `ModuleNotFoundError: reimb.graph.build`.

- [ ] **Step 3: Implement state + stub nodes + graph**

```python
# services/py/reimb/graph/state.py
from typing import TypedDict, Any

class CaseState(TypedDict, total=False):
    case_id: str
    claim: dict[str, Any]
    rules: dict[str, Any]
    extracted: dict[str, Any]
    citations: list[str]
    flags: list[str]
    decision: str
    confidence: float
    rationale: str
```

```python
# services/py/reimb/graph/nodes_stub.py
from .state import CaseState

def intake(s: CaseState) -> CaseState: return {}
def extract(s: CaseState) -> CaseState:
    return {"extracted": dict(s["claim"]), "confidence": 0.95}
def policy_retrieve(s: CaseState) -> CaseState: return {"citations": ["STUB-01"]}
def validate(s: CaseState) -> CaseState: return {"flags": s.get("flags", [])}
def adjudicate(s: CaseState) -> CaseState:
    r = s["rules"]
    amt = s["claim"]["amount"]
    ok = (amt <= r["A_auto"] and s.get("confidence", 0) >= r["tau_d"]
          and not s.get("flags"))
    decision = "APPROVE" if ok else "ESCALATE"
    return {"decision": decision, "rationale": f"stub: amount {amt} -> {decision}"}
```

```python
# services/py/reimb/graph/build.py
from langgraph.graph import StateGraph, START, END
from .state import CaseState
from . import nodes_stub as n

def build_graph():
    g = StateGraph(CaseState)
    g.add_node("intake", n.intake)
    g.add_node("extract", n.extract)
    g.add_node("policy_retrieve", n.policy_retrieve)
    g.add_node("validate", n.validate)
    g.add_node("adjudicate", n.adjudicate)
    g.add_edge(START, "intake")
    g.add_edge("intake", "extract")
    # fork after extract:
    g.add_edge("extract", "policy_retrieve")
    g.add_edge("extract", "validate")
    # join into adjudicate:
    g.add_edge("policy_retrieve", "adjudicate")
    g.add_edge("validate", "adjudicate")
    g.add_edge("adjudicate", END)
    return g.compile()
```

- [ ] **Step 4: Run test to verify pass**

Run: `cd services/py && pip install langgraph && python -m pytest tests/graph -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/py/reimb/graph services/py/tests/graph
git commit -m "feat(graph): LangGraph state machine with stub nodes"
```

---

### Task 4: SQS worker that runs the graph

**Files:**
- Create: `services/py/reimb/worker.py`
- Test: `services/py/tests/graph/test_worker.py`

**Interfaces:**
- Consumes: `build_graph()` from Task 3; a `load_case(case_id) -> CaseState` callback (injected, so tests don't need AWS/DB).
- Produces: `process_message(body: dict, load_case, persist) -> CaseState`.

- [ ] **Step 1: Write the failing test**

```python
# services/py/tests/graph/test_worker.py
from reimb.worker import process_message

def test_process_message_persists_decision():
    saved = {}
    def load_case(cid):
        return {"case_id": cid, "claim": {"amount": 10.0, "currency": "USD"},
                "rules": {"A_auto": 2000.0, "tau_d": 0.85, "require_receipt_proof": True},
                "flags": []}
    def persist(cid, state): saved[cid] = state
    out = process_message({"case_id": "c1"}, load_case, persist)
    assert saved["c1"]["decision"] == "APPROVE"
    assert out["decision"] == "APPROVE"
```

- [ ] **Step 2: Run test (expect failure)**

Run: `cd services/py && python -m pytest tests/graph/test_worker.py -q`
Expected: FAIL — `ModuleNotFoundError: reimb.worker`.

- [ ] **Step 3: Implement the worker core**

```python
# services/py/reimb/worker.py
from typing import Callable
from .graph.build import build_graph
from .graph.state import CaseState

_GRAPH = build_graph()

def process_message(body: dict,
                    load_case: Callable[[str], CaseState],
                    persist: Callable[[str, CaseState], None]) -> CaseState:
    case_id = body["case_id"]
    state = load_case(case_id)
    result = _GRAPH.invoke(state)
    persist(case_id, result)
    return result
```

- [ ] **Step 4: Run test to verify pass**

Run: `cd services/py && python -m pytest tests/graph/test_worker.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/py/reimb/worker.py services/py/tests/graph/test_worker.py
git commit -m "feat(worker): SQS-driven graph runner with injected IO"
```

---

## Acceptance check

```bash
cd services/go && go test ./... && cd ../py && python -m pytest -q
```
Expected: handler accepts+enqueues; graph runs INTAKE→...→ADJUDICATE; worker persists a decision.

## Self-review notes

- Covers spec §2 (API front door, orchestrator, SQS), §3 (contract), §5 decision-flow topology.
- Postgres checkpointer wiring (durable HITL pause) is added in P7 when escalation exists; here
  the graph runs in-memory, which is sufficient to prove topology. Noted intentionally.
- Nodes are stubs by design; P3–P6 replace `extract`, `policy_retrieve`, `validate`, `adjudicate`.
