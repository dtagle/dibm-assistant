"""Pruebas de la clave por cliente, el límite de peticiones y la página (spec 04).

El límite usa el reloj inyectado (``TickingClock``): la prueba lo hace avanzar
en lugar de esperar.
"""

import re

from app.config import Settings
from app.tracing import Tracer
from tests.conftest import TEST_API_KEY, TEST_CLIENT_NAME, read_log_events

ID_QUESTION = "Cuéntame del documento 2025-12 por favor"
WRONG_KEY = "wrong-secret-key-987654321"


def test_client_name_is_logged_in_runs_and_audits_but_the_key_never_is(
    make_secure_client, capfd
):
    api = make_secure_client(api_key=TEST_API_KEY)
    assert api.post("/ask", json={"question": ID_QUESTION}).status_code == 200
    output = capfd.readouterr().out
    events = read_log_events(output)
    runs = [event for event in events if event["event"] == "agent_run"]
    audits = [event for event in events if event["event"] == "audit"]
    assert runs[0]["client"] == TEST_CLIENT_NAME
    assert audits[0]["client"] == TEST_CLIENT_NAME
    assert TEST_API_KEY not in output


def test_rejected_key_is_not_echoed_in_the_response_or_the_log(
    make_secure_client, capfd
):
    api = make_secure_client(api_key=WRONG_KEY)
    response = api.post("/ask", json={"question": ID_QUESTION})
    output = capfd.readouterr().out
    assert response.status_code == 401
    assert WRONG_KEY not in response.text
    assert WRONG_KEY not in output
    assert TEST_API_KEY not in output


def test_retry_after_counts_the_seconds_left_in_the_minute(
    make_secure_client, ticking_clock
):
    api = make_secure_client(api_key=TEST_API_KEY, RATE_LIMIT_PER_MINUTE="2")
    assert api.post("/ask", json={"question": "Hola"}).status_code == 200
    ticking_clock.advance(20)
    assert api.post("/ask", json={"question": "Hola"}).status_code == 200
    limited = api.post("/ask", json={"question": "Hola"})
    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "40"


def test_trace_metadata_carries_the_client_name(monkeypatch):
    recorded = {}

    def fake_traceable(**options):
        recorded.update(options)
        return lambda func: func

    tracer = Tracer(Settings(), env={})
    monkeypatch.setattr(tracer, "_traceable", fake_traceable)
    wrapped = tracer.wrap(
        lambda: "ok", "agent_run", "chain", "r-1", client=TEST_CLIENT_NAME
    )
    assert wrapped() == "ok"
    assert recorded["metadata"] == {"request_id": "r-1", "client": TEST_CLIENT_NAME}


def test_home_page_keeps_the_key_in_session_storage_and_sends_it_as_a_header(
    make_secure_client,
):
    page = make_secure_client().get("/").text
    key_field = re.search(r'<input[^>]*data-testid="api-key"[^>]*>', page)
    assert key_field is not None
    assert 'type="password"' in key_field.group(0)
    assert "sessionStorage" in page
    assert "localStorage" not in page
    assert "X-API-Key" in page
    assert TEST_API_KEY not in page


def test_home_page_explains_rejected_keys_and_rate_limits_in_spanish(
    make_secure_client,
):
    page = make_secure_client().get("/").text
    assert "Clave inválida" in page
    assert "Demasiadas preguntas; espera" in page
    assert "Retry-After" in page
