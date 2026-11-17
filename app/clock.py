"""Reloj inyectable del DIBM Assistant.

El código nunca pide la hora directamente: recibe un ``Clock``. Así las pruebas
inyectan un reloj fijo y los resultados son deterministas.
"""

import time
from datetime import datetime, timezone
from typing import Protocol


class Clock(Protocol):
    """Interfaz de cualquier reloj que use el producto."""

    def now(self) -> datetime:
        """Devuelve la hora actual con zona horaria.

        :return: Hora actual
        :rtype: datetime.datetime
        """

    def monotonic(self) -> float:
        """Devuelve segundos de un reloj que nunca retrocede.

        :return: Segundos del reloj monótono
        :rtype: float
        """


class SystemClock:
    """Reloj real del sistema operativo."""

    def now(self) -> datetime:
        """Devuelve la hora actual en UTC.

        :return: Hora actual en UTC
        :rtype: datetime.datetime
        """
        return datetime.fromtimestamp(time.time(), tz=timezone.utc)

    def monotonic(self) -> float:
        """Devuelve los segundos del reloj monótono del sistema.

        :return: Segundos del reloj monótono
        :rtype: float
        """
        return time.monotonic()
