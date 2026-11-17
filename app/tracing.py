"""Trazas opcionales en LangSmith.

Sin ``LANGSMITH_TRACING=true`` y ``LANGSMITH_API_KEY`` el envoltorio devuelve la
función tal cual: no importa ``langsmith`` ni intenta conectarse. La clave la
lee la librería del entorno; este módulo nunca la toca.
"""

import os
from typing import Any, Callable, Mapping

from app.config import Settings

API_KEY_VARIABLES = ("LANGSMITH_API_KEY", "LANGCHAIN_API_KEY")


def has_api_key(env: Mapping[str, str]) -> bool:
    """Indica si existe una clave de LangSmith, sin devolver su valor.

    :param env: Variables de entorno
    :type env: Mapping[str, str]
    :return: ``True`` si alguna variable de clave tiene valor
    :rtype: bool
    """
    return any((env.get(name) or "").strip() for name in API_KEY_VARIABLES)


class Tracer:
    """Envuelve funciones con ``@traceable`` cuando las trazas están activas.

    :param settings: Configuración (``langsmith_tracing`` y ``hide_*``)
    :type settings: Settings
    :param env: Entorno donde se busca la clave; por omisión ``os.environ``
    :type env: Mapping[str, str] | None
    """

    def __init__(self, settings: Settings, env: Mapping[str, str] | None = None):
        """Prepara el cliente de LangSmith solo si las trazas están activas.

        :param settings: Configuración del producto
        :type settings: Settings
        :param env: Entorno donde se busca la clave
        :type env: Mapping[str, str] | None
        """
        self._traceable: Callable[..., Any] | None = None
        self._client: Any = None
        env = os.environ if env is None else env
        if settings.langsmith_tracing and has_api_key(env):
            self._setup(settings.hide_inputs, settings.hide_outputs)

    def _setup(self, hide_inputs: bool, hide_outputs: bool) -> None:
        """Importa ``langsmith`` y crea su cliente.

        Si la librería no está instalada, las trazas quedan apagadas.

        :param hide_inputs: No mandar entradas
        :type hide_inputs: bool
        :param hide_outputs: No mandar salidas
        :type hide_outputs: bool
        """
        try:
            # pylint: disable-next=import-outside-toplevel
            from langsmith import Client, traceable
        except ImportError:
            return
        self._client = Client(hide_inputs=hide_inputs, hide_outputs=hide_outputs)
        self._traceable = traceable

    @property
    def enabled(self) -> bool:
        """Indica si las trazas están activas.

        :return: ``True`` si se mandan trazas
        :rtype: bool
        """
        return self._traceable is not None

    def wrap(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        func: Callable[..., Any],
        name: str,
        run_type: str,
        request_id: str,
        client: str | None = None,
    ) -> Callable[..., Any]:
        """Envuelve una función para que quede como traza.

        :param func: Función a trazar
        :type func: Callable
        :param name: Nombre de la traza
        :type name: str
        :param run_type: Tipo de traza (``chain``, ``llm`` o ``tool``)
        :type run_type: str
        :param request_id: Id de la petición, va en los metadatos
        :type request_id: str
        :param client: Nombre del cliente (nunca su clave), va en los metadatos
        :type client: str | None
        :return: La función envuelta, o la misma si las trazas están apagadas
        :rtype: Callable
        """
        if self._traceable is None:
            return func
        metadata = {"request_id": request_id}
        if client is not None:
            metadata["client"] = client
        decorator = self._traceable(
            name=name,
            run_type=run_type,
            client=self._client,
            metadata=metadata,
        )
        return decorator(func)
