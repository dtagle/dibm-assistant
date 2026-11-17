"""Pruebas del modelo simulado: reglas, su orden y conteo de tokens."""

import json

from app.llm import FakeLLM

HELP = "Pregúntame por un autor o por las últimas publicaciones del DIBM."


def decide(llm, question):
    """Pregunta al modelo y devuelve su objeto JSON.

    :param llm: Modelo simulado
    :type llm: FakeLLM
    :param question: Último mensaje de la persona
    :type question: str
    :return: La decisión del modelo
    :rtype: dict
    """
    completion = llm.complete([{"role": "user", "content": question}])
    return json.loads(completion.text)


def test_publication_id_wins_over_a_year_and_keeps_its_volume():
    decision = decide(FakeLLM(["Pérez"]), "¿De qué trata el 1981-37 T2 de 2025?")
    assert decision == {
        "tool": "get_publication",
        "args": {"publication_id": "1981-37 T2"},
    }


def test_surname_must_match_a_whole_word_ignoring_accents():
    llm = FakeLLM(["Pérez"])
    by_author = decide(llm, "¿Qué ha publicado PEREZ?")
    assert by_author["tool"] == "search_by_author"
    assert by_author["args"]["author"].lower().replace("é", "e") == "perez"
    assert decide(llm, "Un análisis perezoso") == {"answer": HELP}


def test_tokens_are_counted_as_words():
    messages = [
        {"role": "system", "content": "uno dos tres"},
        {"role": "user", "content": "hola mundo"},
    ]
    completion = FakeLLM([]).complete(messages)
    assert json.loads(completion.text) == {"answer": HELP}
    assert completion.input_tokens == 5
    assert completion.output_tokens == len(completion.text.split())
