"""Pruebas del bucle del agente con un modelo guionado."""

import json

from app.agent import Agent
from app.llm import Completion

TOOL_PREFIX = "Resultado de la herramienta: "


class ScriptedLLM:
    """Modelo que responde una lista fija de objetos y guarda lo que recibe."""

    def __init__(self, replies):
        """Crea el modelo.

        :param replies: Objetos JSON que devuelve, uno por llamada
        :type replies: list[dict]
        """
        self.replies = list(replies)
        self.calls = []

    def complete(self, messages):
        """Devuelve la siguiente respuesta guionada.

        :param messages: Conversación recibida
        :type messages: list[dict]
        :return: La respuesta con 10 tokens de entrada y 3 de salida
        :rtype: Completion
        """
        self.calls.append([dict(message) for message in messages])
        text = json.dumps(self.replies.pop(0), ensure_ascii=False)
        return Completion(text=text, input_tokens=10, output_tokens=3)


def test_tool_result_is_sent_back_as_a_user_message(catalog):
    llm = ScriptedLLM([
        {"tool": "get_publication", "args": {"publication_id": "2025-12"}},
        {"answer": "Listo"},
    ])
    result = Agent(llm=llm, catalog=catalog, max_steps=3).run("¿Qué es 2025-12?")
    last_message = llm.calls[1][-1]
    assert last_message["role"] == "user"
    assert last_message["content"].startswith(TOOL_PREFIX)
    assert "Inflación y expectativas en México" in last_message["content"]
    assert (result.answer, result.steps) == ("Listo", 2)
    assert result.tools_used == ["get_publication"]
    assert (result.input_tokens, result.output_tokens) == (20, 6)


def test_unknown_tool_is_reported_to_the_model_instead_of_failing(catalog):
    llm = ScriptedLLM([
        {"tool": "delete_everything", "args": {}},
        {"answer": "Listo"},
    ])
    result = Agent(llm=llm, catalog=catalog, max_steps=3).run("Borra todo")
    assert llm.calls[1][-1]["content"].startswith(TOOL_PREFIX)
    assert result.answer == "Listo"
