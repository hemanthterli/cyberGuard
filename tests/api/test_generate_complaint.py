from app.services import complaint_draft_service
from app.services.errors import ServiceError


def test_generate_complaint_success(client, monkeypatch):
    def fake_generate(_payload):
        return "Complaint letter text"

    monkeypatch.setattr(complaint_draft_service, "generate_complaint_letter", fake_generate)
    response = client.post(
        "/generate-complaint",
        json={
            "summary": "Summary",
            "detected_phrases": ["phrase"],
            "applicable_laws": [{"law": "Act", "description": "Desc"}],
            "recommended_actions": ["Action"],
        },
    )
    assert response.status_code == 200
    assert response.text == "Complaint letter text"
    assert response.headers["content-type"].startswith("text/plain")


def test_generate_complaint_invalid_input(client):
    response = client.post("/generate-complaint", json={"summary": ""})
    assert response.status_code == 422


def test_generate_complaint_service_failure(client, monkeypatch):
    def fake_generate(_payload):
        raise ServiceError("boom", code="model_failed", status_code=502)

    monkeypatch.setattr(complaint_draft_service, "generate_complaint_letter", fake_generate)
    response = client.post(
        "/generate-complaint",
        json={
            "summary": "Summary",
            "detected_phrases": ["phrase"],
            "applicable_laws": [{"law": "Act", "description": "Desc"}],
            "recommended_actions": ["Action"],
        },
    )
    assert response.status_code == 502
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "model_failed"
