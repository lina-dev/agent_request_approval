"""Single entrypoint to all models via the LiteLLM gateway.

Agents never call vLLM directly. Transient HTTP failures (timeouts, 5xx, 429)
are mapped to ``GatewayError`` so ``retry_loop`` can retry them; 4xx client
errors are mapped to a terminal ``GatewayError`` subclass-free ReimbError path
(raised as ValueError) since retrying won't help.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..errors import GatewayError, ReimbError

_RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class GatewayClientError(ReimbError):
    """Non-retryable 4xx from the gateway (bad request, auth)."""


class Gateway:
    def __init__(self, base_url: str, api_key: str, timeout: float = 60.0,
                 client: httpx.Client | None = None):
        self._client = client or httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

    def _post(self, path: str, payload: dict) -> dict:
        try:
            resp = self._client.post(path, json=payload)
        except (httpx.TimeoutException, httpx.TransportError) as err:
            raise GatewayError(f"transport error calling {path}: {err!r}") from err
        if resp.status_code in _RETRYABLE_STATUS:
            raise GatewayError(f"gateway {resp.status_code} on {path}")
        if resp.status_code >= 400:
            raise GatewayClientError(f"gateway {resp.status_code} on {path}: {resp.text[:200]}")
        try:
            return resp.json()
        except ValueError as err:
            raise GatewayError(f"non-JSON response from {path}") from err

    def chat(self, model: str, messages: list[dict], **kw: Any) -> dict:
        return self._post("/v1/chat/completions",
                          {"model": model, "messages": messages, **kw})

    def chat_content(self, model: str, messages: list[dict], **kw: Any) -> str:
        """Convenience: return the assistant message text, or raise GatewayError."""
        data = self.chat(model, messages, **kw)
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as err:
            raise GatewayError(f"malformed chat response: {data!r}") from err

    def embed(self, texts: list[str], model: str = "embedder") -> list[list[float]]:
        data = self._post("/v1/embeddings", {"model": model, "input": texts})
        try:
            return [d["embedding"] for d in data["data"]]
        except (KeyError, TypeError) as err:
            raise GatewayError(f"malformed embeddings response: {data!r}") from err
