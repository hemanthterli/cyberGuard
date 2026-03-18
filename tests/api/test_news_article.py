from app.services import news_service
from app.services.errors import ServiceError
from app.services.types import ProcessedResult


def test_news_article_success(client, monkeypatch):
    def fake_process(_url):
        return ProcessedResult(text="article", input_type="url", source_url="https://example.com", size_bytes=12)

    monkeypatch.setattr(news_service, "process_news_url", fake_process)
    response = client.post(
        "/news-article",
        json={"url": "https://example.com/article"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["text"] == "article"


def test_news_article_invalid_input(client):
    response = client.post(
        "/news-article",
        json={"url": "not-a-url"},
    )
    assert response.status_code == 422


def test_news_article_edge_case_empty_url(client):
    response = client.post("/news-article", json={"url": ""})
    assert response.status_code == 422


def test_news_article_service_failure(client, monkeypatch):
    def fake_process(_url):
        raise ServiceError("boom", code="fetch_failed", status_code=502)

    monkeypatch.setattr(news_service, "process_news_url", fake_process)
    response = client.post("/news-article", json={"url": "https://example.com/article"})
    assert response.status_code == 502
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "fetch_failed"
