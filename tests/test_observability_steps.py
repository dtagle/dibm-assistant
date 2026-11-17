"""Pasos de los escenarios de ``features/observability.feature`` contra la API."""

import uuid

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from tests.conftest import FailingLLM

scenarios("features/observability.feature")


@pytest.fixture
def context():
    """Estado de un escenario: opciones de la API, cliente y respuestas."""
    return {"env": {}, "seconds": 0.0, "llm": None, "api": None, "answers": []}


def _api(context, make_observed_client):
    """Crea la API la primera vez que un paso la usa y luego la reutiliza.

    :param context: Estado del escenario
    :type context: dict
    :param make_observed_client: Fábrica de clientes con reloj fijo
    :type make_observed_client: callable
    :return: El cliente de la API
    :rtype: fastapi.testclient.TestClient
    """
    if context["api"] is None:
        context["api"] = make_observed_client(
            llm=context["llm"],
            seconds_per_call=context["seconds"],
            **context["env"],
        )
    return context["api"]


@given("the observed assistant is running")
def observed_assistant(context):
    """La API con reloj fijo y configuración por omisión."""
    assert context["api"] is None


@given(
    parsers.parse("the observed assistant is running with an SLO of {target:d} ms")
)
def observed_assistant_with_slo(context, target):
    """La API con la meta de latencia p95 indicada."""
    context["env"]["SLO_P95_MS"] = str(target)


@given(parsers.parse("each model call takes {seconds:f} seconds"))
def each_model_call_takes(context, seconds):
    """Cada llamada al modelo hace avanzar el reloj fijo."""
    context["seconds"] = seconds


@given("the observed assistant is running with a model that fails")
def observed_assistant_with_failing_model(context):
    """La API con un modelo que siempre lanza un error inesperado."""
    context["llm"] = FailingLLM()


@when("I check the health of the assistant", target_fixture="response")
def check_health(context, make_observed_client):
    """Pide ``GET /health`` sin encabezado ``X-Request-ID``."""
    return _api(context, make_observed_client).get("/health")


@when(
    parsers.parse('I ask "{question}" with request id "{request_id}"'),
    target_fixture="response",
)
def ask_with_request_id(context, make_observed_client, question, request_id):
    """Manda la pregunta con el id de petición del cliente."""
    return _api(context, make_observed_client).post(
        "/ask", json={"question": question}, headers={"X-Request-ID": request_id}
    )


@when(parsers.parse('I ask "{question}" {times:d} times'))
def ask_several_times(context, make_observed_client, question, times):
    """Manda la misma pregunta varias veces y guarda las respuestas."""
    api = _api(context, make_observed_client)
    for _ in range(times):
        response = api.post("/ask", json={"question": question})
        assert response.status_code == 200
        context["answers"].append(response.json())


@when("I read the metrics", target_fixture="metrics")
def read_metrics(context, make_observed_client):
    """Pide ``GET /metrics``."""
    response = _api(context, make_observed_client).get("/metrics")
    assert response.status_code == 200
    return response.json()


@then("the response carries a generated request id")
def response_carries_generated_request_id(response):
    """El encabezado trae un UUID válido."""
    assert uuid.UUID(response.headers["X-Request-ID"])


@then(parsers.parse('the response header "{header}" is "{value}"'))
def response_header_is(response, header, value):
    """Comprueba el valor de un encabezado."""
    assert response.headers[header] == value


@then(parsers.parse('the response body request id is "{request_id}"'))
def response_body_request_id_is(response, request_id):
    """Comprueba ``request_id`` en el cuerpo de ``POST /ask``."""
    assert response.json()["request_id"] == request_id


@then(parsers.parse("the response status is {status:d}"))
def response_status_is(response, status):
    """Comprueba el código HTTP."""
    assert response.status_code == status


@then(
    parsers.parse(
        'the response body is an internal error for request "{request_id}"'
    )
)
def response_is_internal_error(response, request_id):
    """El cuerpo no revela el error, solo el id para soporte."""
    assert response.json() == {"detail": "internal error", "request_id": request_id}


@then(parsers.parse("the metrics report {count:d} requests"))
def metrics_report_requests(metrics, count):
    """Comprueba cuántas peticiones contó el proceso antes de ``/metrics``."""
    assert metrics["requests"] == count


@then("the metrics report the input and output tokens of those answers")
def metrics_report_tokens(context, metrics):
    """Los tokens de las métricas suman los de las respuestas."""
    answers = context["answers"]
    assert metrics["tokens"] == {
        "input": sum(answer["input_tokens"] for answer in answers),
        "output": sum(answer["output_tokens"] for answer in answers),
    }


@then(parsers.parse("the latency p95 is {latency:d} ms"))
def latency_p95_is(metrics, latency):
    """Comprueba el p95 medido con el reloj fijo."""
    assert metrics["latency_ms"]["p95"] == pytest.approx(latency)


@then("the SLO is met")
def slo_is_met(metrics):
    """La meta se cumple."""
    assert metrics["slo"]["met"] is True


@then("the SLO is not met")
def slo_is_not_met(metrics):
    """La meta no se cumple."""
    assert metrics["slo"]["met"] is False
