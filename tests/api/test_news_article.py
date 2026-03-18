from app.services import news_service
from app.services.errors import ServiceError
from app.services.types import ProcessedResult


def test_news_article_success(client, set_api_key, monkeypatch):
    def fake_process(_payload):
        return ProcessedResult(text="article", input_type="url", source_url="https://example.com", size_bytes=12)

    monkeypatch.setattr(news_service, "process_news_article", fake_process)
    response = client.post(
        "/news-article",
        json={"url": "https://example.com/article"},
        headers=set_api_key,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["text"] == "article"


def test_news_article_invalid_input(client, set_api_key):
    response = client.post(
        "/news-article",
        json={"text": "hi", "url": "https://example.com/article"},
        headers=set_api_key,
    )
    assert response.status_code == 422


def test_news_article_auth_failure(client, monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key")
    response = client.post("/news-article", json={"text": "hi"})
    assert response.status_code == 401


def test_news_article_edge_case_empty_text(client, set_api_key):
    response = client.post("/news-article", json={"text": "   "}, headers=set_api_key)
    assert response.status_code == 400


def test_news_article_service_failure(client, set_api_key, monkeypatch):
    def fake_process(_payload):
        raise ServiceError("boom", code="fetch_failed", status_code=502)

    monkeypatch.setattr(news_service, "process_news_article", fake_process)
    response = client.post("/news-article", json={"text": "hi"}, headers=set_api_key)
    assert response.status_code == 502
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "fetch_failed"
