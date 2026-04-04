from types import SimpleNamespace

from app.schemas.responses import ComplaintLaw, ComplaintOutput
from app.services import cyber_law_service


class _DummyTypes:
    class GenerateContentConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs


def _make_client(response):
    models = SimpleNamespace(generate_content=lambda **_kwargs: response)
    return SimpleNamespace(models=models)


def test_search_uses_grounding_chunks_when_present(monkeypatch):
    grounding = SimpleNamespace(
        web_search_queries=["us cyber harassment defamation law"],
        grounding_chunks=[
            SimpleNamespace(web=SimpleNamespace(title="CFAA", uri="https://www.justice.gov/criminal-fraud/computer-fraud-and-abuse-act")),
            SimpleNamespace(web=SimpleNamespace(title="US Defamation Law", uri="https://www.law.cornell.edu/wex/defamation")),
        ],
    )
    response = SimpleNamespace(
        candidates=[
            SimpleNamespace(
                content=SimpleNamespace(parts=[SimpleNamespace(text="Results with grounding")]),
                grounding_metadata=grounding,
            )
        ]
    )

    client = _make_client(response)
    monkeypatch.setattr(cyber_law_service, "_trace", lambda *args, **kwargs: None)

    laws = cyber_law_service._search_laws_with_google(client, _DummyTypes, "query", "usa")

    assert len(laws) == 2
    assert laws[0].stage == "gemini_search"
    assert laws[0].source.startswith("https://")


def test_search_falls_back_to_text_links_when_grounding_missing(monkeypatch):
    text = (
        "Useful references: "
        "[CFAA](https://www.justice.gov/criminal-fraud/computer-fraud-and-abuse-act) "
        "and https://www.law.cornell.edu/wex/defamation"
    )
    response = SimpleNamespace(
        candidates=[
            SimpleNamespace(
                content=SimpleNamespace(parts=[SimpleNamespace(text=text)]),
                grounding_metadata=None,
            )
        ]
    )

    client = _make_client(response)
    monkeypatch.setattr(cyber_law_service, "_trace", lambda *args, **kwargs: None)

    laws = cyber_law_service._search_laws_with_google(client, _DummyTypes, "query", "usa")

    assert len(laws) >= 1
    urls = {item.source for item in laws}
    assert "https://www.justice.gov/criminal-fraud/computer-fraud-and-abuse-act" in urls


def test_enforce_membership_tops_up_to_minimum_laws():
    candidates = [
        cyber_law_service.LawCandidate("Law A", "Desc A", "https://a", "country_rag", 0.1),
        cyber_law_service.LawCandidate("Law B", "Desc B", "https://b", "country_rag", 0.2),
        cyber_law_service.LawCandidate("Law C", "Desc C", "https://c", "country_rag", 0.3),
        cyber_law_service.LawCandidate("Law D", "Desc D", "https://d", "country_rag", 0.4),
    ]

    model_output = ComplaintOutput(
        summary="Only one law returned by model",
        detected_phrases=["phrase"],
        applicable_laws=[ComplaintLaw(law="Law A", description="Desc A", source="https://a")],
        recommended_actions=["Action"],
    )

    enforced = cyber_law_service._enforce_membership_and_sources(model_output, candidates)

    assert len(enforced.applicable_laws) >= 3
    assert all(item.source for item in enforced.applicable_laws)


def test_search_stage_rewrite_fallback_generates_compact_query():
    query = cyber_law_service._fallback_query_for_stage(
        original_query="very long raw query",
        stage="gemini_search",
        core_decision={
            "core_cybercrime": "Online defamation and harassment via public social media video clip.",
            "description": "Targeted mocking and reputational attack",
        },
        content="content",
    )

    assert "cyber harassment defamation applicable laws" in query
    assert len(query) > 20
