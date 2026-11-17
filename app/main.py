"""API web sin estado del DIBM Assistant.

``create_app()`` recibe sus dependencias para que las pruebas inyecten las suyas.
``app`` es la aplicación real; se crea la primera vez que se pide (por ejemplo,
cuando ``uvicorn app.main:app`` la importa), así importar el módulo no lee el
snapshot. Lo que sí pasa al importar es validar la configuración y las reglas de
compliance: con ``API_KEYS`` mal formada o una regla de producción rota, el
producto no arranca.
"""

import os
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal, Mapping

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field, field_validator

from app.agent import Agent
from app.catalog import Catalog, load_catalog
from app.clock import Clock, SystemClock
from app.compliance import check_compliance
from app.config import ConfigError, Settings, load_settings
from app.costs import Prices, load_prices
from app.llm import LLM, ModelUnavailableError, create_llm
from app.observability import (
    REQUEST_ID_HEADER,
    JsonLogger,
    Metrics,
    resolve_request_id,
)
from app.router import choose_model
from app.security import API_KEY_HEADER, RateLimiter, authenticate
from app.tracing import Tracer

STATIC_DIR = Path(__file__).resolve().parent / "static"
INDEX_PAGE = STATIC_DIR / "index.html"
INVALID_KEY_DETAIL = "invalid or missing API key"
RATE_LIMIT_DETAIL = "rate limit exceeded"

LLMFactory = Callable[..., LLM]
ClientDependency = Callable[..., str]


class HistoryTurn(BaseModel):
    """Un turno previo de la conversación que manda el cliente.

    :param role: ``user`` o ``assistant``
    :type role: str
    :param content: Texto del turno
    :type content: str
    """

    role: Literal["user", "assistant"]
    content: str


class AskResponse(BaseModel):
    """Respuesta de ``POST /ask``.

    :param answer: Respuesta en español
    :type answer: str
    :param steps: Vueltas del bucle del agente
    :type steps: int
    :param tools_used: Herramientas usadas
    :type tools_used: list[str]
    :param input_tokens: Tokens de entrada
    :type input_tokens: int
    :param output_tokens: Tokens de salida
    :type output_tokens: int
    :param request_id: Id de la petición, para soporte
    :type request_id: str
    :param model: Modelo que eligió el enrutador
    :type model: str
    :param route: Motivo del enrutador
    :type route: str
    :param cached_calls: Llamadas servidas de la caché del gateway
    :type cached_calls: int
    :param cost_usd: Costo de la respuesta en USD
    :type cost_usd: float
    """

    answer: str
    steps: int
    tools_used: list[str]
    input_tokens: int
    output_tokens: int
    request_id: str
    model: str
    route: str
    cached_calls: int
    cost_usd: float


def _ask_request_model(max_question_chars: int) -> type[BaseModel]:
    """Crea el modelo del cuerpo de ``POST /ask`` con el largo configurado.

    :param max_question_chars: Largo máximo de la pregunta
    :type max_question_chars: int
    :return: La clase Pydantic del cuerpo
    :rtype: type[pydantic.BaseModel]
    """

    class AskRequest(BaseModel):
        """Cuerpo de ``POST /ask``: pregunta e historial opcional."""

        question: str = Field(min_length=1, max_length=max_question_chars)
        history: list[HistoryTurn] = Field(default_factory=list)

        @field_validator("question")
        @classmethod
        def question_not_blank(cls, value: str) -> str:
            """Rechaza preguntas de solo espacios.

            :param value: Pregunta recibida
            :type value: str
            :return: La pregunta
            :rtype: str
            :raises ValueError: Si está en blanco
            """
            if not value.strip():
                raise ValueError("question must not be blank")
            return value

    return AskRequest


