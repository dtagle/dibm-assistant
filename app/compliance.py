"""Compliance como código: reglas que se revisan solas al arrancar.

Con ``ENVIRONMENT=production`` el producto se niega a arrancar si alguna regla
falla. El error nombra cada regla que falla y nunca muestra una clave.
La tabla de reglas está en ``doc/compliance-checklist.md``.
"""

from app.config import ConfigError, Settings

PRODUCTION = "production"
MIN_API_KEY_CHARS = 16


def _model_rule(settings: Settings) -> list[str]:
    """Regla 1: en producción no se usa el modelo simulado.

    :param settings: Configuración
    :type settings: Settings
    :return: Fallas de la regla (vacía si se cumple)
    :rtype: list[str]
    """
    if settings.model_provider == "fake":
        return ["MODEL_PROVIDER must not be fake"]
    return []


def _api_keys_rule(settings: Settings) -> list[str]:
    """Regla 2: hay claves y todas tienen al menos ``MIN_API_KEY_CHARS``.

    Solo se nombran los clientes, que no son secretos; nunca sus claves.

    :param settings: Configuración
    :type settings: Settings
    :return: Fallas de la regla (vacía si se cumple)
    :rtype: list[str]
    """
    if not settings.api_keys:
        return ["API_KEYS must not be empty"]
    short = sorted(
        client
        for client, key in settings.api_keys.items()
        if len(key) < MIN_API_KEY_CHARS
    )
    if short:
        clients = ", ".join(short)
        return [
            f"API_KEYS keys must have at least {MIN_API_KEY_CHARS} characters "
            f"(clients: {clients})"
        ]
    return []


def _tracing_rule(settings: Settings) -> list[str]:
    """Regla 3: con trazas encendidas se ocultan entradas y salidas.

    :param settings: Configuración
    :type settings: Settings
    :return: Fallas de la regla (vacía si se cumple)
    :rtype: list[str]
    """
    if not settings.langsmith_tracing:
        return []
    failures = []
    if not settings.hide_inputs:
        failures.append("HIDE_INPUTS must be true when LANGSMITH_TRACING is on")
    if not settings.hide_outputs:
        failures.append("HIDE_OUTPUTS must be true when LANGSMITH_TRACING is on")
    return failures


def check_compliance(settings: Settings) -> None:
    """Revisa las reglas de producción; fuera de producción no hace nada.

    :param settings: Configuración ya validada
    :type settings: Settings
    :raises ConfigError: Si alguna regla falla; el mensaje las nombra todas
    """
    if settings.environment != PRODUCTION:
        return
    failures = (
        _model_rule(settings) + _api_keys_rule(settings) + _tracing_rule(settings)
    )
    if failures:
        raise ConfigError("production compliance failed: " + "; ".join(failures))
