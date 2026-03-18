import pytest

from app.services import audio_service
from app.services.errors import ServiceError
from app.services.types import ProcessedResult


def test_audio_success(client, set_api_key, monkeypatch):
    def fake_process(_payload):
        return ProcessedResult(text="ok", input_type="text", source_url=None, size_bytes=2)

    monkeypatch.setattr(audio_service, "process_audio", fake_process)
    response = client.post("/audio", json={"text": "ok"}, headers=set_api_key)
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["text"] == "ok"


def test_audio_invalid_input(client, set_api_key):
    response = client.post(
        "/audio",
        json={"text": "hi", "url": "https://example.com/audio.mp3"},
        headers=set_api_key,
    )
    assert response.status_code == 422


def test_audio_auth_failure(client, monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key")
    response = client.post("/audio", json={"text": "hi"})
    assert response.status_code == 401


def test_audio_edge_case_empty_text(client, set_api_key):
    response = client.post("/audio", json={"text": "   "}, headers=set_api_key)
    assert response.status_code == 400


def test_audio_service_failure(client, set_api_key, monkeypatch):
    def fake_process(_payload):
        raise ServiceError("boom", code="service_failed", status_code=502)

    monkeypatch.setattr(audio_service, "process_audio", fake_process)
    response = client.post("/audio", json={"text": "hi"}, headers=set_api_key)
    assert response.status_code == 502
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "service_failed"
