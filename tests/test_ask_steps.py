"""Pasos de los escenarios de ``features/ask.feature`` contra la API."""

from pytest_bdd import given, parsers, scenarios, then, when

from tests.conftest import SAMPLE_TITLES

scenarios("features/ask.feature")


@given("the assistant is running with the sample catalog", target_fixture="api")
def api_with_sample_catalog(make_client):
    """La API con el catálogo de ejemplo y la configuración por omisión."""
    return make_client()


@given(
    parsers.parse(
        "the assistant is running with the sample catalog "
        "and at most {steps:d} agent step"
    ),
    target_fixture="api",
)
def api_with_step_cap(make_client, steps):
    """La API con el tope del bucle en ``steps`` vueltas."""
    return make_client(AGENT_MAX_STEPS=str(steps))


@when(parsers.parse('I ask "{question}"'), target_fixture="response")
def ask_question(api, question):
    """Manda la pregunta a ``POST /ask``."""
    return api.post("/ask", json={"question": question})


@when(
    parsers.parse("I ask a question of {length:d} characters"),
    target_fixture="response",
)
def ask_question_of_length(api, length):
    """Manda una pregunta del largo pedido."""
    return api.post("/ask", json={"question": "a" * length})


@then(parsers.parse("the response status is {status:d}"))
def response_status_is(response, status):
    """Comprueba el código HTTP."""
    assert response.status_code == status


@then(parsers.parse('the tools used are "{tool}"'))
def tools_used_are(response, tool):
    """Comprueba que se usó exactamente esa herramienta."""
    assert response.json()["tools_used"] == [tool]


@then("no tools were used")
def no_tools_were_used(response):
    """Comprueba que el agente no pidió herramientas."""
    assert response.json()["tools_used"] == []


@then(parsers.parse("the agent took {steps:d} steps"))
def agent_took_steps(response, steps):
    """Comprueba las vueltas del bucle."""
    assert response.json()["steps"] == steps


@then(parsers.parse('the answer mentions "{text}"'))
def answer_mentions(response, text):
    """Comprueba que la respuesta contiene el texto."""
    assert text in response.json()["answer"]


@then(parsers.parse('the answer does not mention "{text}"'))
def answer_does_not_mention(response, text):
    """Comprueba que la respuesta no contiene el texto."""
    assert text not in response.json()["answer"]


@then("the answer mentions no sample title")
def answer_mentions_no_sample_title(response):
    """Comprueba que no se inventó ningún documento del catálogo."""
    answer = response.json()["answer"]
    assert not [title for title in SAMPLE_TITLES if title in answer]


@then(parsers.parse('the answer is "{text}"'))
def answer_is(response, text):
    """Comprueba la respuesta exacta."""
    assert response.json()["answer"] == text