def _default_llm_factory(settings: Settings, catalog: Catalog, model: str) -> LLM:
    """Crea el modelo configurado con el nombre que eligió el enrutador.

    :param settings: Configuración
    :type settings: Settings
    :param catalog: Catálogo del DIBM
    :type catalog: Catalog
    :param model: Nombre del modelo
    :type model: str
    :return: El modelo
    :rtype: LLM
    """
    return create_llm(settings, catalog.surnames(), model)


def _load_checked_prices(settings: Settings) -> Prices:
    """Carga los precios y exige que los dos modelos tengan precio.

    :param settings: Configuración (``prices_path`` y modelos)
    :type settings: Settings
    :return: Precios por modelo
    :rtype: dict
    :raises ConfigError: Si el archivo falla o falta el precio de un modelo
    """
    try:
        prices = load_prices(settings.prices_path)
    except ValueError as error:
        raise ConfigError(f"PRICES_PATH: {error}") from error
    for name, model in (
        ("MODEL_SMALL", settings.model_small),
        ("MODEL_LARGE", settings.model_large),
    ):
        if model not in prices:
            raise ConfigError(f"{name} has no price in {settings.prices_path}")
    return prices


def _install_model_errors(application: FastAPI, logger: JsonLogger) -> None:
    """Convierte la falla del modelo real en ``502`` con el id de la petición.

    :param application: Aplicación a la que se agrega el manejador
    :type application: fastapi.FastAPI
    :param logger: Logger JSON
    :type logger: JsonLogger
    """

    @application.exception_handler(ModelUnavailableError)
    async def model_unavailable(
        request: Request, error: ModelUnavailableError
    ) -> JSONResponse:
        """Responde ``502`` sin detalles internos.

        :param request: Petición que falló
        :type request: fastapi.Request
        :param error: Error del modelo
        :type error: ModelUnavailableError
        :return: ``{"detail": "model unavailable", "request_id": ...}``
        :rtype: JSONResponse
        """
        request_id = request.state.request_id
        logger.log("error", request_id, error_type=type(error).__name__)
        return JSONResponse(
            status_code=502,
            content={"detail": "model unavailable", "request_id": request_id},
        )


