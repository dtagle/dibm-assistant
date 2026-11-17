"""Pruebas de la configuración de observabilidad (spec 02)."""

import pytest

from app.config import ConfigError, load_settings


def test_observability_settings_have_safe_defaults():
    settings = load_settings({})
    assert settings.service_name == "dibm-assistant"
    assert settings.slo_p95_ms == 2000
    assert settings.langsmith_tracing is False
    assert settings.hide_inputs is True
    assert settings.hide_outputs is True


def test_observability_settings_are_read_from_the_environment():
    settings = load_settings(
        {
            "SERVICE_NAME": "dibm-staging",
            "SLO_P95_MS": "1500",
            "LANGSMITH_TRACING": "true",
            "HIDE_INPUTS": "false",
            "HIDE_OUTPUTS": "false",
        }
    )
    assert settings.service_name == "dibm-staging"
    assert settings.slo_p95_ms == 1500
    assert settings.langsmith_tracing is True
    assert settings.hide_inputs is False
    assert settings.hide_outputs is False


@pytest.mark.parametrize("value", ["0", "fast"])
def test_invalid_slo_target_stops_startup(value):
    with pytest.raises(ConfigError, match="SLO_P95_MS"):
        load_settings({"SLO_P95_MS": value})
