"""Pruebas de las rutas de la API y de la página web."""

import os


def test_health_reports_ok_and_the_publication_count(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert (body["status"], body["pid"]) == ("ok", os.getpid())
    assert body["publications"] == 4


def test_home_page_has_the_form_and_paints_answers_with_text_content(client):
    response = client.get("/")
    page = response.text
    assert response.status_code == 200
    assert "DIBM Assistant · Banco de México" in page
    for test_id in ("question", "send", "answer"):
        assert f'data-testid="{test_id}"' in page
    assert "textContent" in page
    assert "innerHTML" not in page


def test_history_sent_by_the_client_is_accepted(client):
    history = [
        {"role": "user", "content": "Hola"},
        {"role": "assistant", "content": "Pregúntame por un autor."},
    ]
    response = client.post("/ask", json={"question": "Hola", "history": history})
    assert response.status_code == 200
    body = response.json()
    for field in ("answer", "steps", "tools_used", "input_tokens", "output_tokens"):
        assert field in body
