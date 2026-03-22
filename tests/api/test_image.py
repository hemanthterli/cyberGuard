from app.services import image_service
from app.services.errors import ServiceError
from app.services.types import ProcessedResult


def test_image_success(client, monkeypatch):
    def fake_process(_image_bytes, _content_type, _filename):
        return ProcessedResult(text="ok", input_type="file", source_url=None, size_bytes=10)

    monkeypatch.setattr(image_service, "process_image_bytes", fake_process)
    response = client.post(
        "/image",
        files={"file": ("img.png", b"data", "image/png")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["text"] == "ok"


def test_image_invalid_input(client):
    response = client.post(
        "/image",
        files={"file": ("img.gif", b"data", "image/gif")},
    )
    assert response.status_code == 400


def test_image_edge_case_empty_file(client):
    response = client.post(
        "/image",
        files={"file": ("img.png", b"", "image/png")},
    )
    assert response.status_code == 400


def test_image_service_failure(client, monkeypatch):
    def fake_process(_image_bytes, _content_type, _filename):
        raise ServiceError("boom", code="ocr_failed", status_code=422)

    monkeypatch.setattr(image_service, "process_image_bytes", fake_process)
    response = client.post(
        "/image",
        files={"file": ("img.png", b"data", "image/png")},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "ocr_failed"
