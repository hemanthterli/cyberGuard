from app.services import image_service
from app.services.errors import ServiceError
from app.services.types import ProcessedResult


def test_image_success(client, set_api_key, monkeypatch):
    def fake_process(_payload):
        return ProcessedResult(text="ok", input_type="url", source_url="https://example.com", size_bytes=10)

    monkeypatch.setattr(image_service, "process_image", fake_process)
    response = client.post("/image", json={"url": "https://example.com/img.png"}, headers=set_api_key)
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["text"] == "ok"


def test_image_invalid_input(client, set_api_key):
    response = client.post(
        "/image",
        json={"text": "hi", "url": "https://example.com/img.png"},
        headers=set_api_key,
    )
    assert response.status_code == 422


def test_image_auth_failure(client, monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key")
    response = client.post("/image", json={"text": "hi"})
    assert response.status_code == 401


def test_image_edge_case_empty_text(client, set_api_key):
    response = client.post("/image", json={"text": "   "}, headers=set_api_key)
    assert response.status_code == 400


def test_image_service_failure(client, set_api_key, monkeypatch):
    def fake_process(_payload):
        raise ServiceError("boom", code="ocr_failed", status_code=422)

    monkeypatch.setattr(image_service, "process_image", fake_process)
    response = client.post("/image", json={"text": "hi"}, headers=set_api_key)
    assert response.status_code == 422
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "ocr_failed"
