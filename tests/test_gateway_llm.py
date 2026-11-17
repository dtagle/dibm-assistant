"""Pruebas del modelo real (Cloudflare AI Gateway) sin red, con httpx.MockTransport."""

import json

import httpx
import pytest

from app.llm import GatewayLLM, ModelUnavailableError
from tests.conftest import SMALL_MODEL

GATEWAY_URL = (
    "https://gateway.ai.cloudflare.com/v1/account-123/dibm"
    "/workers-ai/v1/chat/completions"
)
MESSAGES = [
    {"role": "system", "content": "Eres el DIBM Assistant."},
    {"role": "user", "content": "Hola"},
]


def make_gateway(handler, cache_ttl_seconds=0):
    """Crea el modelo real con un transporte simulado.

    :param handler: Recibe la petición httpx y devuelve la respuesta
    :type handler: callable
    :param cache_ttl_seconds: Segundos de caché del gateway (0: apagada)
    :type cache_ttl_seconds: int
    :return: El modelo
    :rtype: GatewayLLM
    """
    return GatewayLLM(
        account_id="account-123",
        gateway_id="dibm",
        api_token="token-secret-value",
        model=SMALL_MODEL,
        max_tokens=300,
        temperature=0.0,
        cache_ttl_seconds=cache_ttl_seconds,
        transport=httpx.MockTransport(handler),
    )


def reply(text, headers=None, usage=True):
    """Arma una respuesta con la forma de la API compatible con OpenAI.

    :param text: Contenido del mensaje del modelo
    :type text: str
    :param headers: Encabezados extra del gateway
    :type headers: dict | None
    :param usage: Si la respuesta trae ``usage``
    :type usage: bool
    :return: La respuesta httpx
    :rtype: httpx.Response
    """
    body = {"choices": [{"message": {"role": "assistant", "content": text}}]}
    if usage:
        body["usage"] = {"prompt_tokens": 42, "completion_tokens": 7}
    return httpx.Response(200, json=body, headers=headers or {})


def test_gateway_posts_model_messages_and_limits_with_the_token():
    """URL del gateway, ``Authorization`` y cuerpo con las cuatro claves."""
    seen = []

    def handler(request):
        seen.append(request)
        return reply('{"answer": "Hola"}')

    completion = make_gateway(handler).complete(MESSAGES)
    request = seen[0]
    assert str(request.url) == GATEWAY_URL
    assert request.headers["Authorization"] == "Bearer token-secret-value"
    assert json.loads(request.content) == {
        "model": SMALL_MODEL,
        "messages": MESSAGES,
        "max_tokens": 300,
        "temperature": 0.0,
    }
    assert completion.text == '{"answer": "Hola"}'


def test_gateway_reads_tokens_from_usage_and_tolerates_missing_usage():
    """Los tokens salen de ``usage``; si no viene, cuentan cero."""
    with_usage = make_gateway(lambda request: reply("Hola")).complete(MESSAGES)
    assert (with_usage.input_tokens, with_usage.output_tokens) == (42, 7)
    without = make_gateway(lambda request: reply("Hola", usage=False)).complete(
        MESSAGES
    )
    assert (without.input_tokens, without.output_tokens) == (0, 0)


def test_cache_ttl_header_is_sent_only_when_the_cache_is_on():
    """Con ``CACHE_TTL_SECONDS`` en 0 no se manda ``cf-aig-cache-ttl``."""
    seen = []

    def handler(request):
        seen.append(request)
        return reply("Hola")

    make_gateway(handler, cache_ttl_seconds=0).complete(MESSAGES)
    make_gateway(handler, cache_ttl_seconds=3600).complete(MESSAGES)
    assert "cf-aig-cache-ttl" not in seen[0].headers
    assert seen[1].headers["cf-aig-cache-ttl"] == "3600"


def test_cache_hit_marks_the_call_as_cached():
    """``cf-aig-cache-status: HIT`` hace que la llamada cuente como cacheada."""
    hit = make_gateway(
        lambda request: reply("Hola", headers={"cf-aig-cache-status": "HIT"}),
        cache_ttl_seconds=60,
    ).complete(MESSAGES)
    miss = make_gateway(
        lambda request: reply("Hola", headers={"cf-aig-cache-status": "MISS"}),
        cache_ttl_seconds=60,
    ).complete(MESSAGES)
    assert hit.cached is True
    assert miss.cached is False


def test_gateway_failure_is_reported_as_model_unavailable_without_the_token():
    """Un error HTTP o de red se convierte en ``ModelUnavailableError``."""

    def server_error(_request):
        return httpx.Response(503, json={"error": "overloaded"})

    def network_error(request):
        raise httpx.ConnectError("connection refused", request=request)

    for handler in (server_error, network_error):
        with pytest.raises(ModelUnavailableError) as error:
            make_gateway(handler).complete(MESSAGES)
        assert "token-secret-value" not in str(error.value)
