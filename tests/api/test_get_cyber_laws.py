from app.services import cyber_law_service
from app.services.errors import ServiceError
from app.schemas.responses import ComplaintLaw, ComplaintOutput


def test_get_cyber_laws_success(client, monkeypatch):
    def fake_analyze(_payload):
        return ComplaintOutput(
            summary="Summary",
            detected_phrases=["phrase"],
            applicable_laws=[ComplaintLaw(law="Act", description="Desc")],
            recommended_actions=["Action"],
        )

    monkeypatch.setattr(cyber_law_service, "analyze_cyber_laws", fake_analyze)
    response = client.post(
        "/get-cyber-laws",
        json={
            "content": "raw content",
            "core_decision": {
                "bullying": "yes",
                "description": "desc",
                "phrases": "phrase",
                "source": "https://example.com",
                "impact_action": "Report",
                "core_cybercrime": "summary",
            },
            "retrieved_laws": ["law snippet"],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["summary"] == "Summary"


def test_get_cyber_laws_invalid_input(client):
    response = client.post("/get-cyber-laws", json={"content": "raw"})
    assert response.status_code == 422


def test_get_cyber_laws_service_failure(client, monkeypatch):
    def fake_analyze(_payload):
        raise ServiceError("boom", code="model_failed", status_code=502)

    monkeypatch.setattr(cyber_law_service, "analyze_cyber_laws", fake_analyze)
    response = client.post(
        "/get-cyber-laws",
        json={
            "content": "raw content",
            "core_decision": {
                "bullying": "yes",
                "description": "desc",
                "phrases": "phrase",
                "source": "https://example.com",
                "impact_action": "Report",
                "core_cybercrime": "summary",
            },
            "retrieved_laws": ["law snippet"],
        },
    )
    assert response.status_code == 502
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "model_failed"
