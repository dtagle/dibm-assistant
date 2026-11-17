"""Agente único con bucle con tope sobre las herramientas del DIBM.

En cada vuelta el modelo pide una herramienta o responde. El resultado de una
herramienta vuelve al modelo como mensaje ``user`` con un prefijo fijo.
"""

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from app.catalog import Catalog
from app.costs import Prices, call_cost
from app.llm import LLM, TOOL_RESULT_PREFIX, Completion
from app.prompts import SYSTEM_PROMPT
from app.tools import ToolError, run_tool

STOPPED_ANSWER = (
    "No pude completar la respuesta. Intenta con una pregunta más concreta."
)
ALLOWED_HISTORY_ROLES = ("user", "assistant")

AuditHook = Callable[[Any, Any], None]
WrapHook = Callable[[Callable[..., Any], str, str], Callable[..., Any]]


def _no_wrap(func: Callable[..., Any], _name: str, _run_type: str) -> Callable:
    """Envoltorio que no hace nada (trazas apagadas).

    :param func: Función a envolver
    :type func: Callable
    :param _name: Nombre de la traza (no se usa)
    :type _name: str
    :param _run_type: Tipo de traza (no se usa)
    :type _run_type: str
    :return: La misma función
    :rtype: Callable
    """
    return func


@dataclass
class AgentResult:  # pylint: disable=too-many-instance-attributes
    """Resultado de una corrida del agente.

    Reúne todo lo que la API devuelve y registra: por eso tiene muchos
    atributos.

    :param answer: Respuesta final para la persona
    :type answer: str
    :param steps: Vueltas del bucle (llamadas al modelo)
    :type steps: int
    :param tools_used: Herramientas ejecutadas, en orden
    :type tools_used: list[str]
    :param input_tokens: Tokens de entrada acumulados
    :type input_tokens: int
    :param output_tokens: Tokens de salida acumulados
    :type output_tokens: int
    :param stopped: Si se llegó al tope sin respuesta
    :type stopped: bool
    :param cached_calls: Llamadas servidas de la caché del gateway
    :type cached_calls: int
    :param cost_usd: Costo acumulado en USD
    :type cost_usd: float
    """

    answer: str = ""
    steps: int = 0
    tools_used: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    stopped: bool = False
    cached_calls: int = 0
    cost_usd: float = 0.0


def parse_reply(text: str) -> dict:
    """Interpreta la respuesta del modelo según el protocolo JSON.

    Un texto que no es un objeto JSON con ``tool`` o ``answer`` se toma como
    respuesta final.

    :param text: Texto devuelto por el modelo
    :type text: str
    :return: ``{"answer": ...}`` o ``{"tool": ..., "args": ...}``
    :rtype: dict
    """
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return {"answer": str(text)}
    if isinstance(data, dict):
        if "tool" in data:
            return {"tool": data.get("tool"), "args": data.get("args")}
        if "answer" in data:
            return {"answer": str(data["answer"])}
    return {"answer": str(text)}


