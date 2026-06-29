"""Chunk the company policy corpus into independently citable clause rows."""

from __future__ import annotations


def chunk_corpus(docs: list[dict]) -> list[dict]:
    """Flatten policy docs into clause rows with stable ids.

    Each input doc: ``{category, policy_version, clauses: [{id, text}]}``.
    Returns rows: ``{clause_id, text, category, policy_version}``.
    """
    rows: list[dict] = []
    for doc in docs or []:
        category = doc.get("category", "")
        version = doc.get("policy_version", "")
        for clause in doc.get("clauses", []) or []:
            cid = clause.get("id")
            text = clause.get("text", "")
            if not cid or not text:
                continue  # skip malformed clauses rather than emit uncitable rows
            rows.append({
                "clause_id": cid,
                "text": text,
                "category": category,
                "policy_version": version,
            })
    return rows
