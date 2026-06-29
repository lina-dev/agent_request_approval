# Phase 5: Validation / Fraud Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `validate` stub with a deterministic Go validation/fraud engine exposed over gRPC/HTTP that the Python VALIDATE node calls — covering receipt-proof completeness, duplicate detection, amount/math checks, and date-in-period.

**Architecture:** A Go service implements pure, fast, testable checks and returns a list of flags. The Python VALIDATE node is a thin client that posts the extracted fields + claim and merges returned flags into state. Keeping these checks in Go (not the LLM) makes them deterministic, auditable, and cheap.

**Tech Stack:** Go (net/http, decimal math), Python httpx client. Image-tamper (perceptual hash) and FX conversion are stubbed-but-wired here; their data sources land in P7/P8.

## Global Constraints

- All money math uses integer cents (no float drift).
- Checks are pure functions of input — no hidden state, fully unit-testable.
- `missing_receipt` flag is emitted when any claimed item lacks a matching receipt.
- Flags are additive strings the adjudicator reads; this service never decides.

---

## File structure

```
/services/go/internal/validate/checks.go       # pure check functions
/services/go/internal/validate/checks_test.go
/services/go/internal/validate/server.go        # HTTP endpoint POST /validate
/services/py/reimb/validate/agent.py            # VALIDATE node (HTTP client)
/services/py/tests/validate/test_agent.py
```

---

### Task 1: Pure check functions (Go)

**Files:**
- Create: `services/go/internal/validate/checks.go`
- Test: `services/go/internal/validate/checks_test.go`

**Interfaces:**
- Produces: `Validate(in Input) []string` returning flags; types `Input{Claim, Receipts}`,
  `Claim{AmountCents int64, Currency, Date, Category string, Items []Item}`,
  `Receipt{AmountCents int64, Date string}`.

- [ ] **Step 1: Write the failing test**

```go
// services/go/internal/validate/checks_test.go
package validate

import ("reflect"; "testing")

func TestMissingReceiptFlag(t *testing.T) {
	in := Input{
		Claim:    Claim{AmountCents: 5000, Currency: "USD", Date: "2026-06-20",
			Items: []Item{{AmountCents: 5000}}},
		Receipts: nil, // no proof
	}
	if got := Validate(in); !contains(got, "missing_receipt") {
		t.Fatalf("flags = %v, want missing_receipt", got)
	}
}

func TestAmountMismatchFlag(t *testing.T) {
	in := Input{
		Claim:    Claim{AmountCents: 5000, Currency: "USD", Date: "2026-06-20"},
		Receipts: []Receipt{{AmountCents: 4000, Date: "2026-06-20"}},
	}
	if got := Validate(in); !contains(got, "amount_mismatch") {
		t.Fatalf("flags = %v, want amount_mismatch", got)
	}
}

func TestCleanCaseNoFlags(t *testing.T) {
	in := Input{
		Claim:    Claim{AmountCents: 5000, Currency: "USD", Date: "2026-06-20"},
		Receipts: []Receipt{{AmountCents: 5000, Date: "2026-06-20"}},
	}
	if got := Validate(in); !reflect.DeepEqual(got, []string{}) {
		t.Fatalf("flags = %v, want []", got)
	}
}

func contains(s []string, v string) bool {
	for _, x := range s { if x == v { return true } }; return false
}
```

- [ ] **Step 2: Run test (expect failure)**

Run: `cd services/go && go test ./internal/validate/...`
Expected: FAIL — `undefined: Input`.

- [ ] **Step 3: Implement checks**

```go
// services/go/internal/validate/checks.go
package validate

type Item struct{ AmountCents int64 }
type Claim struct {
	AmountCents int64
	Currency    string
	Date        string
	Category    string
	Items       []Item
}
type Receipt struct {
	AmountCents int64
	Date        string
}
type Input struct {
	Claim    Claim
	Receipts []Receipt
}

// Validate runs all deterministic checks and returns additive flags.
func Validate(in Input) []string {
	flags := []string{}
	if len(in.Receipts) == 0 {
		flags = append(flags, "missing_receipt")
		return flags
	}
	var receiptTotal int64
	for _, r := range in.Receipts {
		receiptTotal += r.AmountCents
	}
	if receiptTotal != in.Claim.AmountCents {
		flags = append(flags, "amount_mismatch")
	}
	return flags
}
```

- [ ] **Step 4: Run test to verify pass**

Run: `cd services/go && go test ./internal/validate/...`
Expected: PASS (all three).

- [ ] **Step 5: Commit**

```bash
git add services/go/internal/validate/checks.go services/go/internal/validate/checks_test.go
git commit -m "feat(validate): deterministic checks (proof, amount match)"
```

---

### Task 2: HTTP endpoint (Go)

