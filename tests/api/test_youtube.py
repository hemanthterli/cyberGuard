from app.services import youtube_service
from app.services.errors import ServiceError
from app.services.types import ProcessedResult


def test_youtube_success(client, set_api_key, monkeypatch):
    def fake_process(_payload):
        return ProcessedResult(text="captions", input_type="url", source_url="https://youtube.com", size_bytes=None)

    monkeypatch.setattr(youtube_service, "process_youtube", fake_process)
    response = client.post("/youtube", json={"url": "https://www.youtube.com/watch?v=abc"}, headers=set_api_key)
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["text"] == "captions"


def test_youtube_invalid_input(client, set_api_key):
    response = client.post(
        "/youtube",
        json={"text": "hi", "url": "https://www.youtube.com/watch?v=abc"},
        headers=set_api_key,
    )
    assert response.status_code == 422


def test_youtube_auth_failure(client, monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key")
    response = client.post("/youtube", json={"text": "abc123"})
    assert response.status_code == 401


def test_youtube_edge_case_empty_text(client, set_api_key):
    response = client.post("/youtube", json={"text": "   "}, headers=set_api_key)
    assert response.status_code == 400


def test_youtube_service_failure(client, set_api_key, monkeypatch):
    def fake_process(_payload):
        raise ServiceError("boom", code="youtube_failed", status_code=502)

    monkeypatch.setattr(youtube_service, "process_youtube", fake_process)
    response = client.post("/youtube", json={"text": "abc123"}, headers=set_api_key)
    assert response.status_code == 502
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "youtube_failed"
