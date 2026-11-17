"""Observabilidad: log JSON, id por petición y métricas del proceso.

El log sale por la salida estándar, una línea JSON por evento. Solo recibe
campos explícitos: nunca el texto de la pregunta, de la respuesta ni claves.
Las métricas viven en memoria y son de este proceso.
"""

import json
import math
import os
import re
import sys
import threading
import uuid
from datetime import timezone
from typing import Any

from app.clock import Clock

REQUEST_ID_HEADER = "X-Request-ID"
# Un id de cliente válido: ASCII visible, sin espacios, de 1 a 128 caracteres.
_REQUEST_ID_PATTERN = re.compile(r"[\x21-\x7e]{1,128}")


def resolve_request_id(header_value: str | None) -> str:
    """Usa el id que manda el cliente o genera un UUID.

    Un valor vacío, muy largo o con caracteres no imprimibles se reemplaza por
    un UUID para que no ensucie el log.

    :param header_value: Valor del encabezado ``X-Request-ID``
    :type header_value: str | None
    :return: El id de la petición
    :rtype: str
    """
    value = (header_value or "").strip()
    if _REQUEST_ID_PATTERN.fullmatch(value):
        return value
    return str(uuid.uuid4())


class JsonLogger:
    """Escribe eventos como una línea JSON en la salida estándar.

    :param service: Valor del campo ``service``
    :type service: str
    :param clock: Reloj que da la hora de cada evento
    :type clock: Clock
    """

    def __init__(self, service: str, clock: Clock):
        """Crea el logger.

        :param service: Nombre del servicio
        :type service: str
        :param clock: Reloj inyectado
        :type clock: Clock
        """
        self._service = service
        self._clock = clock
        self._lock = threading.Lock()

    def timestamp(self) -> str:
        """Da la hora actual en ISO 8601, en UTC y con sufijo ``Z``.

        :return: La hora formateada
        :rtype: str
        """
        now = self._clock.now().astimezone(timezone.utc)
        return now.isoformat(timespec="milliseconds").replace("+00:00", "Z")

    def log(self, event: str, request_id: str, **fields: Any) -> None:
        """Escribe un evento.

        :param event: Nombre del evento (``request``, ``agent_run``, ...)
        :type event: str
        :param request_id: Id de la petición
        :type request_id: str
        :param fields: Campos propios del evento
        :type fields: Any
        """
        record = {
            "ts": self.timestamp(),
            "service": self._service,
            "event": event,
            "request_id": request_id,
        }
        record.update(fields)
        line = json.dumps(record, ensure_ascii=False, default=str)
        with self._lock:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()


def percentile(values: list[float], rank: float) -> float:
    """Calcula un percentil por el método del rango más cercano.

    :param values: Valores medidos
    :type values: list[float]
    :param rank: Percentil entre 0 y 100
    :type rank: float
    :return: El percentil, o 0 si no hay valores
    :rtype: float
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(math.ceil(rank / 100 * len(ordered)) - 1, 0)
    return ordered[min(index, len(ordered) - 1)]


class Metrics:
    """Métricas en memoria de este proceso.

    :param slo_p95_ms: Meta de latencia p95 en milisegundos
    :type slo_p95_ms: int
    """

    def __init__(self, slo_p95_ms: int):
        """Crea las métricas vacías.

        :param slo_p95_ms: Meta de latencia p95
        :type slo_p95_ms: int
        """
        self._slo_p95_ms = slo_p95_ms
        self._lock = threading.Lock()
        self._latencies: list[float] = []
        self._errors = 0
        self._input_tokens = 0
        self._output_tokens = 0
        self._cost_usd = 0.0

    def record_cost(self, cost_usd: float) -> None:
        """Suma el costo de una corrida del agente.

        :param cost_usd: Costo en USD
        :type cost_usd: float
        """
        with self._lock:
            self._cost_usd += cost_usd

    def record_request(self, latency_ms: float, status: int) -> None:
        """Anota una petición terminada.

        :param latency_ms: Latencia en milisegundos
        :type latency_ms: float
        :param status: Código HTTP de la respuesta (5xx cuenta como error)
        :type status: int
        """
        with self._lock:
            self._latencies.append(latency_ms)
            if status >= 500:
                self._errors += 1

    def record_tokens(self, input_tokens: int, output_tokens: int) -> None:
        """Suma los tokens de una corrida del agente.

        :param input_tokens: Tokens de entrada
        :type input_tokens: int
        :param output_tokens: Tokens de salida
        :type output_tokens: int
        """
        with self._lock:
            self._input_tokens += input_tokens
            self._output_tokens += output_tokens

    def snapshot(self) -> dict[str, Any]:
        """Devuelve las métricas actuales.

        :return: ``pid``, ``requests``, ``error_rate``, ``latency_ms``,
            ``tokens``, ``cost_usd`` y ``slo``
        :rtype: dict
        """
        with self._lock:
            latencies = list(self._latencies)
            errors = self._errors
            tokens = {"input": self._input_tokens, "output": self._output_tokens}
            cost_usd = self._cost_usd
        requests = len(latencies)
        p95 = percentile(latencies, 95)
        return {
            "pid": os.getpid(),
            "requests": requests,
            "error_rate": round(errors / requests, 4) if requests else 0.0,
            "latency_ms": {"p50": percentile(latencies, 50), "p95": p95},
            "tokens": tokens,
            "cost_usd": cost_usd,
            "slo": {"p95_ms_target": self._slo_p95_ms, "met": p95 < self._slo_p95_ms},
        }
