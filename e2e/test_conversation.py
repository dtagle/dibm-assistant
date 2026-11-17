"""Pruebas de punta a punta de la página del DIBM Assistant (specs 03 y 04).

Corren contra el producto vivo con el modelo simulado. La URL base la pone la
verificación (``--base-url``); los elementos se buscan por ``data-testid``.
La clave se lee de ``E2E_API_KEY``, que pone la verificación; nunca se escribe aquí.
"""

import os
import re

from playwright.sync_api import Page, expect

FIRST_QUESTION = "¿Cuáles son las últimas publicaciones?"
SECOND_QUESTION = "¿De qué trata el documento 2025-12?"
FAKE_ANSWER_PREFIX = "Según el DIBM de Banxico"
INVALID_KEY_MESSAGE = "Clave inválida"


def _open_with_key(page: Page, api_key: str) -> None:
    """Abre la página y escribe la clave en su campo.

    :param page: Página de Playwright
    :type page: Page
    :param api_key: Clave que se escribe en ``data-testid="api-key"``
    :type api_key: str
    """
    page.goto("/")
    page.get_by_test_id("api-key").fill(api_key)


def _open_with_valid_key(page: Page) -> None:
    """Abre la página y escribe la clave válida de ``E2E_API_KEY``.

    :param page: Página de Playwright
    :type page: Page
    """
    _open_with_key(page, os.environ["E2E_API_KEY"])


def _ask(page: Page, question: str) -> dict:
    """Escribe una pregunta, la envía y devuelve el cuerpo JSON de ``/ask``.

    :param page: Página de Playwright ya abierta en ``/`` con la clave escrita
    :type page: Page
    :param question: Texto de la pregunta
    :type question: str
    :return: Cuerpo de la respuesta de ``POST /ask``
    :rtype: dict
    """
    page.get_by_test_id("question").fill(question)
    with page.expect_response(re.compile(r"/ask$")) as response_info:
        page.get_by_test_id("send").click()
    response = response_info.value
    assert response.ok, f"POST /ask answered {response.status}"
    return response.json()


def test_the_api_key_field_hides_what_is_typed(page: Page) -> None:
    """El campo de clave es de tipo contraseña."""
    page.goto("/")

    expect(page.get_by_test_id("api-key")).to_have_attribute("type", "password")


def test_a_sent_question_shows_its_answer_and_request_id(page: Page) -> None:
    """Una pregunta enviada con clave muestra la respuesta y su request_id."""
    _open_with_valid_key(page)
    body = _ask(page, FIRST_QUESTION)

    conversation = page.get_by_test_id("answer")
    expect(conversation).to_contain_text(FIRST_QUESTION)
    expect(conversation).to_contain_text(FAKE_ANSWER_PREFIX)
    expect(conversation).to_contain_text(str(body["request_id"]))


def test_an_empty_question_shows_an_error_message_in_spanish(page: Page) -> None:
    """Enviar una pregunta vacía muestra un mensaje de error visible."""
    _open_with_valid_key(page)
    page.get_by_test_id("question").fill("")
    page.get_by_test_id("send").click()

    expect(page.get_by_test_id("answer")).to_have_text(re.compile(r"\S"))


def test_a_second_question_keeps_the_previous_conversation(page: Page) -> None:
    """La segunda pregunta no borra la conversación anterior."""
    _open_with_valid_key(page)
    first = _ask(page, FIRST_QUESTION)
    conversation = page.get_by_test_id("answer")
    expect(conversation).to_contain_text(str(first["request_id"]))

    second = _ask(page, SECOND_QUESTION)

    expect(conversation).to_contain_text(SECOND_QUESTION)
    expect(conversation).to_contain_text(str(second["request_id"]))
    expect(conversation).to_contain_text(FIRST_QUESTION)
    expect(conversation).to_contain_text(str(first["request_id"]))


def test_a_wrong_api_key_shows_invalid_key_message(page: Page) -> None:
    """Una clave equivocada muestra «Clave inválida»."""
    wrong_key = "wrong-" + os.environ["E2E_API_KEY"]
    _open_with_key(page, wrong_key)
    page.get_by_test_id("question").fill(FIRST_QUESTION)
    with page.expect_response(re.compile(r"/ask$")) as response_info:
        page.get_by_test_id("send").click()
    assert response_info.value.status == 401

    expect(page.get_by_test_id("answer")).to_contain_text(INVALID_KEY_MESSAGE)
