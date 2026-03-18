from app.services import text_service
from app.services.errors import ServiceError
from app.services.types import ProcessedResult


def test_text_success(client, set_api_key, monkeypatch):
    def fake_process(_payload):
        return ProcessedResult(text="hello", input_type="text", source_url=None, size_bytes=5)

    monkeypatch.setattr(text_service, "process_text", fake_process)
    response = client.post("/text", json={"text": "hello"}, headers=set_api_key)
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["text"] == "hello"


def test_text_invalid_input(client, set_api_key):
    response = client.post(
        "/text",
        json={"text": "hi", "url": "https://example.com"},
        headers=set_api_key,
    )
    assert response.status_code == 422


def test_text_auth_failure(client, monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key")
    response = client.post("/text", json={"text": "hello"})
    assert response.status_code == 401


def test_text_edge_case_empty_text(client, set_api_key):
    response = client.post("/text", json={"text": "   "}, headers=set_api_key)
    assert response.status_code == 400


def test_text_service_failure(client, set_api_key, monkeypatch):
    def fake_process(_payload):
        raise ServiceError("boom", code="fetch_failed", status_code=502)

    monkeypatch.setattr(text_service, "process_text", fake_process)
    response = client.post("/text", json={"text": "hi"}, headers=set_api_key)
    assert response.status_code == 502
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "fetch_failed"
