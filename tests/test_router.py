"""Pruebas del enrutador: una regla en código elige el modelo por pregunta."""

from app.config import load_settings
from app.router import choose_model
from tests.conftest import LARGE_MODEL, SMALL_MODEL


def test_question_of_exactly_router_max_chars_stays_on_the_small_model():
    """Solo las preguntas que pasan del límite van al modelo capaz."""
    settings = load_settings({"ROUTER_MAX_CHARS": "10"})
    assert choose_model("a" * 10, settings) == (SMALL_MODEL, "short_question")
    assert choose_model("a" * 11, settings) == (LARGE_MODEL, "long_question")


def test_every_analysis_keyword_sends_the_question_to_the_large_model():
    """«compara», «resume», «explica», «por qué», «analiza» y «todos»."""
    settings = load_settings({})
    questions = [
        "Compara dos documentos",
        "Resume el 2025-12",
        "Explica la inflación",
        "¿Por qué sube?",
        "Analiza a Pérez",
        "Dame todos",
    ]
    for question in questions:
        assert choose_model(question, settings) == (LARGE_MODEL, "keyword"), question
