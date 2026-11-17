"""Configuración del DIBM Assistant leída de variables de entorno.

Un valor inválido detiene el arranque con un mensaje que nombra la variable.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

PRODUCT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_PUBLICATIONS_PATH = PRODUCT_DIR / "data" / "publications.json"
DEFAULT_PRICES_PATH = PRODUCT_DIR / "data" / "model_prices.json"
SUPPORTED_PROVIDERS = ("fake", "gateway")
GATEWAY_VARIABLES = ("CF_ACCOUNT_ID", "CF_GATEWAY_ID", "CF_API_TOKEN")
DEFAULT_SERVICE_NAME = "dibm-assistant"
DEFAULT_GATEWAY_ID = "default"
DEFAULT_MODEL_SMALL = "@cf/meta/llama-3.1-8b-instruct-fast"
DEFAULT_MODEL_LARGE = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
MAX_TEMPERATURE = 2.0
TRUE_VALUES = ("true", "1", "yes", "on")
FALSE_VALUES = ("false", "0", "no", "off")
SUPPORTED_ENVIRONMENTS = ("development", "production")
DEFAULT_ENVIRONMENT = "development"
DEFAULT_RATE_LIMIT_PER_MINUTE = 30


class ConfigError(ValueError):
    """Error de configuración que impide arrancar el producto."""


@dataclass(frozen=True)
class Settings:  # pylint: disable=too-many-instance-attributes
    """Configuración inmutable del producto.

    Agrupa todas las variables de entorno: por eso tiene muchos atributos.

    :param model_provider: Modelo a usar: ``fake`` o ``gateway``
    :type model_provider: str
    :param agent_max_steps: Tope de vueltas del bucle del agente
    :type agent_max_steps: int
    :param max_question_chars: Largo máximo de la pregunta
    :type max_question_chars: int
    :param publications_path: Ruta del snapshot del DIBM
    :type publications_path: pathlib.Path
    :param service_name: Valor del campo ``service`` del log
    :type service_name: str
    :param slo_p95_ms: Meta de latencia p95 en milisegundos
    :type slo_p95_ms: int
    :param langsmith_tracing: Si se piden trazas a LangSmith; solo se mandan
        si además existe ``LANGSMITH_API_KEY`` (la clave no se guarda aquí)
    :type langsmith_tracing: bool
    :param hide_inputs: No mandar entradas a LangSmith
    :type hide_inputs: bool
    :param hide_outputs: No mandar salidas a LangSmith
    :type hide_outputs: bool
    :param cf_account_id: Cuenta de Cloudflare
    :type cf_account_id: str
    :param cf_gateway_id: Gateway de Cloudflare AI Gateway
    :type cf_gateway_id: str
    :param cf_api_token: Token de Cloudflare (secreto: no sale en ``repr``)
    :type cf_api_token: str
    :param model_small: Modelo barato
    :type model_small: str
    :param model_large: Modelo capaz
    :type model_large: str
    :param routing: Si se elige el modelo por pregunta
    :type routing: bool
    :param router_max_chars: Preguntas más largas van al modelo capaz
    :type router_max_chars: int
    :param history_window: Mensajes de historial que se mandan al modelo
    :type history_window: int
    :param model_max_tokens: Tope de tokens de salida por llamada
    :type model_max_tokens: int
    :param model_temperature: Temperatura del modelo
    :type model_temperature: float
    :param cache_ttl_seconds: Caché del gateway en segundos (0: apagada)
    :type cache_ttl_seconds: int
    :param prices_path: Ruta de los precios por modelo
    :type prices_path: pathlib.Path
    :param environment: ``development`` o ``production``; con ``production``
        se aplican las reglas de compliance
    :type environment: str
    :param api_keys: Clave de cada cliente (secreto: no sale en ``repr``)
    :type api_keys: dict[str, str]
    :param rate_limit_per_minute: Peticiones por cliente por minuto
    :type rate_limit_per_minute: int
    """

    model_provider: str = "fake"
    agent_max_steps: int = 3
    max_question_chars: int = 2000
    publications_path: Path = DEFAULT_PUBLICATIONS_PATH
    service_name: str = DEFAULT_SERVICE_NAME
    slo_p95_ms: int = 2000
    langsmith_tracing: bool = False
    hide_inputs: bool = True
    hide_outputs: bool = True
    cf_account_id: str = ""
    cf_gateway_id: str = DEFAULT_GATEWAY_ID
    cf_api_token: str = field(default="", repr=False)
    model_small: str = DEFAULT_MODEL_SMALL
    model_large: str = DEFAULT_MODEL_LARGE
    routing: bool = True
    router_max_chars: int = 80
    history_window: int = 6
    model_max_tokens: int = 300
    model_temperature: float = 0.0
    cache_ttl_seconds: int = 0
    prices_path: Path = DEFAULT_PRICES_PATH
    environment: str = DEFAULT_ENVIRONMENT
    api_keys: dict[str, str] = field(default_factory=dict, repr=False)
    rate_limit_per_minute: int = DEFAULT_RATE_LIMIT_PER_MINUTE


def _environment(env: Mapping[str, str]) -> str:
    """Lee el ambiente en que corre el producto.

    :param env: Variables de entorno
    :type env: Mapping[str, str]
    :return: ``development`` o ``production``
    :rtype: str
    :raises ConfigError: Si el valor no es un ambiente conocido
    """
    value = (env.get("ENVIRONMENT") or DEFAULT_ENVIRONMENT).strip().lower()
    if value not in SUPPORTED_ENVIRONMENTS:
        allowed = ", ".join(SUPPORTED_ENVIRONMENTS)
        raise ConfigError(f"ENVIRONMENT must be one of: {allowed}")
    return value


def _api_keys(env: Mapping[str, str]) -> dict[str, str]:
    """Lee ``API_KEYS`` con la forma ``cliente:clave,cliente2:clave2``.

    Un error nombra la posición de la entrada que falla y su largo, nunca su
    valor: la entrada puede ser una clave completa.

    :param env: Variables de entorno
    :type env: Mapping[str, str]
    :return: Clave de cada cliente
    :rtype: dict[str, str]
    :raises ConfigError: Si una entrada no es ``cliente:clave`` o repite cliente
    """
    raw = (env.get("API_KEYS") or "").strip()
    if not raw:
        return {}
    keys: dict[str, str] = {}
    for position, item in enumerate(raw.split(","), start=1):
        entry = item.strip()
        client, separator, key = entry.partition(":")
        client, key = client.strip(), key.strip()
        if not separator or not client or not key:
            raise ConfigError(
                f"API_KEYS entry {position} must look like client:key "
                f"(entry length {len(entry)})"
            )
        if client in keys:
            raise ConfigError(f"API_KEYS entry {position} repeats a client name")
        keys[client] = key
    return keys


def _positive_int(env: Mapping[str, str], name: str, default: int) -> int:
    """Lee un entero positivo del entorno.

    :param env: Variables de entorno
    :type env: Mapping[str, str]
    :param name: Nombre de la variable
    :type name: str
    :param default: Valor por omisión
    :type default: int
    :return: El entero leído
    :rtype: int
    :raises ConfigError: Si el valor no es un entero mayor que cero
    """
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw.strip())
    except ValueError as error:
        raise ConfigError(f"{name} must be a positive integer") from error
    if value < 1:
        raise ConfigError(f"{name} must be a positive integer")
    return value


def _non_negative_int(env: Mapping[str, str], name: str, default: int) -> int:
    """Lee un entero mayor o igual a cero del entorno.

    :param env: Variables de entorno
    :type env: Mapping[str, str]
    :param name: Nombre de la variable
    :type name: str
    :param default: Valor por omisión
    :type default: int
    :return: El entero leído
    :rtype: int
    :raises ConfigError: Si el valor no es un entero mayor o igual a cero
    """
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw.strip())
    except ValueError as error:
        raise ConfigError(f"{name} must be a non-negative integer") from error
    if value < 0:
        raise ConfigError(f"{name} must be a non-negative integer")
    return value


def _temperature(env: Mapping[str, str], name: str, default: float) -> float:
    """Lee una temperatura entre 0 y ``MAX_TEMPERATURE``.

    :param env: Variables de entorno
    :type env: Mapping[str, str]
    :param name: Nombre de la variable
    :type name: str
    :param default: Valor por omisión
    :type default: float
    :return: La temperatura leída
    :rtype: float
    :raises ConfigError: Si el valor no es un número en el rango
    """
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw.strip())
    except ValueError as error:
        raise ConfigError(f"{name} must be a number") from error
    if not 0.0 <= value <= MAX_TEMPERATURE:
        raise ConfigError(f"{name} must be between 0 and {MAX_TEMPERATURE}")
    return value


def _text(env: Mapping[str, str], name: str, default: str) -> str:
    """Lee un texto sin espacios en los extremos.

    :param env: Variables de entorno
    :type env: Mapping[str, str]
    :param name: Nombre de la variable
    :type name: str
    :param default: Valor si falta o está vacío
    :type default: str
    :return: El texto leído
    :rtype: str
    """
    return (env.get(name) or "").strip() or default


def _path(env: Mapping[str, str], name: str, default: Path) -> Path:
    """Lee una ruta del entorno.

    :param env: Variables de entorno
    :type env: Mapping[str, str]
    :param name: Nombre de la variable
    :type name: str
    :param default: Ruta si falta o está vacía
    :type default: pathlib.Path
    :return: La ruta leída
    :rtype: pathlib.Path
    """
    raw = (env.get(name) or "").strip()
    return Path(raw) if raw else default


def _check_gateway(values: Mapping[str, str]) -> None:
    """Exige las tres variables ``CF_*`` para el modelo real.

    Se revisan los valores ya resueltos: ``CF_GATEWAY_ID`` tiene valor por
    omisión (``default``). El mensaje nombra la variable que falta, nunca un
    valor.

    :param values: Valor resuelto de cada variable ``CF_*``
    :type values: Mapping[str, str]
    :raises ConfigError: Si falta alguna variable ``CF_*``
    """
    missing = [name for name in GATEWAY_VARIABLES if not values.get(name)]
    if missing:
        names = ", ".join(missing)
        raise ConfigError(f"MODEL_PROVIDER=gateway requires {names}")


def _boolean(env: Mapping[str, str], name: str, default: bool) -> bool:
    """Lee un valor verdadero o falso del entorno.

    :param env: Variables de entorno
    :type env: Mapping[str, str]
    :param name: Nombre de la variable
    :type name: str
    :param default: Valor por omisión
    :type default: bool
    :return: El valor leído
    :rtype: bool
    :raises ConfigError: Si el valor no es ``true`` ni ``false``
    """
    raw = (env.get(name) or "").strip().lower()
    if raw == "":
        return default
    if raw in TRUE_VALUES:
        return True
    if raw in FALSE_VALUES:
        return False
    raise ConfigError(f"{name} must be true or false")


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Construye la configuración a partir del entorno.

    :param env: Variables de entorno; si es ``None`` se usa ``os.environ``
    :type env: Mapping[str, str] | None
    :return: La configuración validada
    :rtype: Settings
    :raises ConfigError: Si alguna variable tiene un valor inválido
    """
    env = os.environ if env is None else env
    provider = (env.get("MODEL_PROVIDER") or "fake").strip().lower()
    if provider not in SUPPORTED_PROVIDERS:
        allowed = ", ".join(SUPPORTED_PROVIDERS)
        raise ConfigError(f"MODEL_PROVIDER must be one of: {allowed}")
    gateway = {
        "CF_ACCOUNT_ID": _text(env, "CF_ACCOUNT_ID", ""),
        "CF_GATEWAY_ID": _text(env, "CF_GATEWAY_ID", DEFAULT_GATEWAY_ID),
        "CF_API_TOKEN": _text(env, "CF_API_TOKEN", ""),
    }
    if provider == "gateway":
        _check_gateway(gateway)
    return Settings(
        model_provider=provider,
        agent_max_steps=_positive_int(env, "AGENT_MAX_STEPS", 3),
        max_question_chars=_positive_int(env, "MAX_QUESTION_CHARS", 2000),
        publications_path=_path(env, "PUBLICATIONS_PATH", DEFAULT_PUBLICATIONS_PATH),
        service_name=_text(env, "SERVICE_NAME", DEFAULT_SERVICE_NAME),
        slo_p95_ms=_positive_int(env, "SLO_P95_MS", 2000),
        langsmith_tracing=_boolean(env, "LANGSMITH_TRACING", False),
        hide_inputs=_boolean(env, "HIDE_INPUTS", True),
        hide_outputs=_boolean(env, "HIDE_OUTPUTS", True),
        cf_account_id=gateway["CF_ACCOUNT_ID"],
        cf_gateway_id=gateway["CF_GATEWAY_ID"],
        cf_api_token=gateway["CF_API_TOKEN"],
        model_small=_text(env, "MODEL_SMALL", DEFAULT_MODEL_SMALL),
        model_large=_text(env, "MODEL_LARGE", DEFAULT_MODEL_LARGE),
        routing=_boolean(env, "ROUTING", True),
        router_max_chars=_positive_int(env, "ROUTER_MAX_CHARS", 80),
        history_window=_non_negative_int(env, "HISTORY_WINDOW", 6),
        model_max_tokens=_positive_int(env, "MODEL_MAX_TOKENS", 300),
        model_temperature=_temperature(env, "MODEL_TEMPERATURE", 0.0),
        cache_ttl_seconds=_non_negative_int(env, "CACHE_TTL_SECONDS", 0),
        prices_path=_path(env, "PRICES_PATH", DEFAULT_PRICES_PATH),
        environment=_environment(env),
        api_keys=_api_keys(env),
        rate_limit_per_minute=_positive_int(
            env, "RATE_LIMIT_PER_MINUTE", DEFAULT_RATE_LIMIT_PER_MINUTE
        ),
    )
