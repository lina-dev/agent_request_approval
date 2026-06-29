# Phase 3: Extraction Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `extract` stub with a real VLM worker that turns a receipt image (from S3) into validated structured fields plus a confidence score, with a bounded repair loop.

**Architecture:** The extract node fetches image bytes from S3, base64-encodes them, and calls the `extractor` logical model via the Phase-1 Gateway with an image content-block and a strict JSON schema. A Pydantic model validates output; on schema failure or low confidence it re-prompts up to 2 times, then sets `flags += ["extraction_low_confidence"]` so the graph escalates.

**Tech Stack:** Python (Pydantic v2, boto3 for S3), the Phase-1 `Gateway`, Qwen2.5-VL via vLLM.

## Global Constraints

- Extraction output MUST validate against `ReceiptFields` schema or trigger repair.
- Max 2 repair retries; then escalate (never silently pass bad data).
- Image bytes come from S3 by URI — never inline in the case payload.
- `tau_x` (extraction confidence floor) comes from `rules`, default 0.80.

---

## File structure

```
/services/py/reimb/extract/schema.py     # ReceiptFields Pydantic model
/services/py/reimb/extract/agent.py      # extract node (replaces stub)
/services/py/reimb/extract/s3_image.py   # fetch + base64 encode
/services/py/tests/extract/test_schema.py
/services/py/tests/extract/test_agent.py
```

---

### Task 1: ReceiptFields schema

**Files:**
- Create: `services/py/reimb/extract/schema.py`
- Test: `services/py/tests/extract/test_schema.py`

**Interfaces:**
- Produces: `ReceiptFields(merchant, date, amount, currency, tax, line_items, confidence)`
  with `parse_or_none(data: dict) -> ReceiptFields | None`.

- [ ] **Step 1: Write the failing test**

```python
# services/py/tests/extract/test_schema.py
from reimb.extract.schema import ReceiptFields, parse_or_none

def test_valid_parses():
    rf = parse_or_none({
        "merchant": "Cafe X", "date": "2026-06-20", "amount": 12.5,
        "currency": "USD", "tax": 1.0, "line_items": [{"desc": "latte", "amount": 12.5}],
        "confidence": 0.91,
    })
    assert rf is not None and rf.amount == 12.5

def test_missing_required_returns_none():
    assert parse_or_none({"merchant": "X"}) is None
```

- [ ] **Step 2: Run test (expect failure)**

Run: `cd services/py && python -m pytest tests/extract/test_schema.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement schema**

```python
# services/py/reimb/extract/schema.py
from pydantic import BaseModel, ValidationError

class LineItem(BaseModel):
    desc: str
    amount: float

class ReceiptFields(BaseModel):
    merchant: str
    date: str            # ISO yyyy-mm-dd
    amount: float
    currency: str
    tax: float = 0.0
    line_items: list[LineItem] = []
    confidence: float

def parse_or_none(data: dict) -> "ReceiptFields | None":
    try:
        return ReceiptFields(**data)
    except (ValidationError, TypeError):
        return None
```

- [ ] **Step 4: Run test to verify pass**

Run: `cd services/py && pip install pydantic && python -m pytest tests/extract/test_schema.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/py/reimb/extract/schema.py services/py/tests/extract/test_schema.py
git commit -m "feat(extract): ReceiptFields schema with safe parse"
```

---

### Task 2: Extract node with repair loop

**Files:**
- Create: `services/py/reimb/extract/agent.py`, `services/py/reimb/extract/s3_image.py`
- Test: `services/py/tests/extract/test_agent.py`

**Interfaces:**
- Consumes: `Gateway.chat` (Phase 1), `ReceiptFields`/`parse_or_none` (Task 1).
- Produces: `make_extract_node(gateway, fetch_image)` returning a node `extract(state) -> dict`
  that sets `extracted` + `confidence`, or appends `extraction_low_confidence` flag.

- [ ] **Step 1: Write the failing test (gateway + S3 mocked)**

```python
# services/py/tests/extract/test_agent.py
from reimb.extract.agent import make_extract_node

class FakeGateway:
    def __init__(self, contents): self._c = list(contents)
    def chat(self, model, messages, **kw):
        return {"choices": [{"message": {"content": self._c.pop(0)}}]}

def fetch_image(uri): return "BASE64DATA"

def test_extract_success():
    good = '{"merchant":"X","date":"2026-06-20","amount":12.5,"currency":"USD","confidence":0.9}'
    node = make_extract_node(FakeGateway([good]), fetch_image)
    out = node({"case_id": "c1", "documents": [{"uri": "s3://b/r.jpg"}],
                "rules": {"tau_x": 0.8}})
    assert out["extracted"]["amount"] == 12.5
    assert out["confidence"] == 0.9

def test_extract_repairs_then_escalates():
    bad = "not json"
    node = make_extract_node(FakeGateway([bad, bad, bad]), fetch_image)
    out = node({"case_id": "c1", "documents": [{"uri": "s3://b/r.jpg"}],
                "rules": {"tau_x": 0.8}})
    assert "extraction_low_confidence" in out["flags"]
```

- [ ] **Step 2: Run test (expect failure)**

Run: `cd services/py && python -m pytest tests/extract/test_agent.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement s3_image + agent**

```python
# services/py/reimb/extract/s3_image.py
import base64, boto3
from urllib.parse import urlparse

def fetch_image_b64(uri: str) -> str:
    p = urlparse(uri)
    obj = boto3.client("s3").get_object(Bucket=p.netloc, Key=p.path.lstrip("/"))
    return base64.b64encode(obj["Body"].read()).decode()
```

```python
# services/py/reimb/extract/agent.py
import json
from .schema import parse_or_none

_PROMPT = ("Extract receipt fields as strict JSON with keys "
           "merchant,date,amount,currency,tax,line_items,confidence. JSON only.")

def make_extract_node(gateway, fetch_image):
    def extract(state) -> dict:
        tau_x = state["rules"].get("tau_x", 0.80)
        uri = state["documents"][0]["uri"]
        img = fetch_image(uri)
        messages = [{"role": "user", "content": [
            {"type": "text", "text": _PROMPT},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img}"}},
        ]}]
        for _ in range(3):  # 1 try + 2 repairs
            content = gateway.chat("extractor", messages)["choices"][0]["message"]["content"]
            try:
                rf = parse_or_none(json.loads(content))
            except (json.JSONDecodeError, TypeError):
                rf = None
            if rf and rf.confidence >= tau_x:
                return {"extracted": rf.model_dump(), "confidence": rf.confidence}
            messages.append({"role": "user",
                             "content": "Output was invalid or low-confidence. Return strict JSON only."})
        return {"flags": state.get("flags", []) + ["extraction_low_confidence"]}
    return extract
```

- [ ] **Step 4: Run test to verify pass**

Run: `cd services/py && python -m pytest tests/extract/test_agent.py -q`
Expected: PASS (both cases).

- [ ] **Step 5: Wire into graph (replace stub) & commit**

In `reimb/graph/build.py`, replace the stub `extract` with `make_extract_node(gateway, fetch_image_b64)` (gateway injected at app startup). Then:
```bash
git add services/py/reimb/extract services/py/tests/extract services/py/reimb/graph/build.py
git commit -m "feat(extract): VLM extract node with bounded repair loop"
```

---

## Acceptance check

```bash
cd services/py && python -m pytest tests/extract -q
```
Expected: schema + agent tests pass; bad output escalates after 2 repairs.

## Self-review notes

- Covers spec §4 Extraction agent, §4 planning (extraction-repair loop, max 2 retries), §3 S3 image flow.
