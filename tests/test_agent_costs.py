"""Pruebas de las palancas de costo dentro del agente y del modelo simulado
con precio."""

import json

import pytest

from app.agent import Agent
from app.costs import load_prices
from app.llm import Completion
from app.prompts import SYSTEM_PROMPT
from tests.conftest import LARGE_MODEL, SMALL_MODEL, expected_cost


class ScriptedLLM:
    """Modelo que devuelve respuestas fijas en orden y guarda lo que recibe.

    :param completions: Respuestas a devolver, una por llamada
    :type completions: list[Completion]
    """

    def __init__(self, completions):
        """Guarda las respuestas y prepara el registro de llamadas."""
        self._completions = list(completions)
        self.calls = []

    def complete(self, messages):
        """Registra los mensajes y devuelve la siguiente respuesta.

        :param messages: Conversación
        :type messages: list[dict]
        :return: La respuesta fija
        :rtype: Completion
        """
        self.calls.append([dict(message) for message in messages])
        return self._completions.pop(0)


def test_agent_sends_only_the_last_history_window_messages(catalog):
    """Con ``HISTORY_WINDOW=2`` el modelo ve sistema, dos turnos y la pregunta."""
    llm = ScriptedLLM([Completion(text='{"answer": "Hola"}')])
    history = [
        {"role": "user" if index % 2 == 0 else "assistant", "content": f"turn {index}"}
        for index in range(5)
    ]
    Agent(llm, catalog, 3, history_window=2).run("¿Qué hay?", history)
    sent = llm.calls[0]
    assert sent[0]["role"] == "system"
    assert [message["content"] for message in sent[1:]] == [
        "turn 3",
        "turn 4",
        "¿Qué hay?",
    ]


def test_agent_counts_cached_calls_and_charges_only_the_others(catalog, prices_path):
    """La llamada servida de caché no cuesta; la otra se cobra con su modelo."""
    tool_call = json.dumps(
        {"tool": "get_publication", "args": {"publication_id": "2025-12"}}
    )
    llm = ScriptedLLM(
        [
            Completion(text=tool_call, input_tokens=100, output_tokens=10, cached=True),
            Completion(text='{"answer": "Listo"}', input_tokens=200, output_tokens=20),
        ]
    )
    agent = Agent(llm, catalog, 3, model=SMALL_MODEL, prices=load_prices(prices_path))
    result = agent.run("Documento 2025-12")
    assert result.cached_calls == 1
    assert result.cost_usd == pytest.approx(expected_cost(SMALL_MODEL, 200, 20))


def test_system_prompt_asks_to_cite_page_url_and_never_invent():
    """El prompt nombra las cuatro herramientas, pide citar y prohíbe inventar."""
    for tool in (
        "get_publication",
        "search_by_author",
        "latest_publications",
        "search_publications",
    ):
        assert tool in SYSTEM_PROMPT
    prompt = SYSTEM_PROMPT.lower()
    assert "page_url" in prompt
    assert "español" in prompt
    assert "invent" in prompt


def test_fake_models_answer_alike_but_cost_by_their_name(make_cost_client):
    """Los dos modelos simulados responden lo mismo; el capaz cuesta más."""
    question = {"question": "¿Cuáles son las últimas publicaciones?"}
    small = make_cost_client().post("/ask", json=question).json()
    large = make_cost_client(ROUTING="false").post("/ask", json=question).json()
    assert (small["model"], large["model"]) == (SMALL_MODEL, LARGE_MODEL)
    assert small["answer"] == large["answer"]
    assert small["input_tokens"] == large["input_tokens"]
    assert large["cost_usd"] == pytest.approx(
        expected_cost(LARGE_MODEL, large["input_tokens"], large["output_tokens"])
    )
    assert large["cost_usd"] > small["cost_usd"] > 0