def _install_observability(
    application: FastAPI, logger: JsonLogger, metrics: Metrics, clock: Clock
) -> None:
    """Agrega el middleware de id por petición, log ``request`` y errores.

    Toda respuesta lleva ``X-Request-ID``. Un error inesperado se registra con
    su tipo (no su mensaje) y se responde ``500`` con el id para soporte.

    :param application: Aplicación a instrumentar
    :type application: fastapi.FastAPI
    :param logger: Logger JSON
    :type logger: JsonLogger
    :param metrics: Métricas del proceso
    :type metrics: Metrics
    :param clock: Reloj inyectado para medir la latencia
    :type clock: Clock
    """

    @application.middleware("http")
    async def observe(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Asigna el id, mide la latencia y registra la petición.

        :param request: Petición entrante
        :type request: fastapi.Request
        :param call_next: Resto de la aplicación
        :type call_next: Callable
        :return: La respuesta con ``X-Request-ID``
        :rtype: fastapi.Response
        """
        request_id = resolve_request_id(request.headers.get(REQUEST_ID_HEADER))
        request.state.request_id = request_id
        started = clock.monotonic()
        try:
            response = await call_next(request)
        except Exception as error:  # pylint: disable=broad-exception-caught
            logger.log("error", request_id, error_type=type(error).__name__)
            response = JSONResponse(
                status_code=500,
                content={"detail": "internal error", "request_id": request_id},
            )
        latency_ms = round((clock.monotonic() - started) * 1000, 3)
        response.headers[REQUEST_ID_HEADER] = request_id
        metrics.record_request(latency_ms, response.status_code)
        logger.log(
            "request",
            request_id,
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            latency_ms=latency_ms,
        )
        return response


def _client_dependency(settings: Settings, limiter: RateLimiter) -> ClientDependency:
    """Crea la dependencia que exige clave y aplica el límite por cliente.

    La clave recibida nunca entra al log, al error ni al estado de la petición:
    solo el nombre del cliente.

    :param settings: Configuración (``api_keys``)
    :type settings: Settings
    :param limiter: Límite de peticiones por cliente
    :type limiter: RateLimiter
    :return: Dependencia de FastAPI que devuelve el nombre del cliente
    :rtype: Callable
    """
    key_header = APIKeyHeader(name=API_KEY_HEADER, auto_error=False)

    def require_client(
        request: Request, provided: str | None = Depends(key_header)
    ) -> str:
        """Valida la clave y cuenta la petición del cliente.

        :param request: Petición, donde se guarda el nombre del cliente
        :type request: fastapi.Request
        :param provided: Valor del encabezado ``X-API-Key``
        :type provided: str | None
        :return: Nombre del cliente
        :rtype: str
        :raises HTTPException: ``401`` si la clave falta o es inválida;
            ``429`` con ``Retry-After`` si el cliente pasó su límite
        """
        client = authenticate(settings.api_keys, provided)
        if client is None:
            raise HTTPException(status_code=401, detail=INVALID_KEY_DETAIL)
        request.state.client = client
        retry_after = limiter.check(client)
        if retry_after:
            raise HTTPException(
                status_code=429,
                detail=RATE_LIMIT_DETAIL,
                headers={"Retry-After": str(retry_after)},
            )
        return client

    return require_client


def create_app(
    settings: Settings | None = None,
    catalog: Catalog | None = None,
    llm_factory: LLMFactory | None = None,
    clock: Clock | None = None,
) -> FastAPI:
    """Arma la aplicación FastAPI con sus dependencias.

    :param settings: Configuración; si falta se lee del entorno
    :type settings: Settings | None
    :param catalog: Catálogo; si falta se carga de ``publications_path``
    :type catalog: Catalog | None
    :param llm_factory: Crea el modelo con ``(settings, catalog, model)``
    :type llm_factory: Callable | None
    :param clock: Reloj para la hora del log y las latencias; si falta, el real
    :type clock: Clock | None
    :return: La aplicación
    :rtype: fastapi.FastAPI
    :raises ConfigError: Si la configuración, los precios o una regla de
        compliance de producción fallan
    :raises CatalogError: Si el snapshot no existe o está vacío
    """
    settings = settings or load_settings()
    check_compliance(settings)
    catalog = catalog if catalog is not None else load_catalog(
        settings.publications_path
    )
    prices = _load_checked_prices(settings)
    llm_factory = llm_factory or _default_llm_factory
    clock = clock or SystemClock()
    ask_request = _ask_request_model(settings.max_question_chars)
    logger = JsonLogger(settings.service_name, clock)
    metrics = Metrics(settings.slo_p95_ms)
    tracer = Tracer(settings)
    require_client = _client_dependency(
        settings, RateLimiter(settings.rate_limit_per_minute, clock)
    )
    application = FastAPI(title="DIBM Assistant")
    _install_observability(application, logger, metrics, clock)
    _install_model_errors(application, logger)

    @application.get("/", include_in_schema=False)
    def home() -> FileResponse:
        """Sirve la página web.

        :return: El archivo ``static/index.html``
        :rtype: FileResponse
        """
        return FileResponse(INDEX_PAGE, media_type="text/html")

    @application.get("/health")
    def health() -> dict[str, Any]:
        """Informa que el proceso está vivo y cuántos documentos cargó.

        :return: ``status``, ``pid`` y ``publications``
        :rtype: dict
        """
        return {"status": "ok", "pid": os.getpid(), "publications": len(catalog)}

    @application.get("/metrics", dependencies=[Depends(require_client)])
    def read_metrics() -> dict[str, Any]:
        """Devuelve las métricas de este proceso; exige ``X-API-Key``.

        :return: ``pid``, ``requests``, ``error_rate``, ``latency_ms``,
            ``tokens``, ``cost_usd`` y ``slo``
        :rtype: dict
        """
        return metrics.snapshot()

    @application.post("/ask", response_model=AskResponse)
    def ask(
        body: ask_request,  # type: ignore[valid-type]
        request: Request,
        client: str = Depends(require_client),
    ) -> AskResponse:
        """Responde una pregunta; el historial lo manda el cliente y no se guarda.

        Exige ``X-API-Key``. Registra ``audit`` por herramienta y ``agent_run``
        con el nombre del cliente, sin el texto de la pregunta ni de la
        respuesta y sin la clave.

        :param body: Pregunta e historial
        :type body: AskRequest
        :param request: Petición, de donde se toma su id
        :type request: fastapi.Request
        :param client: Nombre del cliente dueño de la clave
        :type client: str
        :return: Respuesta, pasos, herramientas, tokens, id, modelo y costo
        :rtype: AskResponse
        :raises ModelUnavailableError: Si el modelo real falla (se responde 502)
        """
        request_id = request.state.request_id

        def audit(tool: Any, args: Any) -> None:
            """Registra una llamada a herramienta.

            :param tool: Nombre de la herramienta
            :type tool: Any
            :param args: Argumentos pedidos por el modelo
            :type args: Any
            """
            logger.log(
                "audit",
                request_id,
                action="tool_call",
                tool=tool,
                args=args,
                client=client,
            )

        def wrap(func: Callable[..., Any], name: str, run_type: str) -> Callable:
            """Envuelve una función como traza con el id de la petición.

            :param func: Función a trazar
            :type func: Callable
            :param name: Nombre de la traza
            :type name: str
            :param run_type: Tipo de traza
            :type run_type: str
            :return: La función envuelta
            :rtype: Callable
            """
            return tracer.wrap(func, name, run_type, request_id, client=client)

        model, route = choose_model(body.question, settings)
        agent = Agent(
            llm_factory(settings, catalog, model),
            catalog,
            settings.agent_max_steps,
            audit=audit,
            wrap=wrap,
            history_window=settings.history_window,
            model=model,
            prices=prices,
        )
        history = [turn.model_dump() for turn in body.history]
        result = wrap(agent.run, "agent_run", "chain")(body.question, history)
        metrics.record_tokens(result.input_tokens, result.output_tokens)
        metrics.record_cost(result.cost_usd)
        logger.log(
            "agent_run",
            request_id,
            question_chars=len(body.question),
            history_messages=len(history),
            steps=result.steps,
            tools=result.tools_used,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            stopped=result.stopped,
            model=model,
            route=route,
            cached_calls=result.cached_calls,
            cost_usd=result.cost_usd,
            client=client,
        )
        return AskResponse(
            answer=result.answer,
            steps=result.steps,
            tools_used=result.tools_used,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            request_id=request_id,
            model=model,
            route=route,
            cached_calls=result.cached_calls,
            cost_usd=result.cost_usd,
        )

    return application


_APPLICATION: FastAPI | None = None


def validate_startup(env: Mapping[str, str] | None = None) -> Settings:
    """Valida la configuración y las reglas de compliance sin leer el snapshot.

    Se llama al importar el módulo: así el producto no arranca con ``API_KEYS``
    mal formada ni con una regla de producción rota.

    :param env: Variables de entorno; si es ``None`` se usa ``os.environ``
    :type env: Mapping[str, str] | None
    :return: La configuración validada
    :rtype: Settings
    :raises ConfigError: Si la configuración o una regla de compliance fallan
    """
    settings = load_settings(env)
    check_compliance(settings)
    return settings


validate_startup()


def __getattr__(name: str) -> FastAPI:
    """Crea ``app`` con las dependencias reales la primera vez que se pide.

    :param name: Atributo pedido al módulo
    :type name: str
    :return: La aplicación real
    :rtype: fastapi.FastAPI
    :raises AttributeError: Si se pide otro atributo
    """
    global _APPLICATION  # pylint: disable=global-statement
    if name != "app":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    if _APPLICATION is None:
        _APPLICATION = create_app()
    return _APPLICATION
