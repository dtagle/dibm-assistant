"""Pruebas del log JSON, las métricas y las trazas (spec 02).

El log sale por la salida estándar, una línea JSON por evento; se captura con
``capfd`` y se lee con ``read_log_events``.
"""

import os
from datetime import datetime

from tests.conftest import (
    FIXED_NOW,
    SECRET_FAILURE_DETAIL,
    FailingLLM,
    read_log_events,
)

LATEST_QUESTION = "¿Cuáles son las últimas publicaciones?"
ID_QUESTION = "Cuéntame del documento 2025-12 por favor"


def _events(capfd, name):
    """Eventos del log con ese nombre."""
    events = read_log_events(capfd.readouterr().out)
    return [event for event in events if event["event"] == name]


def test_request_event_is_logged_once_with_method_path_status_and_latency(
    make_observed_client, capfd
):
    api = make_observed_client(seconds_per_call=0.25)
    api.post("/ask", json={"question": LATEST_QUESTION})
    requests = _events(capfd, "request")
    assert len(requests) == 1
    event = requests[0]
    assert (event["method"], event["path"], event["status"]) == ("POST", "/ask", 200)
    assert event["latency_ms"] == 500


def test_log_lines_carry_utc_timestamp_service_and_request_id(
    make_observed_client, capfd
):
    api = make_observed_client()
    api.post(
        "/ask", json={"question": LATEST_QUESTION}, headers={"X-Request-ID": "r-1"}
    )
    events = read_log_events(capfd.readouterr().out)
    assert {e["event"] for e in events} >= {"request", "agent_run", "audit"}
    for event in events:
        timestamp = datetime.fromisoformat(event["ts"].replace("Z", "+00:00"))
        assert timestamp == FIXED_NOW
        assert timestamp.utcoffset().total_seconds() == 0
        assert event["service"] == "dibm-assistant"
        assert event["request_id"] == "r-1"


def test_service_name_comes_from_configuration(make_observed_client, capfd):
    make_observed_client(SERVICE_NAME="dibm-staging").get("/health")
    assert _events(capfd, "request")[0]["service"] == "dibm-staging"


def test_agent_run_event_reports_counts_without_question_or_answer_text(
    make_observed_client, capfd
):
    api = make_observed_client()
    history = [{"role": "user", "content": "Hola"}]
    body = api.post("/ask", json={"question": ID_QUESTION, "history": history}).json()
    output = capfd.readouterr().out
    run = [e for e in read_log_events(output) if e["event"] == "agent_run"][0]
    assert run["question_chars"] == len(ID_QUESTION)
    assert run["history_messages"] == 1
    assert run["steps"] == body["steps"] == 2
    assert run["tools"] == ["get_publication"]
    assert run["input_tokens"] == body["input_tokens"]
    assert run["output_tokens"] == body["output_tokens"]
    assert run["stopped"] is False
    assert ID_QUESTION not in output
    assert "Inflación y expectativas en México" not in output


def test_each_tool_call_is_audited_with_its_arguments(make_observed_client, capfd):
    make_observed_client().post("/ask", json={"question": ID_QUESTION})
    audits = _events(capfd, "audit")
    assert len(audits) == 1
    assert audits[0]["action"] == "tool_call"
    assert audits[0]["tool"] == "get_publication"
    assert audits[0]["args"] == {"publication_id": "2025-12"}


def test_error_event_reports_the_error_type_without_the_message(
    make_observed_client, capfd
):
    api = make_observed_client(llm=FailingLLM())
    response = api.post(
        "/ask", json={"question": LATEST_QUESTION}, headers={"X-Request-ID": "e-1"}
    )
    output = capfd.readouterr().out
    errors = [e for e in read_log_events(output) if e["event"] == "error"]
    assert response.status_code == 500
    assert len(errors) == 1
    assert errors[0]["request_id"] == "e-1"
    assert "RuntimeError" in errors[0].values()
    assert SECRET_FAILURE_DETAIL not in output
    assert SECRET_FAILURE_DETAIL not in response.text


def test_error_rate_counts_failed_requests(make_observed_client):
    healthy = make_observed_client()
    healthy.post("/ask", json={"question": LATEST_QUESTION})
    assert healthy.get("/metrics").json()["error_rate"] == 0
    failing = make_observed_client(llm=FailingLLM())
    failing.get("/health")
    failing.post("/ask", json={"question": LATEST_QUESTION})
    assert failing.get("/metrics").json()["error_rate"] == 0.5


def test_metrics_report_the_process_id_and_slo_target(make_observed_client):
    metrics = make_observed_client(SLO_P95_MS="750").get("/metrics").json()
    assert metrics["pid"] == os.getpid()
    assert set(metrics) >= {"requests", "error_rate", "latency_ms", "tokens", "slo"}
    assert metrics["slo"]["p95_ms_target"] == 750


def test_home_page_shows_the_request_id(client):
    assert "request_id" in client.get("/").text


def test_langsmith_api_key_never_appears_in_logs(
    make_observed_client, capfd, monkeypatch
):
    secret = "lsv2-test-key-that-must-stay-hidden"
    monkeypatch.setenv("LANGSMITH_API_KEY", secret)
    api = make_observed_client(LANGSMITH_API_KEY=secret)
    api.post("/ask", json={"question": LATEST_QUESTION})
    output = capfd.readouterr().out
    assert read_log_events(output)
    assert secret not in output


def test_tracing_without_api_key_keeps_the_assistant_working(
    make_observed_client, monkeypatch
):
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("LANGCHAIN_API_KEY", raising=False)
    api = make_observed_client(LANGSMITH_TRACING="true")
    response = api.post("/ask", json={"question": LATEST_QUESTION})
    assert response.status_code == 200
    assert response.json()["tools_used"] == ["latest_publications"]
