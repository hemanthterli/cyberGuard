import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def set_api_key(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    monkeypatch.setenv("API_KEY", "test-key")
    return {"X-API-Key": "test-key"}


@pytest.fixture(autouse=True)
def clear_api_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("API_KEY", raising=False)
    yield
    monkeypatch.delenv("API_KEY", raising=False)
