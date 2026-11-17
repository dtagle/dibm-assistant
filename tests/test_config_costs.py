"""Pruebas de la configuración nueva de costos y del archivo ``.env.example``."""

import pytest

from app.config import PRODUCT_DIR, ConfigError, load_settings
from tests.conftest import LARGE_MODEL, SMALL_MODEL

PRODUCT_VARIABLES = (
    "MODEL_PROVIDER",
    "AGENT_MAX_STEPS",
    "MAX_QUESTION_CHARS",
    "PUBLICATIONS_PATH",
    "SERVICE_NAME",
    "SLO_P95_MS",
    "LANGSMITH_TRACING",
    "LANGSMITH_API_KEY",
    "HIDE_INPUTS",
    "HIDE_OUTPUTS",
    "CF_ACCOUNT_ID",
    "CF_GATEWAY_ID",
    "CF_API_TOKEN",
    "MODEL_SMALL",
    "MODEL_LARGE",
    "ROUTING",
    "ROUTER_MAX_CHARS",
    "HISTORY_WINDOW",
    "MODEL_MAX_TOKENS",
    "MODEL_TEMPERATURE",
    "CACHE_TTL_SECONDS",
    "PRICES_PATH",
)


def test_cost_settings_have_the_documented_defaults():
    """Los valores por omisión de la tabla de la especificación."""
    settings = load_settings({})
    assert settings.model_small == SMALL_MODEL
    assert settings.model_large == LARGE_MODEL
    assert settings.routing is True
    assert settings.router_max_chars == 80
    assert settings.history_window == 6
    assert settings.model_max_tokens == 300
    assert settings.model_temperature == 0
    assert settings.cache_ttl_seconds == 0
    assert str(settings.prices_path).replace("\\", "/").endswith(
        "data/model_prices.json"
    )


def test_gateway_settings_load_with_cloudflare_credentials():
    """Con las tres variables ``CF_*`` arranca; el gateway por omisión es
    ``default``."""
    settings = load_settings(
        {
            "MODEL_PROVIDER": "gateway",
            "CF_ACCOUNT_ID": "account-123",
            "CF_API_TOKEN": "token-secret-value",
        }
    )
    assert settings.model_provider == "gateway"
    assert settings.cf_account_id == "account-123"
    assert settings.cf_gateway_id == "default"


def test_gateway_without_token_stops_startup():
    """Falta ``CF_API_TOKEN``: no arranca y el mensaje nombra la variable."""
    with pytest.raises(ConfigError, match="CF_API_TOKEN"):
        load_settings({"MODEL_PROVIDER": "gateway", "CF_ACCOUNT_ID": "account-123"})


def test_env_example_lists_every_variable_without_secret_values():
    """``.env.example`` documenta todas las variables y deja vacíos los secretos."""
    lines = (PRODUCT_DIR / ".env.example").read_text("utf-8").splitlines()
    values = {}
    for line in lines:
        if "=" in line and not line.lstrip().startswith("#"):
            name, value = line.split("=", 1)
            values[name.strip()] = value.strip()
    for name in PRODUCT_VARIABLES:
        assert name in values, name
    assert values["CF_API_TOKEN"] == ""
    assert values["LANGSMITH_API_KEY"] == ""
