from app.services import cyber_law_service
from app.services.errors import ServiceError
from app.schemas.responses import ComplaintLaw, ComplaintOutput


def _payload() -> dict:
    return {
        "content": "The user is facing impersonation and online abuse.",
        "core_decision": {
            "bullying": "yes",
            "description": "Online abuse detected",
            "phrases": "threat, fake profile",
            "source": "https://example.com/post/1",
            "impact_action": "File complaint",
            "core_cybercrime": "Impersonation and cyber harassment on social media",
        },
        "retrieved_laws": ["legacy snippet without metadata"],
        "language": "english",
        "location": "india",
    }


def test_get_cyber_laws_country_sufficient_no_fallback(client, monkeypatch):
    stage_calls: list[str] = []

    monkeypatch.setattr(cyber_law_service, "_build_gemini_client", lambda: (object(), object()))

    def fake_retrieve(query, location, stage):
        stage_calls.append(stage)
        assert stage == "country_rag"
        assert location == "india"
        return [
            cyber_law_service.LawCandidate("IT Act Section 66C", "Identity theft law", "https://law/66c", stage, 0.11),
            cyber_law_service.LawCandidate("IT Act Section 66D", "Cheating by personation", "https://law/66d", stage, 0.12),
            cyber_law_service.LawCandidate("IT Act Section 67", "Obscene material publication", "https://law/67", stage, 0.13),
        ]

    def fake_validate(*_args, **kwargs):
        return {"is_sufficient": True, "reason": "Enough relevant laws", "law_count": 3}

    def fake_route(*_args, **kwargs):
        return "proceed"

    def fake_synthesize(_client, _types, _content, _core_decision, law_candidates, _retrieved_laws_context, _stage_history):
        return ComplaintOutput(
            summary="Sufficient country laws.",
            detected_phrases=["threat"],
            applicable_laws=[
                ComplaintLaw(law=item.law, description=item.description, source=item.source)
                for item in law_candidates[:3]
            ],
            recommended_actions=["Report to platform"],
        )

    monkeypatch.setattr(cyber_law_service, "_retrieve_law_candidates", fake_retrieve)
    monkeypatch.setattr(cyber_law_service, "_validate_law_coverage", fake_validate)
    monkeypatch.setattr(cyber_law_service, "_decide_route", fake_route)
    monkeypatch.setattr(cyber_law_service, "_generate_final_response", fake_synthesize)

    response = client.post("/get-cyber-laws", json=_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert stage_calls == ["country_rag"]
    assert "summary" in body["data"]
    assert "detected_phrases" in body["data"]
    assert "applicable_laws" in body["data"]
    assert "recommended_actions" in body["data"]
    assert len(body["data"]["applicable_laws"]) == 3
    assert all(item["source"] for item in body["data"]["applicable_laws"])


def test_get_cyber_laws_country_insufficient_international_sufficient(client, monkeypatch):
    stage_calls: list[str] = []
    rewrites: list[str] = []

    monkeypatch.setattr(cyber_law_service, "_build_gemini_client", lambda: (object(), object()))

    def fake_retrieve(_query, _location, stage):
        stage_calls.append(stage)
        if stage == "country_rag":
            return [
                cyber_law_service.LawCandidate("IT Act Section 66C", "Identity theft law", "https://law/66c", stage, 0.11),
            ]
        if stage == "international_rag":
            return [
                cyber_law_service.LawCandidate("Computer Misuse Act 1990", "UK computer misuse law", "https://law/cma", stage, 0.21),
                cyber_law_service.LawCandidate("Budapest Convention", "International cybercrime framework", "https://law/budapest", stage, 0.22),
            ]
        return []

    def fake_validate(_client, _types, _query, _state, stage, *_args):
        if stage == "country_rag":
            return {"is_sufficient": False, "reason": "Need broader legal coverage", "law_count": 1}
        return {"is_sufficient": True, "reason": "Now sufficient", "law_count": 3}

    def fake_route(_client, _types, _validation, stage, _allowed):
        if stage == "country_rag":
            return "international_rag"
        return "proceed"

    def fake_rewrite(*_args, **kwargs):
        rewrites.append(kwargs["stage"])
        return f"enhanced {kwargs['original_query']}"

    def fake_synthesize(_client, _types, _content, _core_decision, law_candidates, _retrieved_laws_context, _stage_history):
        return ComplaintOutput(
            summary="International fallback added coverage.",
            detected_phrases=["fake profile"],
            applicable_laws=[
                ComplaintLaw(law=item.law, description=item.description, source=item.source)
                for item in law_candidates[:3]
            ],
            recommended_actions=["Keep evidence", "File complaint"],
        )

    monkeypatch.setattr(cyber_law_service, "_retrieve_law_candidates", fake_retrieve)
    monkeypatch.setattr(cyber_law_service, "_validate_law_coverage", fake_validate)
    monkeypatch.setattr(cyber_law_service, "_decide_route", fake_route)
    monkeypatch.setattr(cyber_law_service, "_rewrite_query", fake_rewrite)
    monkeypatch.setattr(cyber_law_service, "_generate_final_response", fake_synthesize)

    response = client.post("/get-cyber-laws", json=_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert stage_calls == ["country_rag", "international_rag"]
    assert rewrites == ["international_rag"]
    assert len(body["data"]["applicable_laws"]) == 3
    assert all(item["source"] for item in body["data"]["applicable_laws"])


def test_get_cyber_laws_search_fallback_invoked(client, monkeypatch):
    stage_calls: list[str] = []
    rewrites: list[str] = []
    search_called = {"value": False}

    monkeypatch.setattr(cyber_law_service, "_build_gemini_client", lambda: (object(), object()))

    def fake_retrieve(_query, _location, stage):
        stage_calls.append(stage)
        if stage == "country_rag":
            return [
                cyber_law_service.LawCandidate("IT Act Section 66C", "Identity theft law", "https://law/66c", stage, 0.11),
            ]
        if stage == "international_rag":
            return [
                cyber_law_service.LawCandidate("Computer Misuse Act 1990", "UK computer misuse law", "https://law/cma", stage, 0.21),
            ]
        return []

    def fake_validate(_client, _types, _query, _state, stage, *_args):
        if stage == "country_rag":
            return {"is_sufficient": False, "reason": "Need more", "law_count": 1}
        if stage == "international_rag":
            return {"is_sufficient": False, "reason": "Still below minimum", "law_count": 2}
        return {"is_sufficient": True, "reason": "Search covered remaining gap", "law_count": 3}

    def fake_route(_client, _types, _validation, stage, _allowed):
        if stage == "country_rag":
            return "international_rag"
        return "gemini_search"

    def fake_rewrite(*_args, **kwargs):
        rewrites.append(kwargs["stage"])
        return f"rewrite for {kwargs['stage']}"

    def fake_search(_client, _types, _query, _jurisdiction):
        search_called["value"] = True
        return [
            cyber_law_service.LawCandidate("GDPR Article 5", "Data protection principles", "https://law/gdpr-5", "gemini_search", 0.0),
            cyber_law_service.LawCandidate("CFAA", "US federal cyber offense law", "https://law/cfaa", "gemini_search", 1.0),
        ]

    def fake_synthesize(_client, _types, _content, _core_decision, law_candidates, _retrieved_laws_context, _stage_history):
        return ComplaintOutput(
            summary="Search fallback used.",
            detected_phrases=["threat"],
            applicable_laws=[
                ComplaintLaw(law=item.law, description=item.description, source=item.source)
                for item in law_candidates[:4]
            ],
            recommended_actions=["Escalate to authority"],
        )

    monkeypatch.setattr(cyber_law_service, "_retrieve_law_candidates", fake_retrieve)
    monkeypatch.setattr(cyber_law_service, "_validate_law_coverage", fake_validate)
    monkeypatch.setattr(cyber_law_service, "_decide_route", fake_route)
    monkeypatch.setattr(cyber_law_service, "_rewrite_query", fake_rewrite)
    monkeypatch.setattr(cyber_law_service, "_search_laws_with_google", fake_search)
    monkeypatch.setattr(cyber_law_service, "_generate_final_response", fake_synthesize)

    response = client.post("/get-cyber-laws", json=_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert stage_calls == ["country_rag", "international_rag"]
    assert rewrites == ["international_rag", "gemini_search"]
    assert search_called["value"] is True
    assert len(body["data"]["applicable_laws"]) >= 3
    assert all(item["source"] for item in body["data"]["applicable_laws"])


def test_get_cyber_laws_partial_with_warning_when_less_than_three(client, monkeypatch):
    monkeypatch.setattr(cyber_law_service, "_build_gemini_client", lambda: (object(), object()))

    def fake_retrieve(_query, _location, stage):
        if stage == "country_rag":
            return [
                cyber_law_service.LawCandidate("IT Act Section 66C", "Identity theft law", "https://law/66c", stage, 0.11),
            ]
        return []

    def fake_validate(_client, _types, _query, _state, _stage, *_args):
        return {"is_sufficient": False, "reason": "Insufficient relevant sources", "law_count": 1}

    def fake_route(_client, _types, _validation, stage, _allowed):
        if stage == "country_rag":
            return "international_rag"
        return "gemini_search"

    def fake_rewrite(*_args, **kwargs):
        return kwargs["original_query"]

    def fake_search(*_args, **_kwargs):
        return []

    def fake_synthesize(_client, _types, _content, _core_decision, law_candidates, _retrieved_laws_context, _stage_history):
        return ComplaintOutput(
            summary="Only one applicable law found.",
            detected_phrases=["fake profile"],
            applicable_laws=[ComplaintLaw(law=law_candidates[0].law, description=law_candidates[0].description, source=law_candidates[0].source)],
            recommended_actions=["Proceed with available evidence"],
        )

    monkeypatch.setattr(cyber_law_service, "_retrieve_law_candidates", fake_retrieve)
    monkeypatch.setattr(cyber_law_service, "_validate_law_coverage", fake_validate)
    monkeypatch.setattr(cyber_law_service, "_decide_route", fake_route)
    monkeypatch.setattr(cyber_law_service, "_rewrite_query", fake_rewrite)
    monkeypatch.setattr(cyber_law_service, "_search_laws_with_google", fake_search)
    monkeypatch.setattr(cyber_law_service, "_generate_final_response", fake_synthesize)

    response = client.post("/get-cyber-laws", json=_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert len(body["data"]["applicable_laws"]) == 1
    assert "fewer than 3 relevant laws" in body["data"]["summary"].lower()


def test_get_cyber_laws_invalid_input(client):
    response = client.post("/get-cyber-laws", json={"content": "raw"})
    assert response.status_code == 422


def test_get_cyber_laws_service_failure(client, monkeypatch):
    def fake_analyze(_payload):
        raise ServiceError("boom", code="model_failed", status_code=502)

    monkeypatch.setattr(cyber_law_service, "analyze_cyber_laws", fake_analyze)
    response = client.post("/get-cyber-laws", json=_payload())
    assert response.status_code == 502
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "model_failed"
