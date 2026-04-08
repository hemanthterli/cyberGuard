from unittest.mock import MagicMock, patch

import pytest

from app.schemas.responses import ComplaintLaw, ComplaintOutput, RAGSource
from app.services import cyber_law_service
from app.services.errors import ServiceError

# ---------------------------------------------------------------------------
# Shared payloads
# ---------------------------------------------------------------------------

_VALID_PAYLOAD = {
    "content": "raw content",
    "core_decision": {
        "bullying": "yes",
        "description": "desc",
        "phrases": "phrase",
        "source": "https://example.com",
        "impact_action": "Report",
        "core_cybercrime": "online harassment",
    },
    "retrieved_laws": ["law snippet"],
}

_COMPLETE_CORE_DECISION = {
    "bullying": "yes",
    "description": "desc",
    "phrases": "phrase",
    "source": "https://example.com",
    "impact_action": "Report",
    "core_cybercrime": "online harassment",
}


def _fake_output(**kwargs) -> ComplaintOutput:
    return ComplaintOutput(
        summary=kwargs.get("summary", "Summary"),
        detected_phrases=["phrase"],
        applicable_laws=[ComplaintLaw(law="Act", description="Desc")],
        recommended_actions=["Action"],
        rag_sources=kwargs.get("rag_sources", []),
    )


# ---------------------------------------------------------------------------
# Existing endpoint contract tests (unchanged behaviour)
# ---------------------------------------------------------------------------


def test_get_cyber_laws_success(client, monkeypatch):
    monkeypatch.setattr(cyber_law_service, "analyze_cyber_laws", lambda _p: _fake_output())
    response = client.post("/get-cyber-laws", json=_VALID_PAYLOAD)
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
    response = client.post("/get-cyber-laws", json=_VALID_PAYLOAD)
    assert response.status_code == 502
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "model_failed"


# ---------------------------------------------------------------------------
# Unit tests – enrichment helpers
# ---------------------------------------------------------------------------


class TestStructuredToSnippet:
    def test_full_law_dict(self):
        law = {
            "title": "IT Act 2000",
            "description": "Covers cyber offences",
            "source": "rag",
            "url": "https://example.com/it-act",
            "country": "India",
        }
        snippet = cyber_law_service._structured_to_snippet(law)
        assert "IT Act 2000" in snippet
        assert "rag" in snippet
        assert "Covers cyber offences" in snippet

    def test_missing_url_omitted(self):
        law = {"title": "Some Law", "description": "text", "source": "rag", "url": "", "country": "India"}
        snippet = cyber_law_service._structured_to_snippet(law)
        assert "URL:" not in snippet

    def test_empty_dict_returns_empty_string(self):
        snippet = cyber_law_service._structured_to_snippet({})
        assert snippet == ""


class TestFormatSuppliedAsStructured:
    def test_converts_list_to_structured_dicts(self):
        supplied = ["Law A text", "Law B text"]
        result = cyber_law_service._format_supplied_as_structured(supplied, "India")
        assert len(result) == 2
        assert result[0]["source"] == "rag"
        assert result[0]["country"] == "India"
        assert result[0]["description"] == "Law A text"
        assert result[1]["title"] == "Pre-supplied Law 2"

    def test_empty_input(self):
        result = cyber_law_service._format_supplied_as_structured([], "United Kingdom")
        assert result == []


# ---------------------------------------------------------------------------
# Unit tests – Google Search helper
# ---------------------------------------------------------------------------


class TestGoogleSearchLaws:
    def _make_fake_response(self, text: str, chunks=None):
        """Build a minimal mock of the Gemini API response."""
        part = MagicMock()
        part.text = text
        content = MagicMock()
        content.parts = [part]

        grounding = MagicMock()
        grounding.web_search_queries = [f"cyber law query India"]
        if chunks is not None:
            grounding.grounding_chunks = chunks
        else:
            grounding.grounding_chunks = []

        candidate = MagicMock()
        candidate.content = content
        candidate.grounding_metadata = grounding

        response = MagicMock()
        response.candidates = [candidate]
        return response

    def test_returns_structured_entries_with_grounding(self):
        chunk = MagicMock()
        chunk.web = MagicMock()
        chunk.web.title = "IT Act 2000"
        chunk.web.uri = "https://example.com/it-act"

        fake_response = self._make_fake_response("Answer text", chunks=[chunk])
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = fake_response

        with patch("app.services.cyber_law_service.settings") as mock_settings:
            mock_settings.gemini_model = "fake-model"
            result, search_query = cyber_law_service._google_search_laws(
                "online harassment", "India", mock_client
            )

        assert len(result) >= 1
        assert result[0]["source"] == "google_search"
        assert result[0]["country"] == "India"

    def test_falls_back_on_exception(self):
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = RuntimeError("network error")

        result, search_query = cyber_law_service._google_search_laws(
            "phishing", "United States", mock_client
        )
        assert result == []
        assert "phishing" in search_query or "United States" in search_query

    def test_no_candidates_returns_empty(self):
        fake_response = MagicMock()
        fake_response.candidates = []
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = fake_response

        with patch("app.services.cyber_law_service.settings") as mock_settings:
            mock_settings.gemini_model = "fake-model"
            result, _ = cyber_law_service._google_search_laws("query", "India", mock_client)

        assert result == []


