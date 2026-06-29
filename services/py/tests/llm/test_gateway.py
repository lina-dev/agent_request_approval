import httpx
import pytest
import respx

from reimb.errors import GatewayError
from reimb.llm.gateway import Gateway, GatewayClientError


@respx.mock
def test_chat_routes_logical_model_name():
    route = respx.post("http://gw/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]})
    )
    gw = Gateway(base_url="http://gw", api_key="sk-test")
    assert gw.chat_content("adjudicator", [{"role": "user", "content": "x"}]) == "hi"
    sent = route.calls.last.request.content.replace(b" ", b"")
    assert b'"model":"adjudicator"' in sent


@respx.mock
def test_5xx_maps_to_retryable_gateway_error():
    respx.post("http://gw/v1/chat/completions").mock(return_value=httpx.Response(503))
    gw = Gateway(base_url="http://gw", api_key="k")
    with pytest.raises(GatewayError):
        gw.chat_content("adjudicator", [{"role": "user", "content": "x"}])


@respx.mock
def test_4xx_maps_to_non_retryable_client_error():
    respx.post("http://gw/v1/chat/completions").mock(return_value=httpx.Response(400, text="bad"))
    gw = Gateway(base_url="http://gw", api_key="k")
    with pytest.raises(GatewayClientError):
        gw.chat_content("adjudicator", [{"role": "user", "content": "x"}])


@respx.mock
def test_timeout_maps_to_gateway_error():
    respx.post("http://gw/v1/chat/completions").mock(side_effect=httpx.ConnectTimeout("t"))
    gw = Gateway(base_url="http://gw", api_key="k")
    with pytest.raises(GatewayError):
        gw.chat_content("adjudicator", [{"role": "user", "content": "x"}])


@respx.mock
def test_embed_returns_vectors():
    respx.post("http://gw/v1/embeddings").mock(
        return_value=httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]})
    )
    gw = Gateway(base_url="http://gw", api_key="k")
    assert gw.embed(["x"]) == [[0.1, 0.2]]
