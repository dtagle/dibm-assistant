"""Acceso por clave de cliente y límite de peticiones por cliente.

La clave recibida se compara en tiempo constante con ``hmac.compare_digest`` y
nunca se guarda, se registra ni se devuelve: solo sale el nombre del cliente.
El límite usa el reloj inyectado, así las pruebas no esperan.
"""

import hmac
import math
import threading
from collections import deque
from typing import Mapping

from app.clock import Clock

API_KEY_HEADER = "X-API-Key"
WINDOW_SECONDS = 60.0


def authenticate(api_keys: Mapping[str, str], provided: str | None) -> str | None:
    """Devuelve el cliente dueño de la clave recibida.

    Compara contra todas las claves sin cortar al encontrar una, para que el
    tiempo de respuesta no dependa de cuál coincide.

    :param api_keys: Clave de cada cliente
    :type api_keys: Mapping[str, str]
    :param provided: Valor del encabezado ``X-API-Key`` (puede faltar)
    :type provided: str | None
    :return: Nombre del cliente, o ``None`` si la clave falta o es inválida
    :rtype: str | None
    """
    if not provided:
        return None
    candidate = provided.encode("utf-8")
    owner = None
    for client, key in api_keys.items():
        if hmac.compare_digest(candidate, key.encode("utf-8")):
            owner = client
    return owner


class RateLimiter:
    """Ventana deslizante de un minuto por cliente.

    El estado vive en la memoria del proceso: con varias copias, el límite es
    por copia.

    :param limit: Peticiones permitidas por cliente en la ventana
    :type limit: int
    :param clock: Reloj inyectado (se usa ``monotonic()``)
    :type clock: Clock
    :param window_seconds: Largo de la ventana en segundos
    :type window_seconds: float
    """

    def __init__(
        self, limit: int, clock: Clock, window_seconds: float = WINDOW_SECONDS
    ):
        """Crea el limitador vacío.

        :param limit: Peticiones permitidas por cliente en la ventana
        :type limit: int
        :param clock: Reloj inyectado
        :type clock: Clock
        :param window_seconds: Largo de la ventana en segundos
        :type window_seconds: float
        """
        self._limit = limit
        self._clock = clock
        self._window = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, client: str) -> int:
        """Cuenta una petición del cliente si cabe en la ventana.

        Una petición rechazada no se cuenta.

        :param client: Nombre del cliente
        :type client: str
        :return: ``0`` si se permite; si no, los segundos que faltan para que
            se libere un lugar (al menos 1)
        :rtype: int
        """
        now = self._clock.monotonic()
        with self._lock:
            hits = self._hits.setdefault(client, deque())
            while hits and now - hits[0] >= self._window:
                hits.popleft()
            if len(hits) < self._limit:
                hits.append(now)
                return 0
            return max(1, math.ceil(hits[0] + self._window - now))
