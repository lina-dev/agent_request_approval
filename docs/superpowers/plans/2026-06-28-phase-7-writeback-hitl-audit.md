# Phase 7: Writeback / HITL / Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the loop: write decisions back to the expense tool (behind an adapter), pause ESCALATE cases for human review via a durable LangGraph interrupt, and seal every case into an immutable audit record.

**Architecture:** A Go writeback service talks to the expense tool through an `ExpenseAdapter` interface (one concrete impl chosen now, others pluggable). ESCALATE cases use LangGraph's `interrupt` + Postgres checkpointer so the graph durably pauses until a human posts a decision to `POST /reviews/{case_id}`; resuming replays from the checkpoint. Every terminal decision is written to an append-only S3 audit object (Object Lock) capturing inputs, clauses, model versions, rationale, and final actor.

**Tech Stack:** Go (adapter + writeback + audit to S3 Object Lock), Python (LangGraph checkpointer + interrupt/resume), Postgres.

## Global Constraints

- Expense-tool access only through the `ExpenseAdapter` interface — no direct vendor calls elsewhere.
- ESCALATE durably pauses; a process restart must not lose the case (Postgres checkpointer).
- Audit records are write-once (S3 Object Lock, compliance mode) — never updated or deleted.
- Audit captures `model_versions`, `policy_version`, citations, and `final_actor` (agent|human).

---

## File structure

```
/services/go/internal/expense/adapter.go        # ExpenseAdapter interface + one impl
/services/go/internal/expense/adapter_test.go
/services/go/internal/audit/record.go            # immutable audit writer
/services/go/internal/audit/record_test.go
/services/py/reimb/graph/build.py                # add checkpointer + interrupt on ESCALATE
/services/py/reimb/review/resume.py              # apply human decision + resume
/services/py/tests/review/test_resume.py
/infra/modules/audit/main.tf                     # S3 Object Lock bucket
```

---

### Task 1: ExpenseAdapter interface + writeback

**Files:**
- Create: `services/go/internal/expense/adapter.go`
- Test: `services/go/internal/expense/adapter_test.go`

**Interfaces:**
- Produces: `ExpenseAdapter` interface `WriteDecision(ctx, caseID string, d Decision) error`;
  `Decision{Status, Rationale string; Citations []string}`; a `RecordingAdapter` test double.

- [ ] **Step 1: Write the failing test**

```go
// services/go/internal/expense/adapter_test.go
package expense

import ("context"; "testing")

func TestWritebackCallsAdapter(t *testing.T) {
	rec := &RecordingAdapter{}
	err := Writeback(context.Background(), rec, "c1",
		Decision{Status: "APPROVE", Rationale: "ok", Citations: []string{"M-01"}})
	if err != nil { t.Fatal(err) }
	if rec.Last.Status != "APPROVE" || rec.LastCase != "c1" {
		t.Fatalf("adapter not called correctly: %+v", rec)
	}
}
```

- [ ] **Step 2: Run (expect fail), then implement**

```go
// services/go/internal/expense/adapter.go
package expense

import "context"

type Decision struct {
	Status    string
	Rationale string
	Citations []string
}

type ExpenseAdapter interface {
	WriteDecision(ctx context.Context, caseID string, d Decision) error
}

// Writeback is the single entrypoint app code uses.
func Writeback(ctx context.Context, a ExpenseAdapter, caseID string, d Decision) error {
	return a.WriteDecision(ctx, caseID, d)
}

// RecordingAdapter is a test double; swap for a real vendor client (Concur/Expensify/Ramp).
type RecordingAdapter struct {
	Last     Decision
	LastCase string
}

func (r *RecordingAdapter) WriteDecision(_ context.Context, caseID string, d Decision) error {
	r.Last = d; r.LastCase = caseID; return nil
}
```

- [ ] **Step 3: Run to pass & commit**

Run: `cd services/go && go test ./internal/expense/...` → PASS.
```bash
git add services/go/internal/expense
git commit -m "feat(expense): ExpenseAdapter interface and writeback"
```

---

### Task 2: Immutable audit record (Go + S3 Object Lock)

**Files:**
- Create: `services/go/internal/audit/record.go`
- Test: `services/go/internal/audit/record_test.go`
- Create: `infra/modules/audit/main.tf`

**Interfaces:**
- Produces: `Build(caseID string, in CaseInput, dec Decision, meta Meta) Record` (deterministic JSON);
  `Put(ctx, putter, Record) error` where `putter` writes to Object-Lock S3 (mocked in test).

- [ ] **Step 1: Write the failing test**

```go
// services/go/internal/audit/record_test.go
package audit

import ("encoding/json"; "testing")

func TestRecordCapturesProvenance(t *testing.T) {
	r := Build("c1",
		CaseInput{PolicyVersion: "v3"},
		Decision{Status: "APPROVE", Citations: []string{"M-01"}},
		Meta{ModelVersions: map[string]string{"adjudicator": "llama-3.3-70b@abc"}, FinalActor: "agent"})
	b, _ := json.Marshal(r)
	for _, want := range []string{"v3", "M-01", "llama-3.3-70b@abc", "agent"} {
		if !contains(b, want) { t.Fatalf("record missing %q: %s", want, b) }
	}
}
func contains(b []byte, s string) bool { return len(s) > 0 && string(b) != "" && bytesContains(b, s) }
func bytesContains(b []byte, s string) bool { return indexOf(string(b), s) >= 0 }
func indexOf(h, n string) int { for i := 0; i+len(n) <= len(h); i++ { if h[i:i+len(n)] == n { return i } }; return -1 }
```

