"""Interfaz del modelo, modelo simulado determinista y modelo real.

El agente solo conoce ``complete(messages)``: cambiar de modelo no toca el agente.
El modelo real llama a Cloudflare Workers AI a través de AI Gateway con
``httpx``; el transporte se inyecta para que las pruebas no usen la red.
"""

import json
import re
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.catalog import normalize, words
from app.config import Settings

TOOL_RESULT_PREFIX = "Resultado de la herramienta: "
GATEWAY_URL = (
    "https://gateway.ai.cloudflare.com/v1/{account_id}/{gateway_id}"
    "/workers-ai/v1/chat/completions"
)
CACHE_TTL_HEADER = "cf-aig-cache-ttl"
CACHE_STATUS_HEADER = "cf-aig-cache-status"
CACHE_HIT = "HIT"
GATEWAY_TIMEOUT_SECONDS = 30.0
HELP_ANSWER = "Pregúntame por un autor o por las últimas publicaciones del DIBM."

_ID_PATTERN = re.compile(r"(?<!\d)(\d{4}-\d{2})(?!\d)( T\d+\b)?")
_YEAR_PATTERN = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
_LATEST_MARKERS = ("ultimas", "ultimo", "recientes", "mas nuevas")
_TOPIC_PATTERN = re.compile(r"\b(?:sobre|acerca de|tema)\b(.*)", re.IGNORECASE)
_TOPIC_STRIP = " \t\n¿?¡!.,;:\"'«»"


@dataclass(frozen=True)
class Completion:
    """Respuesta de un modelo.

    :param text: Texto devuelto (un objeto JSON según el protocolo)
    :type text: str
    :param input_tokens: Tokens de entrada
    :type input_tokens: int
    :param output_tokens: Tokens de salida
    :type output_tokens: int
    :param cached: Si la respuesta vino de caché
    :type cached: bool
    """

    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached: bool = False


class ModelUnavailableError(RuntimeError):
    """El modelo real no respondió o respondió con error.

    El mensaje nunca incluye el token ni el cuerpo de la respuesta.
    """


class LLM(Protocol):
    """Interfaz de cualquier modelo que use el agente."""

    def complete(self, messages: list[dict]) -> Completion:
        """Completa una conversación.

        :param messages: Mensajes con ``role`` y ``content``
        :type messages: list[dict]
        :return: La respuesta del modelo
        :rtype: Completion
        """


def count_words(text: str) -> int:
    """Cuenta palabras separadas por espacios.

    :param text: Texto a contar
    :type text: str
    :return: Número de palabras
    :rtype: int
    """
    return len(str(text).split())


class FakeLLM:
    """Modelo simulado: decide con reglas sobre el último mensaje, sin red.

    Puede llevar el nombre de un modelo real (``MODEL_SMALL`` o ``MODEL_LARGE``)
    para que su costo se calcule con ese precio; todos responden igual.

    :param surnames: Apellidos de los autores del catálogo (inyectados)
    :type surnames: list[str]
    :param model: Nombre del modelo que simula
    :type model: str
    """

    def __init__(self, surnames: list[str], model: str = "fake"):
        """Crea el modelo con la lista de apellidos conocidos.

        :param surnames: Apellidos de los autores
        :type surnames: list[str]
        :param model: Nombre del modelo que simula
        :type model: str
        """
        self.model = model
        self._surnames: dict[str, str] = {}
        for surname in surnames:
            key = normalize(surname).strip()
            if key and key not in self._surnames:
                self._surnames[key] = surname

    def complete(self, messages: list[dict]) -> Completion:
        """Decide la siguiente acción según el último mensaje.

        :param messages: Conversación con ``role`` y ``content``
        :type messages: list[dict]
        :return: Un objeto JSON con ``tool`` y ``args`` o con ``answer``
        :rtype: Completion
        """
        last = str(messages[-1].get("content", "")) if messages else ""
        text = json.dumps(self._decide(last), ensure_ascii=False)
        input_tokens = sum(count_words(m.get("content", "")) for m in messages)
        return Completion(
            text=text, input_tokens=input_tokens, output_tokens=count_words(text)
        )

    def _decide(self, message: str) -> dict:
        """Aplica las reglas de la especificación en orden.

        :param message: Último mensaje de la conversación
        :type message: str
        :return: La decisión del modelo
        :rtype: dict
        """
        if message.startswith(TOOL_RESULT_PREFIX):
            result = message[len(TOOL_RESULT_PREFIX):]
            return {"answer": f"Según el DIBM de Banxico: {result}"}
        id_match = _ID_PATTERN.search(message)
        if id_match:
            publication_id = id_match.group(1) + (id_match.group(2) or "")
            return _tool("get_publication", publication_id=publication_id)
        latest = _latest_request(message)
        if latest is not None:
            return latest
        return self._author_or_topic(message)

    def _author_or_topic(self, message: str) -> dict:
        """Aplica las reglas 4 a 6: autor, tema o mensaje de ayuda.

        :param message: Último mensaje de la conversación
        :type message: str
        :return: La decisión del modelo
        :rtype: dict
        """
        for word in words(message):
            if word in self._surnames:
                return _tool("search_by_author", author=self._surnames[word])
        topic_match = _TOPIC_PATTERN.search(message)
        if topic_match:
            query = topic_match.group(1).strip(_TOPIC_STRIP) or message
            return _tool("search_publications", query=query)
        return {"answer": HELP_ANSWER}


def _latest_request(message: str) -> dict | None:
    """Aplica la regla 3: pide las últimas publicaciones, con año si lo hay.

    :param message: Último mensaje de la conversación
    :type message: str
    :return: La petición de ``latest_publications`` o ``None`` si no aplica
    :rtype: dict | None
    """
    year_match = _YEAR_PATTERN.search(message)
    if year_match:
        return _tool("latest_publications", year=int(year_match.group(1)))
    normalized = normalize(message)
    if any(marker in normalized for marker in _LATEST_MARKERS):
        return _tool("latest_publications")
    return None


