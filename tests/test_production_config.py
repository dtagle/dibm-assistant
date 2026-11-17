"""Pruebas de la configuración nueva y de compliance como código (spec 04).

``check_compliance(settings)`` no hace nada fuera de producción; con
``environment="production"`` lanza ``ConfigError`` y nombra cada regla que falla.
"""

from dataclasses import replace

import pytest

from app.compliance import check_compliance
from app.config import ConfigError, Settings, load_settings

LONG_KEY = "portal-key-0123456789abcdef"
SAFE_PRODUCTION = Settings(
    environment="production",
    model_provider="gateway",
    api_keys={"dibm-portal": LONG_KEY},
    langsmith_tracing=True,
    hide_inputs=True,
    hide_outputs=True,
)


def test_new_settings_have_safe_defaults():
    settings = load_settings({})
    assert settings.environment == "development"
    assert isinstance(settings.api_keys, dict)
    assert not settings.api_keys
    assert settings.rate_limit_per_minute == 30


def test_api_keys_are_read_as_client_names_and_keys():
    settings = load_settings(
        {"API_KEYS": f"dibm-portal:{LONG_KEY}, intranet:other-key-0123456789"}
    )
    assert settings.api_keys == {
        "dibm-portal": LONG_KEY,
        "intranet": "other-key-0123456789",
    }


@pytest.mark.parametrize(
    "broken_entry",
    ["secret-value-without-client", "dibm-intranet:", ":secret-value-no-client"],
)
def test_malformed_api_keys_entry_is_reported_by_position_and_length(broken_entry):
    with pytest.raises(ConfigError) as raised:
        load_settings({"API_KEYS": f"dibm-portal:{LONG_KEY},{broken_entry}"})
    message = str(raised.value)
    assert "API_KEYS" in message
    assert "entry 2" in message
    assert str(len(broken_entry)) in message
    assert broken_entry not in message
    assert LONG_KEY not in message


@pytest.mark.parametrize("value", ["0", "abc"])
def test_rate_limit_must_be_a_positive_integer(value):
    with pytest.raises(ConfigError, match="RATE_LIMIT_PER_MINUTE"):
        load_settings({"RATE_LIMIT_PER_MINUTE": value})


def test_api_keys_are_hidden_from_the_settings_repr():
    settings = load_settings({"API_KEYS": f"dibm-portal:{LONG_KEY}"})
    assert LONG_KEY not in repr(settings)


def test_development_allows_the_fake_model_and_short_keys():
    check_compliance(Settings(model_provider="fake", api_keys={"local": "short"}))


def test_a_key_of_sixteen_characters_is_long_enough_for_production():
    check_compliance(replace(SAFE_PRODUCTION, api_keys={"portal": "k" * 16}))
    with pytest.raises(ConfigError, match="API_KEYS"):
        check_compliance(replace(SAFE_PRODUCTION, api_keys={"portal": "k" * 15}))


def test_hidden_trace_rules_apply_only_when_tracing_is_on():
    without_tracing = replace(
        SAFE_PRODUCTION, langsmith_tracing=False, hide_inputs=False, hide_outputs=False
    )
    check_compliance(without_tracing)
    with pytest.raises(ConfigError, match="HIDE_OUTPUTS"):
        check_compliance(replace(SAFE_PRODUCTION, hide_outputs=False))


def test_compliance_error_names_every_failed_rule_without_the_keys():
    unsafe = replace(
        SAFE_PRODUCTION, model_provider="fake", api_keys={"portal": "short-secret"}
    )
    with pytest.raises(ConfigError) as raised:
        check_compliance(unsafe)
    message = str(raised.value)
    assert "MODEL_PROVIDER" in message
    assert "API_KEYS" in message
    assert "short-secret" not in message
