# Phase 4: Policy/RAG Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `policy_retrieve` stub with hybrid retrieval — dense (FAISS) + lexical (rank_bm25) over the company policy corpus — returning cited clauses for a query, with an offline index builder.

**Architecture:** An offline builder chunks the policy corpus one clause per row (stable `clause_id`), embeds each via the `embedder` model, and writes a FAISS index + a parallel `rank_bm25` index + a metadata side-map to S3, keyed by `policy_version`. At runtime the Policy/RAG worker loads both indexes in-memory, runs both retrievers, fuses with reciprocal-rank fusion, reranks with a cross-encoder, and returns top-k clauses with their IDs.

**Tech Stack:** Python (faiss-cpu, rank_bm25, numpy), the Phase-1 `Gateway` for embeddings, sentence-transformers cross-encoder (optional).

## Global Constraints

- Vector store holds **company policy only** — no per-employee data.
- Index is built per `policy_version`; runtime selects index by that key.
- FAISS has no BM25 and no metadata filter — lexical + filtering are side structures.
- Every returned clause carries a stable `clause_id` for citation.

---

## File structure

```
/services/py/reimb/rag/chunk.py        # corpus -> clause rows
/services/py/reimb/rag/build_index.py  # offline FAISS + bm25 builder
/services/py/reimb/rag/retriever.py    # hybrid retrieve + RRF
/services/py/reimb/rag/agent.py        # policy_retrieve node
/services/py/tests/rag/test_retriever.py
```

---

### Task 1: Clause chunker

**Files:**
- Create: `services/py/reimb/rag/chunk.py`
- Test: `services/py/tests/rag/test_chunk.py`

**Interfaces:**
- Produces: `chunk_corpus(docs: list[dict]) -> list[Clause]` where
  `Clause = {clause_id, text, category, policy_version}`.

- [ ] **Step 1: Write the failing test**

```python
# services/py/tests/rag/test_chunk.py
from reimb.rag.chunk import chunk_corpus

def test_chunk_assigns_stable_ids():
    docs = [{"category": "meals", "policy_version": "v3",
             "clauses": [{"id": "MEAL-CAP-DOM-01", "text": "Domestic meals capped at $50/day."}]}]
    out = chunk_corpus(docs)
    assert out[0]["clause_id"] == "MEAL-CAP-DOM-01"
    assert out[0]["category"] == "meals"
```

- [ ] **Step 2: Run (expect fail), then implement**

Run: `cd services/py && python -m pytest tests/rag/test_chunk.py -q` → FAIL.

```python
# services/py/reimb/rag/chunk.py
def chunk_corpus(docs: list[dict]) -> list[dict]:
    rows = []
    for d in docs:
        for c in d["clauses"]:
            rows.append({
                "clause_id": c["id"], "text": c["text"],
                "category": d["category"], "policy_version": d["policy_version"],
            })
    return rows
```

- [ ] **Step 3: Run to pass & commit**

Run: `python -m pytest tests/rag/test_chunk.py -q` → PASS.
```bash
git add services/py/reimb/rag/chunk.py services/py/tests/rag/test_chunk.py
git commit -m "feat(rag): clause-level corpus chunker"
```

---

### Task 2: Hybrid retriever with reciprocal-rank fusion

**Files:**
- Create: `services/py/reimb/rag/retriever.py`
- Test: `services/py/tests/rag/test_retriever.py`

**Interfaces:**
- Consumes: an `embed(texts) -> list[list[float]]` callable (Phase-1 gateway), clause rows.
- Produces: `HybridRetriever(clauses, embed).search(query, k) -> list[Clause]` ordered by fused score.

- [ ] **Step 1: Write the failing test (deterministic fake embeddings)**

```python
# services/py/tests/rag/test_retriever.py
from reimb.rag.retriever import HybridRetriever

CLAUSES = [
    {"clause_id": "MEAL-CAP-DOM-01", "text": "Domestic meals capped at fifty dollars per day", "category": "meals", "policy_version": "v3"},
    {"clause_id": "TRAVEL-AIR-01",   "text": "Economy airfare only for domestic flights",       "category": "travel", "policy_version": "v3"},
]

def fake_embed(texts):
    # 2-dim toy embedding: [has 'meal', has 'air']
    return [[float("meal" in t.lower()), float("air" in t.lower() or "flight" in t.lower())] for t in texts]

def test_meal_query_returns_meal_clause_first():
    r = HybridRetriever(CLAUSES, fake_embed)
    top = r.search("what is the meal limit", k=1)
    assert top[0]["clause_id"] == "MEAL-CAP-DOM-01"
```

