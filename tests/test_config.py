"""Pruebas de la configuración leída del entorno."""

import pytest

from app.config import ConfigError, load_settings


def test_defaults_are_used_when_the_environment_is_empty():
    settings = load_settings({})
    assert settings.model_provider == "fake"
    assert settings.agent_max_steps == 3
    assert settings.max_question_chars == 2000
    assert str(settings.publications_path).replace("\\", "/").endswith(
        "data/publications.json"
    )


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("AGENT_MAX_STEPS", "0"),
        ("MAX_QUESTION_CHARS", "abc"),
        ("MODEL_PROVIDER", "unknown-model"),
    ],
)
def test_invalid_value_stops_startup_naming_the_variable(variable, value):
    with pytest.raises(ConfigError, match=variable):
        load_settings({variable: value})
