"""Hybrid retrieval: dense (vector) + lexical (BM25) fused with RRF.

FAISS has no BM25 and no metadata filter, so the lexical index and the
``policy_version``/``category`` filter are side structures maintained here. At
this corpus size the dense half is an exact inner-product search (numpy), which
is what a ``faiss.IndexFlatIP`` computes; swap in the loaded FAISS index in
production with no interface change.
"""

from __future__ import annotations

from typing import Callable

import numpy as np
from rank_bm25 import BM25Okapi


def _rrf(rank: int, k: int = 60) -> float:
    return 1.0 / (k + rank)


def _normalize(v: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(v, axis=-1, keepdims=True)
    norm[norm == 0] = 1.0
    return v / norm


class HybridRetriever:
    """Build once per ``policy_version`` from clause rows."""

    def __init__(self, clauses: list[dict], embed: Callable[[list[str]], list[list[float]]]):
        if not clauses:
            raise ValueError("HybridRetriever requires at least one clause")
        self.clauses = clauses
        self._embed = embed
        vecs = np.array(embed([c["text"] for c in clauses]), dtype="float32")
        self._vecs = _normalize(vecs)
        self._bm25 = BM25Okapi([c["text"].lower().split() for c in clauses])

    def search(self, query: str, k: int = 5,
               category: str | None = None) -> list[dict]:
        """Return up to *k* clauses ranked by fused dense+lexical score.

        ``category`` optionally restricts results (the metadata filter FAISS
        lacks). Falls back to unfiltered results if the filter empties the set.
        """
        if not query or not query.strip():
            return []
        qv = _normalize(np.array(self._embed([query])[0], dtype="float32"))
        dense_order = np.argsort(-(self._vecs @ qv)).tolist()
        lex_scores = self._bm25.get_scores(query.lower().split())
        lex_order = np.argsort(-lex_scores).tolist()

        fused: dict[int, float] = {}
        for rank, idx in enumerate(dense_order):
            fused[idx] = fused.get(idx, 0.0) + _rrf(rank)
        for rank, idx in enumerate(lex_order):
            fused[idx] = fused.get(idx, 0.0) + _rrf(rank)

        ordered = sorted(fused, key=lambda i: -fused[i])
        if category:
            filtered = [i for i in ordered if self.clauses[i].get("category") == category]
            if filtered:
                ordered = filtered
        return [self.clauses[i] for i in ordered[:k]]
