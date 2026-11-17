"""Fixtures compartidas: un catálogo pequeño propio y la API con dependencias inyectadas

Las pruebas nunca leen ``data/publications.json``: usan cuatro publicaciones de
ejemplo para no romperse cuando se actualiza el snapshot.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.catalog import load_catalog
from app.config import load_settings
from app.llm import FakeLLM
from app.main import create_app

PAGE_URL = "https://www.banxico.org.mx/DIBM/web/documento/visor.html?clave={}"


def make_publication(pub_id, year, date, title, authors, **extra):
    """Arma una publicación con la forma del snapshot.

    :param pub_id: Clave del documento
    :type pub_id: str
    :param year: Año de la clave
    :type year: int
    :param date: Fecha de publicación (ISO)
    :type date: str
    :param title: Título en español
    :type title: str
    :param authors: Autores «Nombre Apellido»
    :type authors: list[str]
    :return: La publicación
    :rtype: dict
    """
    publication = {
        "id": pub_id,
        "title": title,
        "title_en": "",
        "authors": authors,
        "year": year,
        "date": date,
        "abstract": "",
        "abstract_en": "",
        "jel": [],
        "topics": [],
        "keywords": [],
        "language": "Español",
        "page_url": PAGE_URL.format(pub_id),
        "pdf_url": f"https://www.banxico.org.mx/dibm/{pub_id}.pdf",
    }
    publication.update(extra)
    return publication


SAMPLE_PUBLICATIONS = [
    make_publication(
        "2025-12",
        2025,
        "2026-01-15",
        "Inflación y expectativas en México",
        ["Ana García López", "Luis Pérez"],
        title_en="Inflation and expectations in Mexico",
        abstract="Estudiamos las expectativas de inflación de los hogares.",
        abstract_en="We study household inflation expectations.",
        jel=["E31"],
        topics=["Macroeconomía: Inflación"],
        keywords=["Inflación", "Expectativas"],
    ),
    make_publication(
        "2025-03",
        2025,
        "2025-04-10",
        "Mercado laboral y salarios",
        ["Sofía Núñez"],
        abstract="Analizamos la política salarial y el empleo formal.",
        topics=["Mercado laboral"],
    ),
    make_publication(
        "2024-07",
        2024,
        "2024-08-01",
        "Política monetaria y tipo de cambio",
        ["Luis Pérez"],
        abstract_en="We study the exchange rate pass-through.",
    ),
    make_publication(
        "1981-37 T2",
        1981,
        "1981-12-01",
        "Notas sobre la balanza de pagos",
        ["Carlos Ortiz"],
    ),
]

SAMPLE_TITLES = [publication["title"] for publication in SAMPLE_PUBLICATIONS]

# Clave de prueba (spec 04): no es un secreto real, solo vive en las pruebas.
TEST_CLIENT_NAME = "test-client"
TEST_API_KEY = "test-key-0123456789abcdef"
TEST_API_KEYS = f"{TEST_CLIENT_NAME}:{TEST_API_KEY}"
# Las pruebas de sesiones anteriores hacen muchas peticiones: el límite por
# omisión de las fixtures es alto para que no les estorbe.
SECURED_ENV = {"API_KEYS": TEST_API_KEYS, "RATE_LIMIT_PER_MINUTE": "1000"}
KEY_HEADERS = {"X-API-Key": TEST_API_KEY}


@pytest.fixture
def write_snapshot(tmp_path):
    """Escribe una lista de publicaciones en un archivo JSON temporal.

    :return: Función que recibe la lista y devuelve la ruta del archivo
    :rtype: callable
    """

    def write(publications, name="publications.json"):
        path = tmp_path / name
        path.write_text(json.dumps(publications, ensure_ascii=False), "utf-8")
        return path

    return write


@pytest.fixture
def snapshot_path(write_snapshot):
    """Ruta del snapshot de ejemplo con cuatro publicaciones."""
    return write_snapshot(SAMPLE_PUBLICATIONS)


@pytest.fixture
def catalog(snapshot_path):
    """Catálogo cargado desde el snapshot de ejemplo."""
    return load_catalog(snapshot_path)


@pytest.fixture
def make_client(snapshot_path, catalog):
    """Crea un cliente de la API con el catálogo de ejemplo y el modelo simulado.

    :return: Función que recibe variables de entorno extra y devuelve un TestClient
    :rtype: callable
    """

    def build(**env):
        settings = load_settings(
            {"PUBLICATIONS_PATH": str(snapshot_path), **SECURED_ENV, **env}
        )
        application = create_app(
            settings=settings,
            catalog=catalog,
            llm_factory=lambda *_args, **_kwargs: FakeLLM(catalog.surnames()),
        )
        return TestClient(application, headers=KEY_HEADERS)

    return build


@pytest.fixture
def client(make_client):
    """Cliente de la API con la configuración por omisión."""
    return make_client()


FIXED_NOW = datetime(2026, 11, 16, 12, 0, 0, tzinfo=timezone.utc)


class FakeClock:
    """Reloj fijo para pruebas deterministas.

    ``now()`` siempre da la misma hora en UTC; ``monotonic()`` solo avanza cuando
    la prueba llama ``advance()``.
    """

    def __init__(self, now=FIXED_NOW):
        """Crea el reloj detenido en ``now``.

        :param now: Hora fija que devuelve ``now()``
        :type now: datetime.datetime
        """
        self._now = now
        self._seconds = 1000.0

    def now(self):
        """Devuelve la hora fija.

        :return: Hora en UTC
        :rtype: datetime.datetime
        """
        return self._now

    def monotonic(self):
        """Devuelve los segundos acumulados.

        :return: Segundos del reloj monótono
        :rtype: float
        """
        return self._seconds

    def advance(self, seconds):
        """Hace avanzar el reloj monótono.

        :param seconds: Segundos a avanzar
        :type seconds: float
        """
        self._seconds += seconds


class SlowLLM:
    """Modelo simulado que tarda ``seconds`` en el reloj fijo por cada llamada.

    :param inner: Modelo que decide la respuesta
    :type inner: FakeLLM
    :param clock: Reloj que se hace avanzar
    :type clock: FakeClock
    :param seconds: Segundos por llamada
    :type seconds: float
    """

    def __init__(self, inner, clock, seconds):
        """Guarda el modelo, el reloj y la demora."""
        self._inner = inner
        self._clock = clock
        self._seconds = seconds

    def complete(self, messages):
        """Avanza el reloj y delega en el modelo simulado.

        :param messages: Conversación
        :type messages: list[dict]
        :return: La respuesta del modelo simulado
        :rtype: Completion
        """
        self._clock.advance(self._seconds)
        return self._inner.complete(messages)


SECRET_FAILURE_DETAIL = "database password is hunter2"


class FailingLLM:
    """Modelo que siempre truena con un mensaje que no debe salir al log."""

    def complete(self, messages):
        """Lanza un error inesperado.

        :param messages: Conversación (no se usa)
        :type messages: list[dict]
        :raises RuntimeError: Siempre
        """
        raise RuntimeError(f"{SECRET_FAILURE_DETAIL} ({len(messages)} messages)")


@pytest.fixture
def clock():
    """Reloj fijo compartido por la API y la prueba."""
    return FakeClock()


@pytest.fixture
def make_observed_client(snapshot_path, catalog, clock):
    """Crea un cliente de la API con reloj fijo y, si se pide, otro modelo.

    Cada llamada arma una aplicación nueva, con sus propias métricas.
    El cliente no relanza los errores del servidor: así se ve la respuesta 500.

    :return: Función que recibe ``llm``, ``seconds_per_call`` y variables de
        entorno extra, y devuelve un TestClient
    :rtype: callable
    """

    def build(llm=None, seconds_per_call=0.0, **env):
        settings = load_settings(
            {"PUBLICATIONS_PATH": str(snapshot_path), **SECURED_ENV, **env}
        )
        model = llm or SlowLLM(FakeLLM(catalog.surnames()), clock, seconds_per_call)
        application = create_app(
            settings=settings,
            catalog=catalog,
            llm_factory=lambda *_args, **_kwargs: model,
            clock=clock,
        )
        return TestClient(
            application, raise_server_exceptions=False, headers=KEY_HEADERS
        )

    return build


SMALL_MODEL = "@cf/meta/llama-3.1-8b-instruct-fast"
LARGE_MODEL = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
# Precios de prueba en USD por millón de tokens: redondos para calcular a mano.
TEST_PRICES = {
    "currency": "USD",
    "unit": "per million tokens",
    "models": {
        "fake": {"input": 0.0, "output": 0.0},
        SMALL_MODEL: {"input": 1.0, "output": 2.0},
        LARGE_MODEL: {"input": 10.0, "output": 20.0},
    },
}


def expected_cost(model, input_tokens, output_tokens):
    """Calcula el costo esperado con los precios de prueba.

    :param model: Nombre del modelo
    :type model: str
    :param input_tokens: Tokens de entrada
    :type input_tokens: int
    :param output_tokens: Tokens de salida
    :type output_tokens: int
    :return: Costo en USD
    :rtype: float
    """
    price = TEST_PRICES["models"][model]
    return (input_tokens * price["input"] + output_tokens * price["output"]) / 1e6


@pytest.fixture
def prices_path(tmp_path):
    """Ruta de un archivo de precios de prueba (no el de ``data/``)."""
    path = tmp_path / "model_prices.json"
    path.write_text(json.dumps(TEST_PRICES), "utf-8")
    return path


@pytest.fixture
def make_cost_client(snapshot_path, catalog, prices_path, clock):
    """Crea un cliente de la API con los precios de prueba.

    Si no se pasa ``llm_factory`` se usa la fábrica real del producto, que con
    ``MODEL_PROVIDER=fake`` crea los modelos simulados con nombre de modelo.

    :return: Función que recibe ``llm_factory`` y variables de entorno extra, y
        devuelve un TestClient
    :rtype: callable
    """

    def build(llm_factory=None, **env):
        settings = load_settings(
            {
                "PUBLICATIONS_PATH": str(snapshot_path),
                "PRICES_PATH": str(prices_path),
                **SECURED_ENV,
                **env,
            }
        )
        application = create_app(
            settings=settings, catalog=catalog, llm_factory=llm_factory, clock=clock
        )
        return TestClient(
            application, raise_server_exceptions=False, headers=KEY_HEADERS
        )

    return build


class TickingClock(FakeClock):
    """Reloj fijo en el que ``advance()`` mueve ``now()`` y ``monotonic()``.

    Así el límite de peticiones funciona igual use la hora o el reloj monótono.
    """

    def advance(self, seconds):
        """Hace avanzar los dos relojes.

        :param seconds: Segundos a avanzar
        :type seconds: float
        """
        super().advance(seconds)
        self._now += timedelta(seconds=seconds)


@pytest.fixture
def ticking_clock():
    """Reloj que la prueba hace avanzar para el límite de peticiones."""
    return TickingClock()


@pytest.fixture
def make_secure_client(snapshot_path, catalog, ticking_clock):
    """Crea un cliente de la API que manda solo la clave que se le pide.

    :return: Función que recibe ``api_key`` (``None``: sin encabezado) y
        variables de entorno extra, y devuelve un TestClient
    :rtype: callable
    """

    def build(api_key=None, **env):
        settings = load_settings(
            {
                "PUBLICATIONS_PATH": str(snapshot_path),
                "API_KEYS": TEST_API_KEYS,
                **env,
            }
        )
        application = create_app(
            settings=settings,
            catalog=catalog,
            llm_factory=lambda *_args, **_kwargs: FakeLLM(catalog.surnames()),
            clock=ticking_clock,
        )
        headers = {"X-API-Key": api_key} if api_key is not None else {}
        return TestClient(
            application, raise_server_exceptions=False, headers=headers
        )

    return build


def read_log_events(text):
    """Extrae los eventos JSON del texto que salió por la salida estándar.

    :param text: Salida estándar capturada
    :type text: str
    :return: Eventos (diccionarios con ``event``), en orden
    :rtype: list[dict]
    """
    events = []
    for line in text.splitlines():
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if isinstance(data, dict) and "event" in data:
            events.append(data)
    return events
