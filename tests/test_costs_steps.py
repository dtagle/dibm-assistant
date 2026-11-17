"""Pasos de los escenarios de ``features/costs.feature`` contra la API."""

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from app.config import ConfigError, load_settings
from app.llm import ModelUnavailableError
from tests.conftest import LARGE_MODEL, SMALL_MODEL, expected_cost

scenarios("features/costs.feature")

MODELS = {"small": SMALL_MODEL, "large": LARGE_MODEL}


class UnavailableLLM:
    """Modelo real que no responde (por ejemplo, el gateway está caído)."""

    def complete(self, messages):
        """Lanza el error de modelo no disponible.

        :param messages: Conversación (no se usa)
        :type messages: list[dict]
        :raises ModelUnavailableError: Siempre
        """
        raise ModelUnavailableError(f"gateway down ({len(messages)} messages)")


@pytest.fixture
def context():
    """Estado de un escenario: entorno, fábrica de modelos, cliente y respuestas."""
    return {"env": {}, "llm_factory": None, "api": None, "answers": []}


def _api(context, make_cost_client):
    """Crea la API la primera vez que un paso la usa y luego la reutiliza.

    :param context: Estado del escenario
    :type context: dict
    :param make_cost_client: Fábrica de clientes con precios de prueba
    :type make_cost_client: callable
    :return: El cliente de la API
    :rtype: fastapi.testclient.TestClient
    """
    if context["api"] is None:
        context["api"] = make_cost_client(
            llm_factory=context["llm_factory"], **context["env"]
        )
    return context["api"]


@given("the priced assistant is running")
def priced_assistant(context):
    """La API con los modelos simulados y la configuración por omisión."""
    assert context["api"] is None


@given(
    parsers.parse('the priced assistant is running with "{name}" set to "{value}"')
)
def priced_assistant_with_setting(context, name, value):
    """La API con una variable de entorno cambiada."""
    context["env"][name] = value


@given("the priced assistant is running with a model that is unavailable")
def priced_assistant_with_unavailable_model(context):
    """La API con un modelo que siempre falla como el gateway caído."""
    context["llm_factory"] = lambda settings, catalog, model: UnavailableLLM()


@when(parsers.parse('I ask the priced assistant "{question}"'))
def ask_priced(context, make_cost_client, question):
    """Manda la pregunta y guarda la respuesta."""
    response = _api(context, make_cost_client).post(
        "/ask", json={"question": question}
    )
    assert response.status_code == 200
    context["answers"].append(response.json())


@when(
    parsers.parse(
        'I send request "{request_id}" to the priced assistant asking "{question}"'
    ),
    target_fixture="response",
)
def ask_priced_with_request_id(context, make_cost_client, request_id, question):
    """Manda la pregunta con el id de petición del cliente."""
    return _api(context, make_cost_client).post(
        "/ask", json={"question": question}, headers={"X-Request-ID": request_id}
    )


@when(
    parsers.parse('I load the settings for the gateway provider without "{name}"'),
    target_fixture="startup_error",
)
def load_gateway_settings_without(name):
    """Intenta cargar la configuración de ``gateway`` sin una variable ``CF_*``."""
    env = {
        "MODEL_PROVIDER": "gateway",
        "CF_ACCOUNT_ID": "account-123",
        "CF_GATEWAY_ID": "dibm",
        "CF_API_TOKEN": "token-secret-value",
    }
    del env[name]
    with pytest.raises(ConfigError) as error:
        load_settings(env)
    return error.value


@then(parsers.parse('the answer used the {size} model because of "{route}"'))
def answer_used_model(context, size, route):
    """Comprueba el modelo y el motivo del enrutador de la última respuesta."""
    answer = context["answers"][-1]
    assert answer["model"] == MODELS[size]
    assert answer["route"] == route


@then(parsers.parse("the cost matches the tokens of the {size} model"))
def cost_matches_tokens(context, size):
    """El costo sale de los tokens y del precio del modelo usado."""
    answer = context["answers"][-1]
    cost = expected_cost(MODELS[size], answer["input_tokens"], answer["output_tokens"])
    assert answer["cost_usd"] > 0
    assert answer["cost_usd"] == pytest.approx(cost)


@then("no call was cached")
def no_call_was_cached(context):
    """Sin caché del gateway ninguna llamada cuenta como cacheada."""
    assert context["answers"][-1]["cached_calls"] == 0


@then("the metrics cost is the sum of both answers")
def metrics_cost_is_sum(context, make_cost_client):
    """``/metrics`` acumula el costo de las respuestas."""
    metrics = _api(context, make_cost_client).get("/metrics").json()
    total = sum(answer["cost_usd"] for answer in context["answers"])
    assert metrics["cost_usd"] == pytest.approx(total)


@then(parsers.parse('the response is model unavailable for request "{request_id}"'))
def response_is_model_unavailable(response, request_id):
    """El cuerpo dice que el modelo no está disponible, sin detalles internos."""
    assert response.status_code == 502
    assert response.json() == {"detail": "model unavailable", "request_id": request_id}


@then(parsers.parse('startup fails naming "{name}"'))
def startup_fails_naming(startup_error, name):
    """El mensaje nombra la variable que falta y no muestra el token."""
    assert name in str(startup_error)
    assert "token-secret-value" not in str(startup_error)
