"""Run a compiled graph over a labeled gold set and score it."""

from __future__ import annotations

import json

from .metrics import compute_metrics


def run_eval(graph, gold_path: str) -> dict:
    """Invoke *graph* per gold case, comparing decision to the label."""
    results: list[dict] = []
    with open(gold_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            case = json.loads(line)
            out = graph.invoke(case["input"])
            results.append({"predicted": out.get("decision", "ESCALATE"),
                            "gold": case["gold"]})
    return compute_metrics(results)


def assert_thresholds(metrics: dict, *, max_false_approval: float = 0.01,
                      min_accuracy: float = 0.95) -> None:
    """Raise AssertionError if metrics regress past the spec's gates."""
    assert metrics["false_approval_rate"] < max_false_approval, metrics
    assert metrics["decision_accuracy"] >= min_accuracy, metrics
