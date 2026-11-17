"""Prueba de humo contra el DIBM Assistant publicado (spec 04, punto 8).

Uso: ``SMOKE_API_KEY=<clave> python scripts/smoke.py <url-del-servicio>``

La clave se lee de la variable ``SMOKE_API_KEY`` y nunca de un argumento, para que
no quede en el historial de la terminal. Nunca se imprime.
"""

import os
import sys

import httpx

QUESTION = {"question": "¿Cuáles son las últimas publicaciones?"}
# Render despierta un servicio dormido en hasta un minuto
TIMEOUT_SECONDS = 90


def run_checks(url: str, key: str, client: httpx.Client) -> bool:
    """Comprueba ``/health``, ``/ask`` sin clave y ``/ask`` con clave.

    Imprime ``[OK]`` o ``[FAIL]`` en cada una, con el código recibido.

    :param url: URL base del servicio, sin la diagonal final
    :type url: str
    :param key: Clave de cliente para ``X-API-Key``
    :type key: str
    :param client: Cliente HTTP que hace las peticiones
    :type client: httpx.Client
    :return: ``True`` si las tres comprobaciones pasan
    :rtype: bool
    """
    checks = [
        ("GET /health", 200, lambda: client.get(f"{url}/health")),
        (
            "POST /ask sin clave",
            401,
            lambda: client.post(f"{url}/ask", json=QUESTION),
        ),
        (
            "POST /ask con clave",
            200,
            lambda: client.post(
                f"{url}/ask", json=QUESTION, headers={"X-API-Key": key}
            ),
        ),
    ]
    passed = True
    for name, expected, request in checks:
        try:
            status = request().status_code
        except httpx.HTTPError as error:
            print(f"[FAIL] {name} -> {type(error).__name__} (esperado {expected})")
            passed = False
            continue
        label = "OK" if status == expected else "FAIL"
        print(f"[{label}] {name} -> {status} (esperado {expected})")
        passed = passed and status == expected
    return passed


def main(args: list[str]) -> int:
    """Corre la prueba de humo.

    :param args: Argumentos de la línea de comandos; solo la URL
    :type args: list[str]
    :return: 0 si todo pasa, 1 si algo falla, 2 si el uso es incorrecto
    :rtype: int
    """
    key = os.environ.get("SMOKE_API_KEY", "")
    if len(args) != 1 or not key:
        print("Uso: SMOKE_API_KEY=<clave> python scripts/smoke.py <url>")
        return 2
    with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
        passed = run_checks(args[0].rstrip("/"), key, client)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