- [ ] **Step 2: Run (expect fail), then implement**

```go
// services/go/internal/audit/record.go
package audit

import "context"

type Decision struct {
	Status    string
	Citations []string
}
type CaseInput struct {
	PolicyVersion string
}
type Meta struct {
	ModelVersions map[string]string
	FinalActor    string // "agent" | "human"
}
type Record struct {
	CaseID        string            `json:"case_id"`
	PolicyVersion string            `json:"policy_version"`
	Status        string            `json:"status"`
	Citations     []string          `json:"policy_citations"`
	ModelVersions map[string]string `json:"model_versions"`
	FinalActor    string            `json:"final_actor"`
}

func Build(caseID string, in CaseInput, dec Decision, meta Meta) Record {
	return Record{
		CaseID: caseID, PolicyVersion: in.PolicyVersion, Status: dec.Status,
		Citations: dec.Citations, ModelVersions: meta.ModelVersions, FinalActor: meta.FinalActor,
	}
}

type Putter interface {
	Put(ctx context.Context, key string, body []byte) error
}

func Put(ctx context.Context, p Putter, r Record, body []byte) error {
	return p.Put(ctx, "audit/"+r.CaseID+".json", body)
}
```

```hcl
# infra/modules/audit/main.tf
resource "aws_s3_bucket" "audit" {
  bucket              = "${var.name}-audit"
  object_lock_enabled = true
}
resource "aws_s3_bucket_object_lock_configuration" "audit" {
  bucket = aws_s3_bucket.audit.id
  rule { default_retention { mode = "COMPLIANCE" days = 2555 } } # 7y
}
```

- [ ] **Step 3: Run to pass, validate infra, commit**

Run: `cd services/go && go test ./internal/audit/...` → PASS; `cd ../../infra && terraform validate`.
```bash
git add services/go/internal/audit infra/modules/audit
git commit -m "feat(audit): immutable provenance record + Object Lock bucket"
```

---

### Task 3: HITL durable interrupt + resume

**Files:**
- Modify: `services/py/reimb/graph/build.py` (Postgres checkpointer + interrupt on ESCALATE)
- Create: `services/py/reimb/review/resume.py`
- Test: `services/py/tests/review/test_resume.py`

**Interfaces:**
- Produces: `apply_human_decision(state, human: dict) -> dict` merging a reviewer's verdict and
  setting `final_actor="human"`; graph resumes from checkpoint after ESCALATE.

- [ ] **Step 1: Write the failing test (pure resume logic)**

```python
# services/py/tests/review/test_resume.py
from reimb.review.resume import apply_human_decision

def test_human_override_sets_actor_and_decision():
    state = {"case_id": "c1", "decision": "ESCALATE", "flags": ["amount_mismatch"]}
    out = apply_human_decision(state, {"verdict": "DENY", "rationale": "receipts don't match",
                                       "reviewer": "u-9"})
    assert out["decision"] == "DENY"
    assert out["final_actor"] == "human"
    assert out["reviewer"] == "u-9"
```

- [ ] **Step 2: Run (expect fail), then implement**

```python
# services/py/reimb/review/resume.py
def apply_human_decision(state: dict, human: dict) -> dict:
    if human["verdict"] not in {"APPROVE", "DENY"}:
        raise ValueError("human verdict must be APPROVE or DENY")
    return {**state,
            "decision": human["verdict"],
            "rationale": human.get("rationale", state.get("rationale", "")),
            "final_actor": "human",
            "reviewer": human.get("reviewer")}
```

For the graph: compile with a checkpointer and interrupt before the terminal node when
`decision == "ESCALATE"`:
```python
# in build.py
from langgraph.checkpoint.postgres import PostgresSaver
# g.compile(checkpointer=PostgresSaver.from_conn_string(DSN),
#           interrupt_before=["await_human"])
```

- [ ] **Step 3: Run to pass & commit**

Run: `cd services/py && python -m pytest tests/review -q` → PASS.
```bash
git add services/py/reimb/review services/py/tests/review services/py/reimb/graph/build.py
git commit -m "feat(hitl): durable escalation interrupt and human-decision resume"
```

---

## Acceptance check

```bash
cd services/go && go test ./internal/expense/... ./internal/audit/... \
 && cd ../py && python -m pytest tests/review -q
```
Expected: writeback hits the adapter; audit captures full provenance; human override sets
`final_actor=human` and resolves the decision.

## Self-review notes

- Covers spec §2/§4 writeback, §5 HITL escalation, §8 immutable audit, integration adapter.
- Concrete vendor adapter (Concur vs Expensify vs Ramp) chosen at execution time — interface is
  the stable contract; `RecordingAdapter` proves the seam.
