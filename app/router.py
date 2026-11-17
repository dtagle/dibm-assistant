"""Enrutador: una regla en código (no otro modelo) elige el modelo por pregunta.

Las preguntas largas o que piden análisis van al modelo capaz; las demás, al
barato.
"""

import re

from app.catalog import normalize
from app.config import Settings

ROUTE_DISABLED = "routing_disabled"
ROUTE_LONG = "long_question"
ROUTE_KEYWORD = "keyword"
ROUTE_SHORT = "short_question"
# Palabras ya normalizadas (minúsculas, sin acentos) que piden análisis.
ANALYSIS_KEYWORDS = ("compara", "resume", "explica", "por que", "analiza", "todos")
_KEYWORD_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(word) for word in ANALYSIS_KEYWORDS) + r")\b"
)


def choose_model(question: str, settings: Settings) -> tuple[str, str]:
    """Elige el modelo para una pregunta y dice por qué.

    :param question: Pregunta de la persona
    :type question: str
    :param settings: Configuración (``routing``, ``router_max_chars`` y modelos)
    :type settings: Settings
    :return: ``(modelo, motivo)``; el motivo es ``routing_disabled``,
        ``long_question``, ``keyword`` o ``short_question``
    :rtype: tuple[str, str]
    """
    if not settings.routing:
        return settings.model_large, ROUTE_DISABLED
    if len(question) > settings.router_max_chars:
        return settings.model_large, ROUTE_LONG
    if _KEYWORD_PATTERN.search(normalize(question)):
        return settings.model_large, ROUTE_KEYWORD
    return settings.model_small, ROUTE_SHORT
