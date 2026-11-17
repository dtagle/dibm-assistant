"""Las cuatro herramientas de solo lectura del agente sobre el catálogo.

Cada herramienta devuelve texto con id, título, autores, fecha y ``page_url`` de
cada documento, para que la respuesta cite su fuente.
"""

from typing import Any, Callable

from app.catalog import Catalog

DEFAULT_LIMIT = 5
MAX_LIMIT = 20


class ToolError(ValueError):
    """La herramienta no existe o sus argumentos no son válidos."""


def _format_publication(publication: dict) -> str:
    """Da formato de una línea a un documento.

    :param publication: Documento del snapshot
    :type publication: dict
    :return: Id, título, autores, fecha y página del documento
    :rtype: str
    """
    authors = ", ".join(publication.get("authors") or []) or "Sin autores"
    when = publication.get("date") or str(publication.get("year", ""))
    return (
        f"- {publication['id']} | {publication.get('title', '')} | {authors} | "
        f"{when} | {publication.get('page_url', '')}"
    )


def _format_list(publications: list[dict]) -> str:
    """Da formato a una lista de documentos, uno por línea.

    :param publications: Documentos a mostrar
    :type publications: list[dict]
    :return: El texto con un documento por línea
    :rtype: str
    """
    return "\n".join(_format_publication(publication) for publication in publications)


def get_publication(catalog: Catalog, publication_id: str) -> str:
    """Devuelve un documento por su id, con resumen y PDF.

    :param catalog: Catálogo del DIBM
    :type catalog: Catalog
    :param publication_id: Clave del documento, por ejemplo ``2025-12``
    :type publication_id: str
    :return: El documento o un aviso de que no existe
    :rtype: str
    """
    publication = catalog.get(str(publication_id))
    if publication is None:
        return f"No existe una publicación con id «{publication_id}»."
    abstract = publication.get("abstract") or publication.get("abstract_en") or ""
    return (
        f"{_format_publication(publication)}\n"
        f"Resumen: {abstract or 'Sin resumen'}\n"
        f"PDF: {publication.get('pdf_url', '')}"
    )


def search_by_author(catalog: Catalog, author: str) -> str:
    """Lista los documentos donde aparece un autor.

    :param catalog: Catálogo del DIBM
    :type catalog: Catalog
    :param author: Nombre o apellido, sin importar mayúsculas ni acentos
    :type author: str
    :return: Los documentos o un aviso de que no hay
    :rtype: str
    """
    found = catalog.by_author(str(author))
    if not found:
        return f"No encontré publicaciones del autor «{author}»."
    return f"Publicaciones de «{author}»:\n{_format_list(found)}"


def latest_publications(
    catalog: Catalog, year: int | None = None, limit: int = DEFAULT_LIMIT
) -> str:
    """Lista los documentos más recientes, de un año o del más reciente.

    :param catalog: Catálogo del DIBM
    :type catalog: Catalog
    :param year: Año de la clave; sin él se usa el más reciente del snapshot
    :type year: int | None
    :param limit: Cuántos documentos devolver (de 1 a 20)
    :type limit: int
    :return: Los documentos o un aviso de que no hay
    :rtype: str
    :raises ToolError: Si ``year`` o ``limit`` no son enteros válidos
    """
    target = catalog.latest_year() if year is None else _as_int(year, "year")
    count = min(max(_as_int(limit, "limit"), 1), MAX_LIMIT)
    found = catalog.latest(target, count)
    if not found:
        return f"No encontré publicaciones de {target}."
    return f"Publicaciones más recientes de {target}:\n{_format_list(found)}"


def search_publications(catalog: Catalog, query: str) -> str:
    """Busca documentos por tema, título, resumen, palabras clave o JEL.

    :param catalog: Catálogo del DIBM
    :type catalog: Catalog
    :param query: Texto de la consulta
    :type query: str
    :return: Hasta cinco documentos o un aviso de que no hay
    :rtype: str
    """
    found = catalog.search(str(query), DEFAULT_LIMIT)
    if not found:
        return f"No encontré publicaciones sobre «{query}»."
    return f"Publicaciones sobre «{query}»:\n{_format_list(found)}"


def _as_int(value: Any, name: str) -> int:
    """Convierte un argumento a entero.

    :param value: Valor recibido del modelo
    :type value: Any
    :param name: Nombre del argumento
    :type name: str
    :return: El entero
    :rtype: int
    :raises ToolError: Si no es un entero
    """
    if isinstance(value, bool):
        raise ToolError(f"{name} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise ToolError(f"{name} must be an integer") from error


TOOLS: dict[str, Callable[..., str]] = {
    "get_publication": get_publication,
    "search_by_author": search_by_author,
    "latest_publications": latest_publications,
    "search_publications": search_publications,
}


def run_tool(catalog: Catalog, name: str, args: Any) -> str:
    """Ejecuta una herramienta por nombre con los argumentos del modelo.

    :param catalog: Catálogo del DIBM
    :type catalog: Catalog
    :param name: Nombre de la herramienta
    :type name: str
    :param args: Argumentos con nombre
    :type args: Any
    :return: El resultado en texto
    :rtype: str
    :raises ToolError: Si la herramienta no existe o los argumentos no sirven
    """
    tool = TOOLS.get(name) if isinstance(name, str) else None
    if tool is None:
        raise ToolError(f"Unknown tool: {name}")
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise ToolError("Tool arguments must be an object")
    try:
        return tool(catalog, **args)
    except TypeError as error:
        raise ToolError(f"Invalid arguments for {name}") from error
