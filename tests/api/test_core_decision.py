from app.services import core_decision_service
from app.services.errors import ServiceError
from app.schemas.responses import CoreDecisionData


def test_core_decision_success(client, monkeypatch):
    def fake_analyze(_payload):
        return CoreDecisionData(
            bullying="yes",
            description="Short explanation",
            phrases="Bad phrase",
            source="https://example.com",
            impact_action="Report",
            core_cybercrime="Short cybercrime summary",
        )

    monkeypatch.setattr(core_decision_service, "analyze_bullying", fake_analyze)
    response = client.post(
        "/core-decision",
        json={
            "source": "https://example.com",
            "source_type": "text",
            "content": "bad content",
            "user_context": "context",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["bullying"] == "yes"
    assert body["data"]["core_cybercrime"] == "Short cybercrime summary"


def test_core_decision_invalid_input(client):
    response = client.post(
        "/core-decision",
        json={"source": "https://example.com", "source_type": "text"},
    )
    assert response.status_code == 422


def test_core_decision_edge_case_empty_content(client, monkeypatch):
    def fake_analyze(_payload):
        raise ServiceError("Empty content", code="invalid_input", status_code=400)

    monkeypatch.setattr(core_decision_service, "analyze_bullying", fake_analyze)
    response = client.post(
        "/core-decision",
        json={
            "source": "https://example.com",
            "source_type": "text",
            "content": "   ",
        },
    )
    assert response.status_code == 400


def test_core_decision_service_failure(client, monkeypatch):
    def fake_analyze(_payload):
        raise ServiceError("Model failed", code="model_failed", status_code=502)

    monkeypatch.setattr(core_decision_service, "analyze_bullying", fake_analyze)
    response = client.post(
        "/core-decision",
        json={
            "source": "https://example.com",
            "source_type": "text",
            "content": "bad content",
        },
    )
    assert response.status_code == 502
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "model_failed"
