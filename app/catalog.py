"""Catálogo en memoria del snapshot del DIBM y sus búsquedas de solo lectura.

El snapshot viene de un sitio externo: se trata como dato no confiable y solo se
lee. La lista está ordenada del documento más reciente al más antiguo.
"""

import json
import re
import unicodedata
from pathlib import Path

MIN_QUERY_WORD_LENGTH = 4
_WORD_PATTERN = re.compile(r"[a-z0-9]+")
_SEARCH_FIELDS = ("title", "title_en", "abstract", "abstract_en")
_SEARCH_LIST_FIELDS = ("topics", "keywords", "jel")


class CatalogError(RuntimeError):
    """Error al cargar el snapshot que impide arrancar el producto."""


def normalize(text: str) -> str:
    """Pasa el texto a minúsculas y le quita los acentos.

    :param text: Texto original
    :type text: str
    :return: Texto normalizado
    :rtype: str
    """
    decomposed = unicodedata.normalize("NFKD", str(text).lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def words(text: str) -> list[str]:
    """Divide un texto en palabras normalizadas.

    :param text: Texto original
    :type text: str
    :return: Palabras en minúsculas y sin acentos
    :rtype: list[str]
    """
    return _WORD_PATTERN.findall(normalize(text))


def surname_of(author: str) -> str:
    """Devuelve el apellido de un autor: la última palabra de su nombre.

    :param author: Nombre «Nombre Apellido»
    :type author: str
    :return: El apellido, o cadena vacía si el nombre está vacío
    :rtype: str
    """
    parts = str(author).split()
    return parts[-1] if parts else ""


def _searchable_words(publication: dict) -> set[str]:
    """Reúne las palabras buscables de un documento.

    :param publication: Documento del snapshot
    :type publication: dict
    :return: Palabras normalizadas de título, resumen, temas, claves y JEL
    :rtype: set[str]
    """
    found: set[str] = set()
    for field in _SEARCH_FIELDS:
        found.update(words(publication.get(field) or ""))
    for field in _SEARCH_LIST_FIELDS:
        for value in publication.get(field) or []:
            found.update(words(value))
    return found


class Catalog:
    """Snapshot del DIBM cargado en memoria.

    :param publications: Documentos ordenados del más reciente al más antiguo
    :type publications: list[dict]
    """

    def __init__(self, publications: list[dict]):
        """Crea el catálogo y precalcula los índices de búsqueda.

        :param publications: Documentos del snapshot
        :type publications: list[dict]
        """
        self._publications = list(publications)
        self._by_id = {normalize(pub["id"]): pub for pub in self._publications}
        self._words = [_searchable_words(pub) for pub in self._publications]
        self._author_words = [
            [set(words(author)) for author in pub.get("authors") or []]
            for pub in self._publications
        ]

    def __len__(self) -> int:
        """Cuántos documentos tiene el catálogo.

        :return: El número de documentos
        :rtype: int
        """
        return len(self._publications)

    def surnames(self) -> list[str]:
        """Apellidos de todos los autores, sin repetir.

        :return: Apellidos en el orden en que aparecen
        :rtype: list[str]
        """
        seen: dict[str, str] = {}
        for publication in self._publications:
            for author in publication.get("authors") or []:
                surname = surname_of(author)
                if surname and normalize(surname) not in seen:
                    seen[normalize(surname)] = surname
        return list(seen.values())

    def get(self, publication_id: str) -> dict | None:
        """Busca un documento por su id.

        :param publication_id: Clave del documento, por ejemplo ``2025-12``
        :type publication_id: str
        :return: El documento o ``None`` si no existe
        :rtype: dict | None
        """
        key = " ".join(normalize(publication_id).split())
        return self._by_id.get(key)

    def by_author(self, author: str) -> list[dict]:
        """Documentos donde aparece un autor.

        Cada palabra buscada debe aparecer completa en el nombre del autor, sin
        distinguir mayúsculas ni acentos; basta con el apellido.

        :param author: Nombre o apellido del autor
        :type author: str
        :return: Documentos en orden del más reciente al más antiguo
        :rtype: list[dict]
        """
        wanted = set(words(author))
        if not wanted:
            return []
        return [
            publication
            for publication, authors in zip(self._publications, self._author_words)
            if any(wanted <= author_words for author_words in authors)
        ]

    def latest_year(self) -> int:
        """El año más reciente del snapshot (no el del reloj).

        :return: El mayor ``year`` del catálogo
        :rtype: int
        """
        return max(int(publication["year"]) for publication in self._publications)

    def latest(self, year: int | None = None, limit: int = 5) -> list[dict]:
        """Los documentos más recientes de un año.

        :param year: Año de la clave; si es ``None`` se usa el más reciente
        :type year: int | None
        :param limit: Cuántos documentos devolver
        :type limit: int
        :return: Hasta ``limit`` documentos
        :rtype: list[dict]
        """
        target = self.latest_year() if year is None else year
        matching = [pub for pub in self._publications if int(pub["year"]) == target]
        return matching[:limit]

    def search(self, query: str, limit: int = 5) -> list[dict]:
        """Busca documentos por palabras de la consulta.

        Se ignoran palabras de menos de cuatro letras. Primero los que más palabras
        distintas coinciden; si empatan, el más reciente.

        :param query: Texto de la consulta
        :type query: str
        :param limit: Máximo de documentos
        :type limit: int
        :return: Los documentos encontrados
        :rtype: list[dict]
        """
        terms = {term for term in words(query) if len(term) >= MIN_QUERY_WORD_LENGTH}
        if not terms:
            return []
        scored = []
        for position, found in enumerate(self._words):
            score = len(terms & found)
            if score:
                scored.append((-score, position))
        scored.sort()
        return [self._publications[position] for _, position in scored[:limit]]


def load_catalog(path: str | Path) -> Catalog:
    """Carga el snapshot del DIBM desde un archivo JSON.

    :param path: Ruta de ``publications.json``
    :type path: str | pathlib.Path
    :return: El catálogo en memoria
    :rtype: Catalog
    :raises CatalogError: Si el archivo no existe, no es JSON válido o está vacío
    """
    path = Path(path)
    if not path.is_file():
        raise CatalogError(f"Publications snapshot not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        message = f"Publications snapshot is not valid JSON: {path}"
        raise CatalogError(message) from error
    if not isinstance(data, list) or not data:
        raise CatalogError(f"Publications snapshot is empty: {path}")
    if not all(isinstance(item, dict) and "id" in item for item in data):
        raise CatalogError(f"Publications snapshot has invalid entries: {path}")
    return Catalog(data)
