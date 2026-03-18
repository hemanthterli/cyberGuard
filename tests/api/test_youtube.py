from app.services import youtube_service
from app.services.errors import ServiceError
from app.services.types import ProcessedResult


def test_youtube_success(client, monkeypatch):
    def fake_process(_url):
        return ProcessedResult(text="captions", input_type="url", source_url="https://youtube.com", size_bytes=None)

    monkeypatch.setattr(youtube_service, "process_youtube_url", fake_process)
    response = client.post("/youtube", json={"url": "https://www.youtube.com/watch?v=abc"})
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["text"] == "captions"


def test_youtube_invalid_input(client):
    response = client.post(
        "/youtube",
        json={"url": "not-a-url"},
    )
    assert response.status_code == 422


def test_youtube_edge_case_empty_url(client):
    response = client.post("/youtube", json={"url": ""})
    assert response.status_code == 422


def test_youtube_service_failure(client, monkeypatch):
    def fake_process(_url):
        raise ServiceError("boom", code="youtube_failed", status_code=502)

    monkeypatch.setattr(youtube_service, "process_youtube_url", fake_process)
    response = client.post("/youtube", json={"url": "https://www.youtube.com/watch?v=abc"})
    assert response.status_code == 502
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "youtube_failed"
