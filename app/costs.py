"""Precios por modelo y costo de cada llamada.

Los precios están en USD por millón de tokens. Una llamada que el gateway
sirvió de caché no cuesta.
"""

import json
from pathlib import Path

TOKENS_PER_PRICE_UNIT = 1_000_000

Prices = dict[str, dict[str, float]]


def load_prices(path: Path) -> Prices:
    """Carga los precios de ``model_prices.json``.

    :param path: Ruta del archivo de precios
    :type path: pathlib.Path
    :return: Precio de entrada y salida por modelo
    :rtype: dict[str, dict[str, float]]
    :raises ValueError: Si el archivo no existe, no es JSON o no tiene la forma
        esperada; el mensaje nombra el archivo
    """
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ValueError(f"Cannot read prices file: {path}") from error
    except ValueError as error:
        raise ValueError(f"Prices file is not valid JSON: {path}") from error
    models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(models, dict):
        raise ValueError(f"Prices file has no models: {path}")
    prices: Prices = {}
    for model, price in models.items():
        try:
            prices[model] = {
                "input": float(price["input"]),
                "output": float(price["output"]),
            }
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"Invalid price for {model} in {path}") from error
    return prices


def call_cost(  # pylint: disable=too-many-arguments
    prices: Prices,
    model: str,
    input_tokens: int,
    output_tokens: int,
    *,
    cached: bool = False,
) -> float:
    """Calcula el costo en USD de una llamada al modelo.

    :param prices: Precios por modelo
    :type prices: dict[str, dict[str, float]]
    :param model: Nombre del modelo
    :type model: str
    :param input_tokens: Tokens de entrada
    :type input_tokens: int
    :param output_tokens: Tokens de salida
    :type output_tokens: int
    :param cached: Si el gateway la sirvió de caché
    :type cached: bool
    :return: Costo en USD (0 si fue cacheada)
    :rtype: float
    :raises ValueError: Si el modelo no tiene precio
    """
    if cached:
        return 0.0
    if model not in prices:
        raise ValueError(f"No price for model: {model}")
    price = prices[model]
    total = input_tokens * price["input"] + output_tokens * price["output"]
    return total / TOKENS_PER_PRICE_UNIT
