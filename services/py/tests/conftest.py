"""Shared fixtures and helpers."""

from __future__ import annotations

import pytest

from reimb.obs import trace


@pytest.fixture(autouse=True)
def _reset_spans():
    """Each test starts with a clean span collector."""
    trace.reset()
    yield
    trace.reset()


def no_sleep(_seconds: float) -> None:
    """Injectable sleeper that makes retry loops instant in tests."""
    return None


class FakeGateway:
    """Returns queued chat contents; raises queued exceptions if provided."""

    def __init__(self, contents):
        self._contents = list(contents)
        self.calls = 0

    def chat_content(self, model, messages, **kw):
        self.calls += 1
        item = self._contents.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def chat(self, model, messages, **kw):
        return {"choices": [{"message": {"content": self.chat_content(model, messages)}}]}

    def embed(self, texts, model="embedder"):
        # toy 3-dim embedding keyed on a few policy words
        return [[float("meal" in t.lower()),
                 float("air" in t.lower() or "flight" in t.lower()),
                 float("hotel" in t.lower() or "lodging" in t.lower())] for t in texts]