class Agent:  # pylint: disable=too-many-instance-attributes
    """Agente con bucle con tope.

    Sus dependencias se inyectan (modelo, catálogo, ganchos, ventana y
    precios): por eso tiene muchos atributos.

    :param llm: Modelo con ``complete(messages)``
    :type llm: LLM
    :param catalog: Catálogo del DIBM
    :type catalog: Catalog
    :param max_steps: Tope de vueltas del bucle
    :type max_steps: int
    :param audit: Se llama con ``(tool, args)`` por cada herramienta pedida
    :type audit: Callable | None
    :param wrap: Envuelve funciones como trazas con ``(func, name, run_type)``
    :type wrap: Callable | None
    :param history_window: Mensajes de historial que se mandan (``None``: todos)
    :type history_window: int | None
    :param model: Nombre del modelo, para el costo
    :type model: str | None
    :param prices: Precios por modelo; sin ellos el costo es 0
    :type prices: dict | None
    """

    def __init__(  # pylint: disable=too-many-arguments
        self,
        llm: LLM,
        catalog: Catalog,
        max_steps: int,
        *,
        audit: AuditHook | None = None,
        wrap: WrapHook | None = None,
        history_window: int | None = None,
        model: str | None = None,
        prices: Prices | None = None,
    ):
        """Crea el agente con sus dependencias.

        :param llm: Modelo a usar
        :type llm: LLM
        :param catalog: Catálogo del DIBM
        :type catalog: Catalog
        :param max_steps: Tope de vueltas
        :type max_steps: int
        :param audit: Registro de cada herramienta pedida
        :type audit: Callable | None
        :param wrap: Envoltorio de trazas
        :type wrap: Callable | None
        :param history_window: Ventana de historial (``None``: sin ventana)
        :type history_window: int | None
        :param model: Nombre del modelo usado
        :type model: str | None
        :param prices: Precios por modelo
        :type prices: dict | None
        """
        self._llm = llm
        self._wrap = wrap or _no_wrap
        self._complete = self._wrap(llm.complete, "llm.complete", "llm")
        self._catalog = catalog
        self._max_steps = max_steps
        self._audit = audit
        self._history_window = history_window
        self._model = model
        self._prices = prices

    def run(self, question: str, history: list[dict] | None = None) -> AgentResult:
        """Responde una pregunta usando el modelo y las herramientas.

        :param question: Pregunta de la persona
        :type question: str
        :param history: Turnos previos que manda el cliente
        :type history: list[dict] | None
        :return: La respuesta, los pasos, las herramientas y los tokens
        :rtype: AgentResult
        """
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(_window(_clean_history(history), self._history_window))
        messages.append({"role": "user", "content": question})
        result = AgentResult()
        for _ in range(self._max_steps):
            completion = self._complete(messages)
            self._account(completion, result)
            reply = parse_reply(completion.text)
            if "answer" in reply:
                result.answer = reply["answer"]
                return result
            messages.append({"role": "assistant", "content": completion.text})
            output = self._execute(reply["tool"], reply["args"], result)
            messages.append({"role": "user", "content": TOOL_RESULT_PREFIX + output})
        result.answer = STOPPED_ANSWER
        result.stopped = True
        return result

    def _account(self, completion: Completion, result: AgentResult) -> None:
        """Suma pasos, tokens, llamadas cacheadas y costo de una llamada.

        :param completion: Respuesta del modelo
        :type completion: Completion
        :param result: Resultado en curso
        :type result: AgentResult
        """
        result.steps += 1
        result.input_tokens += completion.input_tokens
        result.output_tokens += completion.output_tokens
        if completion.cached:
            result.cached_calls += 1
        if self._prices is not None and self._model is not None:
            result.cost_usd += call_cost(
                self._prices,
                self._model,
                completion.input_tokens,
                completion.output_tokens,
                cached=completion.cached,
            )

    def _execute(self, name, args, result: AgentResult) -> str:
        """Ejecuta una herramienta y registra su uso.

        Un error de la herramienta se informa al modelo en lugar de fallar.

        :param name: Nombre pedido por el modelo
        :type name: Any
        :param args: Argumentos pedidos por el modelo
        :type args: Any
        :param result: Resultado en curso donde se anota la herramienta
        :type result: AgentResult
        :return: El texto del resultado o del error
        :rtype: str
        """
        if self._audit is not None:
            self._audit(name, args)
        tool = self._wrap(run_tool, f"tool:{name}", "tool")
        try:
            output = tool(self._catalog, name, args)
        except ToolError as error:
            return f"Error: {error}"
        result.tools_used.append(name)
        return output


def _window(history: list[dict], size: int | None) -> list[dict]:
    """Conserva solo los últimos ``size`` mensajes del historial.

    :param history: Turnos ya limpios
    :type history: list[dict]
    :param size: Tamaño de la ventana; ``None`` conserva todos
    :type size: int | None
    :return: Los últimos turnos
    :rtype: list[dict]
    """
    if size is None:
        return history
    if size <= 0:
        return []
    return history[-size:]


def _clean_history(history: list[dict] | None) -> list[dict]:
    """Conserva solo los turnos válidos del historial del cliente.

    :param history: Turnos con ``role`` y ``content``
    :type history: list[dict] | None
    :return: Turnos de ``user`` y ``assistant`` con texto
    :rtype: list[dict]
    """
    cleaned = []
    for turn in history or []:
        role = turn.get("role")
        content = turn.get("content")
        if role in ALLOWED_HISTORY_ROLES and isinstance(content, str):
            cleaned.append({"role": role, "content": content})
    return cleaned