def _tool(name: str, **args) -> dict:
    """Arma la petición de una herramienta.

    :param name: Nombre de la herramienta
    :type name: str
    :return: Objeto ``{"tool": name, "args": args}``
    :rtype: dict
    """
    return {"tool": name, "args": args}


class GatewayLLM:  # pylint: disable=too-few-public-methods
    """Modelo real: Cloudflare Workers AI a través de AI Gateway.

    :param account_id: Cuenta de Cloudflare
    :type account_id: str
    :param gateway_id: Id del gateway
    :type gateway_id: str
    :param api_token: Token de Cloudflare (secreto)
    :type api_token: str
    :param model: Nombre del modelo
    :type model: str
    :param max_tokens: Tope de tokens de salida
    :type max_tokens: int
    :param temperature: Temperatura
    :type temperature: float
    :param cache_ttl_seconds: Caché del gateway en segundos (0: apagada)
    :type cache_ttl_seconds: int
    :param transport: Transporte httpx; las pruebas inyectan uno simulado
    :type transport: httpx.BaseTransport | None
    """

    def __init__(  # pylint: disable=too-many-arguments
        self,
        *,
        account_id: str,
        gateway_id: str,
        api_token: str,
        model: str,
        max_tokens: int,
        temperature: float,
        cache_ttl_seconds: int = 0,
        transport: httpx.BaseTransport | None = None,
    ):
        """Guarda la configuración de la llamada.

        :param account_id: Cuenta de Cloudflare
        :type account_id: str
        :param gateway_id: Id del gateway
        :type gateway_id: str
        :param api_token: Token de Cloudflare
        :type api_token: str
        :param model: Nombre del modelo
        :type model: str
        :param max_tokens: Tope de tokens de salida
        :type max_tokens: int
        :param temperature: Temperatura
        :type temperature: float
        :param cache_ttl_seconds: Segundos de caché del gateway
        :type cache_ttl_seconds: int
        :param transport: Transporte httpx inyectado
        :type transport: httpx.BaseTransport | None
        """
        self.model = model
        self._url = GATEWAY_URL.format(account_id=account_id, gateway_id=gateway_id)
        self._headers = {"Authorization": f"Bearer {api_token}"}
        if cache_ttl_seconds > 0:
            self._headers[CACHE_TTL_HEADER] = str(cache_ttl_seconds)
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._transport = transport

    def complete(self, messages: list[dict]) -> Completion:
        """Manda la conversación al gateway y lee la respuesta.

        :param messages: Mensajes con ``role`` y ``content``
        :type messages: list[dict]
        :return: Texto, tokens de ``usage`` y si vino de caché
        :rtype: Completion
        :raises ModelUnavailableError: Si hay error de red, HTTP o de formato
        """
        body = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
        }
        try:
            with httpx.Client(
                transport=self._transport, timeout=GATEWAY_TIMEOUT_SECONDS
            ) as client:
                response = client.post(self._url, json=body, headers=self._headers)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            raise ModelUnavailableError(f"gateway returned HTTP {status}") from None
        except httpx.HTTPError as error:
            name = type(error).__name__
            raise ModelUnavailableError(f"gateway request failed: {name}") from None
        except ValueError:
            raise ModelUnavailableError("gateway returned invalid JSON") from None
        cached = response.headers.get(CACHE_STATUS_HEADER, "").upper() == CACHE_HIT
        return _parse_gateway_body(data, cached)


def _parse_gateway_body(data: Any, cached: bool) -> Completion:
    """Extrae texto y tokens de una respuesta compatible con OpenAI.

    :param data: Cuerpo JSON de la respuesta
    :type data: Any
    :param cached: Si el gateway la sirvió de caché
    :type cached: bool
    :return: La respuesta del modelo
    :rtype: Completion
    :raises ModelUnavailableError: Si no trae ``choices[0].message.content``
    """
    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise ModelUnavailableError("gateway response has no message") from None
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    return Completion(
        text=str(text or ""),
        input_tokens=_token_count(usage.get("prompt_tokens")),
        output_tokens=_token_count(usage.get("completion_tokens")),
        cached=cached,
    )


def _token_count(value: Any) -> int:
    """Convierte un conteo de tokens a entero no negativo.

    :param value: Valor de ``usage``
    :type value: Any
    :return: El conteo, o 0 si falta o no es válido
    :rtype: int
    """
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


def create_llm(
    settings: Settings,
    surnames: list[str],
    model: str,
    transport: httpx.BaseTransport | None = None,
) -> LLM:
    """Crea el modelo configurado con el nombre que eligió el enrutador.

    :param settings: Configuración
    :type settings: Settings
    :param surnames: Apellidos del catálogo para el modelo simulado
    :type surnames: list[str]
    :param model: Nombre del modelo
    :type model: str
    :param transport: Transporte httpx para el modelo real
    :type transport: httpx.BaseTransport | None
    :return: El modelo
    :rtype: LLM
    :raises ValueError: Si el proveedor no existe
    """
    if settings.model_provider == "fake":
        return FakeLLM(surnames, model)
    if settings.model_provider == "gateway":
        return GatewayLLM(
            account_id=settings.cf_account_id,
            gateway_id=settings.cf_gateway_id,
            api_token=settings.cf_api_token,
            model=model,
            max_tokens=settings.model_max_tokens,
            temperature=settings.model_temperature,
            cache_ttl_seconds=settings.cache_ttl_seconds,
            transport=transport,
        )
    raise ValueError(f"Unsupported model provider: {settings.model_provider}")
