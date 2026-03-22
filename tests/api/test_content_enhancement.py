from app.services import content_enhancement_service
from app.services.errors import ServiceError
from app.services.types import ProcessedResult


def test_content_enhancement_success(client, monkeypatch):
    def fake_enhance(_payload):
        return ProcessedResult(text="clean", input_type="json", source_url=None, size_bytes=4)

    monkeypatch.setattr(content_enhancement_service, "enhance_content", fake_enhance)
    response = client.post(
        "/content-enhancement",
        json={
            "source_type": "news_article",
            "source": "https://example.com",
            "content": "raw content",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["text"] == "clean"


def test_content_enhancement_invalid_input(client):
    response = client.post(
        "/content-enhancement",
        json={"source": "https://example.com", "content": "raw"},
    )
    assert response.status_code == 422


def test_content_enhancement_edge_case_empty_content(client, monkeypatch):
    def fake_enhance(_payload):
        raise ServiceError("Empty content", code="invalid_input", status_code=400)

    monkeypatch.setattr(content_enhancement_service, "enhance_content", fake_enhance)
    response = client.post(
        "/content-enhancement",
        json={
            "source_type": "news_article",
            "source": "https://example.com",
            "content": "   ",
        },
    )
    assert response.status_code == 400


def test_content_enhancement_service_failure(client, monkeypatch):
    def fake_enhance(_payload):
        raise ServiceError("Model failed", code="model_failed", status_code=502)

    monkeypatch.setattr(content_enhancement_service, "enhance_content", fake_enhance)
    response = client.post(
        "/content-enhancement",
        json={
            "source_type": "news_article",
            "content": "raw content",
        },
    )
    assert response.status_code == 502
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "model_failed"