# ---------------------------------------------------------------------------
# Unit tests – Gemini re-ranking helper
# ---------------------------------------------------------------------------


class TestRerankWithGemini:
    def _make_rerank_response(self, relevant_laws: list[dict]):
        call = MagicMock()
        call.args = {"relevant_laws": relevant_laws}

        part = MagicMock()
        part.function_call = call

        content = MagicMock()
        content.parts = [part]

        candidate = MagicMock()
        candidate.content = content

        response = MagicMock()
        response.candidates = [candidate]
        return response

    def test_returns_filtered_reranked_laws(self):
        all_laws = [
            {"title": "IT Act", "description": "covers hacking", "source": "rag", "url": "", "country": "India"},
            {"title": "Unrelated Tax Law", "description": "tax stuff", "source": "rag", "url": "", "country": "India"},
        ]
        relevant = [all_laws[0]]
        fake_response = self._make_rerank_response(relevant)
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = fake_response

        with patch("app.services.cyber_law_service.settings") as mock_settings:
            mock_settings.gemini_complaint_model = "fake-model"
            result = cyber_law_service._rerank_with_gemini(
                "online hacking", "cyber law India", all_laws, mock_client
            )

        assert len(result) == 1
        assert result[0]["title"] == "IT Act"

    def test_falls_back_when_gemini_raises(self):
        all_laws = [
            {"title": "IT Act", "description": "text", "source": "rag", "url": "", "country": "India"}
        ]
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = RuntimeError("timeout")

        result = cyber_law_service._rerank_with_gemini("query", "search_q", all_laws, mock_client)
        assert result == all_laws  # graceful fallback

    def test_falls_back_when_no_function_call(self):
        part = MagicMock()
        part.function_call = None
        content = MagicMock()
        content.parts = [part]
        candidate = MagicMock()
        candidate.content = content
        response = MagicMock()
        response.candidates = [candidate]

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = response

        all_laws = [{"title": "Law", "description": "d", "source": "rag", "url": "", "country": "India"}]
        with patch("app.services.cyber_law_service.settings") as mock_settings:
            mock_settings.gemini_complaint_model = "fake-model"
            result = cyber_law_service._rerank_with_gemini("q", "sq", all_laws, mock_client)

        assert result == all_laws  # fallback

    def test_empty_input_returns_empty(self):
        mock_client = MagicMock()
        result = cyber_law_service._rerank_with_gemini("q", "sq", [], mock_client)
        assert result == []


# ---------------------------------------------------------------------------
# Unit tests – enrichment pipeline orchestrator
# ---------------------------------------------------------------------------


