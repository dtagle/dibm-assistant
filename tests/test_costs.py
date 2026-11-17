"""Pruebas del cálculo de costo con los precios por millón de tokens."""

import pytest

from app.costs import call_cost, load_prices
from tests.conftest import LARGE_MODEL, SMALL_MODEL


def test_cost_uses_the_price_per_million_tokens(prices_path):
    """Un millón de tokens de entrada y medio de salida del modelo capaz."""
    prices = load_prices(prices_path)
    assert call_cost(prices, LARGE_MODEL, 1_000_000, 500_000) == pytest.approx(20.0)
    assert call_cost(prices, SMALL_MODEL, 100, 50) == pytest.approx(0.0002)


def test_cached_call_costs_nothing(prices_path):
    """Una llamada que el gateway sirvió de caché no cuesta."""
    prices = load_prices(prices_path)
    assert call_cost(prices, LARGE_MODEL, 1000, 1000, cached=True) == 0


def test_missing_prices_file_is_reported(tmp_path):
    """Sin archivo de precios no se puede calcular el costo: falla con claridad."""
    missing = tmp_path / "no_prices.json"
    with pytest.raises(ValueError, match="no_prices.json"):
        load_prices(missing)