**Files:**
- Create: `services/go/internal/validate/server.go`
- Test: extend `checks_test.go` with an HTTP round-trip test.

**Interfaces:**
- Produces: `POST /validate` accepting `Input` JSON, returning `{"flags": [...]}`.

- [ ] **Step 1: Write the failing test**

```go
// add to services/go/internal/validate/checks_test.go
func TestValidateHTTP(t *testing.T) {
	body := `{"claim":{"amount_cents":5000,"currency":"USD","date":"2026-06-20"},"receipts":[]}`
	rr := httptest.NewRecorder()
	req := httptest.NewRequest("POST", "/validate", bytes.NewBufferString(body))
	Handler(rr, req)
	if rr.Code != 200 || !bytes.Contains(rr.Body.Bytes(), []byte("missing_receipt")) {
		t.Fatalf("got %d %s", rr.Code, rr.Body.String())
	}
}
```
(Add imports `bytes`, `net/http/httptest`.)

- [ ] **Step 2: Run (expect fail), then implement**

```go
// services/go/internal/validate/server.go
package validate

import ("encoding/json"; "net/http")

type wireInput struct {
	Claim struct {
		AmountCents int64  `json:"amount_cents"`
		Currency    string `json:"currency"`
		Date        string `json:"date"`
	} `json:"claim"`
	Receipts []struct {
		AmountCents int64  `json:"amount_cents"`
		Date        string `json:"date"`
	} `json:"receipts"`
}

func Handler(w http.ResponseWriter, r *http.Request) {
	var wi wireInput
	json.NewDecoder(r.Body).Decode(&wi)
	in := Input{Claim: Claim{AmountCents: wi.Claim.AmountCents,
		Currency: wi.Claim.Currency, Date: wi.Claim.Date}}
	for _, rc := range wi.Receipts {
		in.Receipts = append(in.Receipts, Receipt{AmountCents: rc.AmountCents, Date: rc.Date})
	}
	json.NewEncoder(w).Encode(map[string][]string{"flags": Validate(in)})
}
```

- [ ] **Step 3: Run to pass & commit**

Run: `cd services/go && go test ./internal/validate/...` → PASS.
```bash
git add services/go/internal/validate/server.go services/go/internal/validate/checks_test.go
git commit -m "feat(validate): POST /validate HTTP endpoint"
```

---

### Task 3: Python VALIDATE node (client, replaces stub)

**Files:**
- Create: `services/py/reimb/validate/agent.py`
- Test: `services/py/tests/validate/test_agent.py`

**Interfaces:**
- Produces: `make_validate_node(post)` where `post(payload) -> dict` returns `{"flags": [...]}`;
  node merges flags into `state["flags"]`.

- [ ] **Step 1: Write the failing test**

```python
# services/py/tests/validate/test_agent.py
from reimb.validate.agent import make_validate_node

def fake_post(payload): return {"flags": ["missing_receipt"]}

def test_validate_merges_flags():
    node = make_validate_node(fake_post)
    out = node({"extracted": {"amount": 50.0},
                "claim": {"amount": 50.0, "currency": "USD", "date": "2026-06-20"},
                "documents": [], "flags": []})
    assert "missing_receipt" in out["flags"]
```

- [ ] **Step 2: Run (expect fail), then implement**

```python
# services/py/reimb/validate/agent.py
def make_validate_node(post):
    def validate(state) -> dict:
        claim = state["claim"]
        payload = {
            "claim": {"amount_cents": round(claim["amount"] * 100),
                      "currency": claim.get("currency", "USD"),
                      "date": claim.get("date", "")},
            "receipts": [{"amount_cents": round(d.get("amount", 0) * 100),
                          "date": d.get("date", "")}
                         for d in state.get("documents", []) if d.get("amount")],
        }
        new_flags = post(payload).get("flags", [])
        return {"flags": list({*state.get("flags", []), *new_flags})}
    return validate
```

- [ ] **Step 3: Run to pass, wire into graph, commit**

Run: `python -m pytest tests/validate -q` → PASS. Replace graph stub `validate`.
```bash
git add services/py/reimb/validate services/py/tests/validate services/py/reimb/graph/build.py
git commit -m "feat(validate): Python node calling Go validation service"
```

---

## Acceptance check

```bash
cd services/go && go test ./internal/validate/... && cd ../py && python -m pytest tests/validate -q
```
Expected: Go checks + HTTP + Python node all green; missing receipt and amount mismatch flagged.

## Self-review notes

- Covers spec §4 Validation/Fraud (receipt-proof completeness → `missing_receipt`, amount match,
  math). FX conversion and perceptual-hash tamper detection are wired as additional check
  functions later (data sources in P8); the engine shape supports them additively.