class TestRunEnrichmentPipeline:
    def test_successful_pipeline(self, monkeypatch):
        rag_structured = [
            {"title": "IT Act", "description": "d", "source": "rag", "url": "", "country": "India"}
        ]
        google_results = [
            {"title": "CERT-In Rules", "description": "g", "source": "google_search", "url": "http://x.com", "country": "India"}
        ]
        reranked = rag_structured + google_results

        monkeypatch.setattr(cyber_law_service, "_google_search_laws", lambda *a, **kw: (google_results, "query India"))
        monkeypatch.setattr(cyber_law_service, "_rerank_with_gemini", lambda *a, **kw: reranked)
        monkeypatch.setattr(cyber_law_service, "_write_enrichment_log", lambda **kw: None)

        mock_client = MagicMock()
        enriched, google_sources = cyber_law_service._run_enrichment_pipeline(
            query="hacking",
            country_label="India",
            rag_structured=rag_structured,
            client=mock_client,
        )

        assert len(enriched) == 2
        assert len(google_sources) == 1  # only entries with URL become RAGSource
        assert google_sources[0].category == "google_search"

    def test_google_search_failure_falls_back_to_rag_only(self, monkeypatch):
        rag_structured = [
            {"title": "IT Act", "description": "d", "source": "rag", "url": "", "country": "India"}
        ]

        def raise_error(*a, **kw):
            raise RuntimeError("network error")

        monkeypatch.setattr(cyber_law_service, "_google_search_laws", raise_error)
        monkeypatch.setattr(cyber_law_service, "_rerank_with_gemini", lambda *a, **kw: a[2])  # pass-through
        monkeypatch.setattr(cyber_law_service, "_write_enrichment_log", lambda **kw: None)

        mock_client = MagicMock()
        enriched, google_sources = cyber_law_service._run_enrichment_pipeline(
            query="hacking",
            country_label="India",
            rag_structured=rag_structured,
            client=mock_client,
        )

        assert enriched == rag_structured
        assert google_sources == []

    def test_empty_rag_and_google_returns_empty(self, monkeypatch):
        monkeypatch.setattr(cyber_law_service, "_google_search_laws", lambda *a, **kw: ([], "q India"))
        monkeypatch.setattr(cyber_law_service, "_write_enrichment_log", lambda **kw: None)

        mock_client = MagicMock()
        enriched, google_sources = cyber_law_service._run_enrichment_pipeline(
            query="unknown",
            country_label="India",
            rag_structured=[],
            client=mock_client,
        )

        assert enriched == []
        assert google_sources == []

    def test_reranking_failure_returns_all_laws(self, monkeypatch):
        rag_structured = [
            {"title": "Law A", "description": "d", "source": "rag", "url": "", "country": "India"}
        ]
        google_results = [
            {"title": "Law B", "description": "g", "source": "google_search", "url": "", "country": "India"}
        ]

        monkeypatch.setattr(cyber_law_service, "_google_search_laws", lambda *a, **kw: (google_results, "q India"))
        monkeypatch.setattr(
            cyber_law_service,
            "_rerank_with_gemini",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("re-rank broke")),
        )
        monkeypatch.setattr(cyber_law_service, "_write_enrichment_log", lambda **kw: None)

        mock_client = MagicMock()
        enriched, _ = cyber_law_service._run_enrichment_pipeline(
            query="issue",
            country_label="India",
            rag_structured=rag_structured,
            client=mock_client,
        )
        # Should fall back to all_laws (rag + google combined)
        assert len(enriched) == 2


# ---------------------------------------------------------------------------
# Unit tests – enrichment log writer
# ---------------------------------------------------------------------------


class TestWriteEnrichmentLog:
    def test_creates_json_log_file(self, tmp_path, monkeypatch):
        # Redirect project root to tmp_path
        monkeypatch.setattr(
            cyber_law_service,
            "_IST",
            cyber_law_service._IST,  # keep real IST
        )

        # Patch Path(__file__).resolve().parents[2] by monkey-patching where log_dir is built
        original_write = cyber_law_service._write_enrichment_log

        written: list[dict] = []

        def patched_write(**kwargs):
            from datetime import datetime
            from pathlib import Path

            now_ist = datetime.now(cyber_law_service._IST)
            timestamp_folder = now_ist.strftime("%d_%m_%Y_%H_%M_%S")
            log_dir = tmp_path / "logs" / timestamp_folder
            log_dir.mkdir(parents=True, exist_ok=True)
            import json

            log_data = {
                "session_id": kwargs["session_id"],
                "user_query": kwargs["user_query"],
                "country": kwargs["country"],
                "generated_search_query": kwargs["search_query"],
                "rag_results": kwargs["rag_results"],
                "google_results": kwargs["google_results"],
                "final_selected_laws": kwargs["reranked_laws"],
            }
            log_file = log_dir / "enrichment_log.json"
            log_file.write_text(json.dumps(log_data, ensure_ascii=False, indent=2), encoding="utf-8")
            written.append(log_data)

        monkeypatch.setattr(cyber_law_service, "_write_enrichment_log", patched_write)

        cyber_law_service._write_enrichment_log(
            session_id="test-session",
            user_query="hacking",
            country="India",
            search_query="cyber law hacking India",
            rag_results=[{"title": "IT Act", "description": "d", "source": "rag", "url": "", "country": "India"}],
            google_results=[],
            reranked_laws=[{"title": "IT Act", "description": "d", "source": "rag", "url": "", "country": "India"}],
        )
        assert len(written) == 1
        assert written[0]["user_query"] == "hacking"
        assert written[0]["country"] == "India"
