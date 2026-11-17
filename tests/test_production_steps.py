"""Pasos de los escenarios de ``features/production.feature`` (spec 04)."""

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from app.config import ConfigError, load_settings
from app.llm import FakeLLM
from app.main import create_app
from tests.conftest import TEST_API_KEY, TEST_API_KEYS

scenarios("features/production.feature")

SECOND_CLIENT_KEY = "second-key-abcdefghijklmnop"
SAFE_PRODUCTION_KEY = "dibm-portal-key-0123456789abcdef"


@pytest.fixture
def context():
    """Estado de un escenario: entorno, cliente y respuestas."""
    return {"env": {}, "api": None, "responses": [], "started": None}


def _api(context, make_secure_client):
    """Crea la API sin clave por omisión la primera vez y luego la reutiliza.

    :param context: Estado del escenario
    :type context: dict
    :param make_secure_client: Fábrica de clientes sin clave por omisión
    :type make_secure_client: callable
    :return: El cliente de la API
    :rtype: fastapi.testclient.TestClient
    """
    if context["api"] is None:
        context["api"] = make_secure_client(**context["env"])
    return context["api"]


def _ask(context, make_secure_client, question, key):
    """Manda una pregunta con la clave indicada y guarda la respuesta.

    :param context: Estado del escenario
    :type context: dict
    :param make_secure_client: Fábrica de clientes
    :type make_secure_client: callable
    :param question: Pregunta
    :type question: str
    :param key: Clave a mandar; ``None`` no manda el encabezado
    :type key: str | None
    :return: La respuesta
    :rtype: httpx.Response
    """
    headers = {"X-API-Key": key} if key is not None else {}
    response = _api(context, make_secure_client).post(
        "/ask", json={"question": question}, headers=headers
    )
    context["responses"].append(response)
    return response


@given("the secured assistant is running")
def secured_assistant(context):
    """La API con una clave de prueba y el límite por omisión."""
    assert context["api"] is None


@given(
    parsers.parse(
        "the secured assistant is running "
        "with a limit of {limit:d} requests per minute"
    )
)
def secured_assistant_with_limit(context, limit):
    """La API con el límite de peticiones indicado."""
    context["env"]["RATE_LIMIT_PER_MINUTE"] = str(limit)


@given(
    parsers.parse(
        "the secured assistant is running with two clients "
        "and a limit of {limit:d} requests per minute"
    )
)
def secured_assistant_with_two_clients(context, limit):
    """La API con dos clientes, cada uno con su clave."""
    context["env"]["API_KEYS"] = f"{TEST_API_KEYS},second-client:{SECOND_CLIENT_KEY}"
    context["env"]["RATE_LIMIT_PER_MINUTE"] = str(limit)


@when(
    parsers.parse('I ask "{question}" without an API key'), target_fixture="response"
)
def ask_without_key(context, make_secure_client, question):
    """Pregunta sin encabezado ``X-API-Key``."""
    return _ask(context, make_secure_client, question, None)


@when(
    parsers.parse('I ask "{question}" with the API key "{key}"'),
    target_fixture="response",
)
def ask_with_key(context, make_secure_client, question, key):
    """Pregunta con una clave dada."""
    return _ask(context, make_secure_client, question, key)


@when(
    parsers.parse('I ask "{question}" with the valid API key'),
    target_fixture="response",
)
def ask_with_valid_key(context, make_secure_client, question):
    """Pregunta con la clave de prueba."""
    return _ask(context, make_secure_client, question, TEST_API_KEY)


@when(parsers.parse('I ask "{question}" {times:d} times with the valid API key'))
def ask_several_times(context, make_secure_client, question, times):
    """Pregunta varias veces con la clave de prueba."""
    for _ in range(times):
        _ask(context, make_secure_client, question, TEST_API_KEY)


@when(parsers.parse('the first client asks "{question}"'))
def first_client_asks(context, make_secure_client, question):
    """El primer cliente pregunta con su clave."""
    _ask(context, make_secure_client, question, TEST_API_KEY)


@when(parsers.parse('the second client asks "{question}"'))
def second_client_asks(context, make_secure_client, question):
    """El segundo cliente pregunta con su clave."""
    _ask(context, make_secure_client, question, SECOND_CLIENT_KEY)


@when(parsers.parse("{seconds:d} seconds pass"))
def seconds_pass(ticking_clock, seconds):
    """Hace avanzar el reloj inyectado."""
    ticking_clock.advance(seconds)


@when(parsers.parse('I read "{path}" without an API key'), target_fixture="response")
def read_without_key(context, make_secure_client, path):
    """Pide una ruta con ``GET`` sin clave."""
    return _api(context, make_secure_client).get(path)


@then(parsers.parse("the response status is {status:d}"))
def response_status_is(response, status):
    """Comprueba el código HTTP."""
    assert response.status_code == status


@then(parsers.parse('the response detail is "{detail}"'))
def response_detail_is(response, detail):
    """Comprueba el cuerpo del error."""
    assert response.json() == {"detail": detail}


@then(parsers.parse("the last response status is {status:d}"))
def last_response_status_is(context, status):
    """Comprueba el código HTTP de la última pregunta."""
    assert context["responses"][-1].status_code == status


@then(parsers.parse('the last response detail is "{detail}"'))
def last_response_detail_is(context, detail):
    """Comprueba el cuerpo de error de la última pregunta."""
    assert context["responses"][-1].json() == {"detail": detail}


@then(parsers.parse("the last response asks to retry after {seconds:d} seconds"))
def last_response_retry_after(context, seconds):
    """Comprueba el encabezado ``Retry-After``."""
    assert context["responses"][-1].headers["Retry-After"] == str(seconds)


@given("a production configuration that is otherwise safe")
def safe_production_configuration(context, snapshot_path, prices_path, monkeypatch):
    """Variables de producción que cumplen todas las reglas de compliance."""
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("LANGCHAIN_API_KEY", raising=False)
    context["env"] = {
        "ENVIRONMENT": "production",
        "MODEL_PROVIDER": "gateway",
        "CF_ACCOUNT_ID": "account-for-tests",
        "CF_API_TOKEN": "token-for-tests",
        "API_KEYS": f"dibm-portal:{SAFE_PRODUCTION_KEY}",
        "LANGSMITH_TRACING": "true",
        "HIDE_INPUTS": "true",
        "HIDE_OUTPUTS": "true",
        "PUBLICATIONS_PATH": str(snapshot_path),
        "PRICES_PATH": str(prices_path),
    }


@given(parsers.re(r'"(?P<variable>[A-Z_]+)" is set to "(?P<value>[^"]*)"'))
def variable_is_set(context, variable, value):
    """Cambia una variable de la configuración de producción."""
    context["env"][variable] = value


@when("the assistant starts")
def assistant_starts(context, catalog):
    """Lee la configuración y arma la aplicación, como al arrancar."""
    try:
        settings = load_settings(context["env"])
        create_app(
            settings=settings,
            catalog=catalog,
            llm_factory=lambda *_args, **_kwargs: FakeLLM(catalog.surnames()),
        )
    except ConfigError as error:
        context["started"] = error
    else:
        context["started"] = True


@then("it refuses to start")
def it_refuses_to_start(context):
    """El arranque falla con un error de configuración sin la clave."""
    assert isinstance(context["started"], ConfigError)
    assert SAFE_PRODUCTION_KEY not in str(context["started"])


@then("it starts")
def it_starts(context):
    """El arranque termina sin error."""
    assert context["started"] is True