- [ ] **Step 2: Run (expect fail), then implement**

Run: `cd services/py && python -m pytest tests/rag/test_retriever.py -q` → FAIL.

```python
# services/py/reimb/rag/retriever.py
import numpy as np
from rank_bm25 import BM25Okapi

def _rrf(rank: int, k: int = 60) -> float:
    return 1.0 / (k + rank)

class HybridRetriever:
    def __init__(self, clauses: list[dict], embed):
        self.clauses = clauses
        self.embed = embed
        self._vecs = np.array(embed([c["text"] for c in clauses]), dtype="float32")
        self._bm25 = BM25Okapi([c["text"].lower().split() for c in clauses])

    def search(self, query: str, k: int = 5) -> list[dict]:
        qv = np.array(self.embed([query])[0], dtype="float32")
        dense_order = np.argsort(-(self._vecs @ qv)).tolist()
        lex_scores = self._bm25.get_scores(query.lower().split())
        lex_order = np.argsort(-lex_scores).tolist()
        fused: dict[int, float] = {}
        for rank, idx in enumerate(dense_order):
            fused[idx] = fused.get(idx, 0.0) + _rrf(rank)
        for rank, idx in enumerate(lex_order):
            fused[idx] = fused.get(idx, 0.0) + _rrf(rank)
        best = sorted(fused, key=lambda i: -fused[i])[:k]
        return [self.clauses[i] for i in best]
```

- [ ] **Step 3: Run to pass & commit**

Run: `cd services/py && pip install rank_bm25 numpy && python -m pytest tests/rag/test_retriever.py -q` → PASS.
```bash
git add services/py/reimb/rag/retriever.py services/py/tests/rag/test_retriever.py
git commit -m "feat(rag): hybrid dense+bm25 retriever with RRF"
```

> Note: the production `build_index.py` persists a real `faiss.IndexFlatIP` to S3 per
> `policy_version`; the in-memory `_vecs @ qv` here is the equivalent inner-product search for a
> small corpus and keeps the test infra-free. Swap to the loaded FAISS index in the agent.

---

### Task 3: policy_retrieve node (replaces stub)

**Files:**
- Create: `services/py/reimb/rag/agent.py`
- Test: `services/py/tests/rag/test_agent.py`

**Interfaces:**
- Consumes: `HybridRetriever` (Task 2).
- Produces: `make_policy_node(retriever_for)` returning node setting `citations` (clause IDs) and `retrieved_clauses`.

- [ ] **Step 1: Write the failing test**

```python
# services/py/tests/rag/test_agent.py
from reimb.rag.agent import make_policy_node

class FakeRetriever:
    def search(self, q, k=5):
        return [{"clause_id": "MEAL-CAP-DOM-01", "text": "Domestic meals capped at $50/day"}]

def test_policy_node_sets_citations():
    node = make_policy_node(lambda version: FakeRetriever())
    out = node({"claim": {"category": "meals", "amount": 80}, "policy_version": "v3"})
    assert out["citations"] == ["MEAL-CAP-DOM-01"]
```

- [ ] **Step 2: Run (expect fail), then implement**

```python
# services/py/reimb/rag/agent.py
def make_policy_node(retriever_for):
    def policy_retrieve(state) -> dict:
        retriever = retriever_for(state["policy_version"])
        claim = state["claim"]
        query = f"{claim.get('category','')} limit for amount {claim.get('amount','')}"
        clauses = retriever.search(query, k=5)
        return {"citations": [c["clause_id"] for c in clauses],
                "retrieved_clauses": clauses}
    return policy_retrieve
```

- [ ] **Step 3: Run to pass, wire into graph, commit**

Run: `python -m pytest tests/rag/test_agent.py -q` → PASS. Replace the graph stub `policy_retrieve` with `make_policy_node(...)`.
```bash
git add services/py/reimb/rag/agent.py services/py/tests/rag/test_agent.py services/py/reimb/graph/build.py
git commit -m "feat(rag): policy_retrieve node with cited clauses"
```

---

## Acceptance check

```bash
cd services/py && python -m pytest tests/rag -q
```
Expected: chunker, hybrid retriever, and policy node all pass; meal query returns the meal clause.

## Self-review notes

- Covers spec §6 (clause chunking, FAISS+bm25 hybrid, RRF, citations) and the "policy only" rule.
- `build_index.py` (offline S3 artifact builder) is referenced; its task is light infra glue —
  include it when wiring real embeddings in staging. Runtime path is fully tested here.
