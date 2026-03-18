from app.services import audio_service
from app.services.errors import ServiceError
from app.services.types import ProcessedResult


def test_audio_success(client, monkeypatch):
    def fake_process(_audio_bytes):
        return ProcessedResult(text="ok", input_type="file", source_url=None, size_bytes=2)

    monkeypatch.setattr(audio_service, "process_audio_bytes", fake_process)
    response = client.post(
        "/audio",
        files={"file": ("audio.mp3", b"data", "audio/mpeg")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["text"] == "ok"


def test_audio_invalid_input(client):
    response = client.post(
        "/audio",
        files={"file": ("audio.txt", b"data", "text/plain")},
    )
    assert response.status_code == 400


def test_audio_edge_case_empty_file(client):
    response = client.post(
        "/audio",
        files={"file": ("audio.mp3", b"", "audio/mpeg")},
    )
    assert response.status_code == 400


def test_audio_service_failure(client, monkeypatch):
    def fake_process(_audio_bytes):
        raise ServiceError("boom", code="service_failed", status_code=502)

    monkeypatch.setattr(audio_service, "process_audio_bytes", fake_process)
    response = client.post(
        "/audio",
        files={"file": ("audio.mp3", b"data", "audio/mpeg")},
    )
    assert response.status_code == 502
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "service_failed"
