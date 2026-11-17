"""Pruebas del catálogo y de las herramientas de solo lectura."""

import pytest

from app.catalog import CatalogError, load_catalog
from app.tools import search_by_author, search_publications
from tests.conftest import SAMPLE_PUBLICATIONS, make_publication

SAMPLE_IDS = [publication["id"] for publication in SAMPLE_PUBLICATIONS]


def listed_ids(text, ids):
    """Devuelve los ids que aparecen en el texto, en el orden de ``ids``.

    :param text: Resultado de una herramienta
    :type text: str
    :param ids: Ids candidatos
    :type ids: list[str]
    :return: Los ids presentes
    :rtype: list[str]
    """
    return [pub_id for pub_id in ids if pub_id in text]


@pytest.mark.parametrize("content", [None, []], ids=["missing", "empty"])
def test_missing_or_empty_snapshot_stops_startup(write_snapshot, tmp_path, content):
    path = tmp_path / "missing.json"
    if content is not None:
        path = write_snapshot(content, name="empty.json")
    with pytest.raises(CatalogError, match=path.name):
        load_catalog(path)


def test_author_search_ignores_case_and_accents(catalog):
    result = search_by_author(catalog, "GARCIA")
    assert "Inflación y expectativas en México" in result
    assert "visor.html?clave=2025-12" in result
    assert listed_ids(result, SAMPLE_IDS) == ["2025-12"]


def test_unknown_author_is_reported(catalog):
    result = search_by_author(catalog, "Zapata")
    assert "Zapata" in result
    assert listed_ids(result, SAMPLE_IDS) == []


def test_search_ignores_words_shorter_than_four_letters(catalog):
    result = search_publications(catalog, "la de y")
    assert listed_ids(result, SAMPLE_IDS) == []


def test_search_ranks_more_matches_first_and_newest_on_ties(catalog):
    result = search_publications(catalog, "inflacion expectativas politica")
    found = listed_ids(result, SAMPLE_IDS)
    ranked = sorted(found, key=result.index)
    assert ranked == ["2025-12", "2025-03", "2024-07"]


def test_search_returns_at_most_five_publications(write_snapshot):
    ids = [f"2020-0{number}" for number in range(7, 0, -1)]
    many = [
        make_publication(pub_id, 2020, "2021-05-10", "Remesas", ["Eva Ruiz"])
        for pub_id in ids
    ]
    result = search_publications(load_catalog(write_snapshot(many)), "remesas")
    assert listed_ids(result, ids) == ids[:5]
