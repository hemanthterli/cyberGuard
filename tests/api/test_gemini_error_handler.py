"""Tests for gemini_error_handler — retry utility and validators."""
from unittest.mock import MagicMock, call, patch

import pytest

from app.services import gemini_error_handler
from app.services.errors import ServiceError


# ---------------------------------------------------------------------------
# call_with_retry — basic success
# ---------------------------------------------------------------------------


def test_call_with_retry_succeeds_on_first_attempt():
    fn = MagicMock(return_value="ok")
    result = gemini_error_handler.call_with_retry(fn, "arg1", key="val")
    assert result == "ok"
    fn.assert_called_once_with("arg1", key="val")


def test_call_with_retry_passes_through_result_when_no_validate():
    fn = MagicMock(return_value={"data": 42})
    result = gemini_error_handler.call_with_retry(fn)
    assert result == {"data": 42}


# ---------------------------------------------------------------------------
# call_with_retry — retry on exception
# ---------------------------------------------------------------------------


def test_call_with_retry_retries_on_exception_and_succeeds():
    attempts = {"count": 0}

    def flaky_fn():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("transient error")
        return "recovered"

    with patch("app.services.gemini_error_handler.time") as mock_time:
        result = gemini_error_handler.call_with_retry(flaky_fn, max_retries=5, delay=0.001)

    assert result == "recovered"
    assert attempts["count"] == 3


def test_call_with_retry_exhausts_retries_and_raises():
    fn = MagicMock(side_effect=RuntimeError("always fails"))

    with patch("app.services.gemini_error_handler.time"):
        with pytest.raises(RuntimeError, match="always fails"):
            gemini_error_handler.call_with_retry(fn, max_retries=2, delay=0.001)

    assert fn.call_count == 3  # 1 initial + 2 retries


def test_call_with_retry_correct_number_of_sleeps():
    fn = MagicMock(side_effect=RuntimeError("fail"))

    with patch("app.services.gemini_error_handler.time") as mock_time:
        with pytest.raises(RuntimeError):
            gemini_error_handler.call_with_retry(fn, max_retries=3, delay=5.0)

    # sleep called between attempts: 3 attempts = 2 gaps (not after the last attempt)
    assert mock_time.sleep.call_count == 3
    mock_time.sleep.assert_called_with(5.0)


# ---------------------------------------------------------------------------
# call_with_retry — retry on invalid output (validate=False)
# ---------------------------------------------------------------------------


def test_call_with_retry_retries_when_validate_returns_false():
    responses = [MagicMock(), MagicMock(), MagicMock()]
    responses[0].candidates = []
    responses[1].candidates = []
    responses[2].candidates = [MagicMock()]  # "valid"

    fn = MagicMock(side_effect=responses)
    validate = MagicMock(side_effect=[False, False, True])

    with patch("app.services.gemini_error_handler.time"):
        result = gemini_error_handler.call_with_retry(
            fn, max_retries=5, delay=0.001, validate=validate
        )

    assert result is responses[2]
    assert fn.call_count == 3


def test_call_with_retry_exhausts_on_repeated_invalid_output():
    fn = MagicMock(return_value=MagicMock())
    validate = MagicMock(return_value=False)

    with patch("app.services.gemini_error_handler.time"):
        with pytest.raises(ServiceError) as exc_info:
            gemini_error_handler.call_with_retry(
                fn, max_retries=2, delay=0.001, validate=validate
            )

    assert exc_info.value.code == "model_failed"
    assert fn.call_count == 3  # 1 + 2 retries


# ---------------------------------------------------------------------------
# call_with_retry — ServiceError is NOT retried
# ---------------------------------------------------------------------------


def test_call_with_retry_does_not_retry_service_error():
    fn = MagicMock(side_effect=ServiceError("config missing", code="config_error", status_code=500))

    with patch("app.services.gemini_error_handler.time") as mock_time:
        with pytest.raises(ServiceError, match="config missing"):
            gemini_error_handler.call_with_retry(fn, max_retries=5, delay=0.001)

    fn.assert_called_once()  # called exactly once, no retries
    mock_time.sleep.assert_not_called()


# ---------------------------------------------------------------------------
# validate_has_text
# ---------------------------------------------------------------------------


class TestValidateHasText:
    def test_returns_true_when_response_text_attribute_present(self):
        resp = MagicMock()
        resp.text = "Some legal text"
        assert gemini_error_handler.validate_has_text(resp) is True

    def test_returns_false_when_text_is_empty_string(self):
        resp = MagicMock()
        resp.text = "   "
        # candidate fallback also empty
        resp.candidates = []
        assert gemini_error_handler.validate_has_text(resp) is False

    def test_returns_false_when_text_is_none_and_no_candidate(self):
        resp = MagicMock()
        resp.text = None
        resp.candidates = []
        assert gemini_error_handler.validate_has_text(resp) is False

    def test_fallback_to_candidate_part_text(self):
        resp = MagicMock()
        resp.text = None
        part = MagicMock()
        part.text = "Candidate text"
        resp.candidates = [MagicMock()]
        resp.candidates[0].content.parts = [part]
        assert gemini_error_handler.validate_has_text(resp) is True

    def test_returns_false_when_candidate_part_text_empty(self):
        resp = MagicMock()
        resp.text = None
        part = MagicMock()
        part.text = ""
        resp.candidates = [MagicMock()]
        resp.candidates[0].content.parts = [part]
        assert gemini_error_handler.validate_has_text(resp) is False


# ---------------------------------------------------------------------------
# validate_has_function_call
# ---------------------------------------------------------------------------


class TestValidateHasFunctionCall:
    def test_returns_true_when_function_call_present(self):
        resp = MagicMock()
        resp.candidates[0].content.parts[0].function_call = MagicMock()
        assert gemini_error_handler.validate_has_function_call(resp) is True

    def test_returns_false_when_function_call_is_none(self):
        resp = MagicMock()
        resp.candidates[0].content.parts[0].function_call = None
        assert gemini_error_handler.validate_has_function_call(resp) is False

    def test_returns_false_when_no_candidates(self):
        resp = MagicMock()
        resp.candidates = []
        # Accessing candidates[0] on empty list raises IndexError
        assert gemini_error_handler.validate_has_function_call(resp) is False


# ---------------------------------------------------------------------------
# raise_if_model_busy
# ---------------------------------------------------------------------------


class TestRaiseIfModelBusy:
    def test_raises_service_error_on_503(self):
        exc = RuntimeError("503 Service Unavailable")
        with pytest.raises(ServiceError) as exc_info:
            gemini_error_handler.raise_if_model_busy(exc)
        assert exc_info.value.code == "model_busy"
        assert exc_info.value.status_code == 503

    def test_raises_service_error_on_429(self):
        exc = RuntimeError("429 resource_exhausted")
        with pytest.raises(ServiceError):
            gemini_error_handler.raise_if_model_busy(exc)

    def test_does_not_raise_on_other_errors(self):
        exc = RuntimeError("404 not found")
        # Should not raise — returns None
        result = gemini_error_handler.raise_if_model_busy(exc)
        assert result is None

    def test_raises_on_exc_with_status_code_attribute(self):
        class ExcWithStatus(RuntimeError):
            status_code = 503

        exc = ExcWithStatus("service unavailable")
        with pytest.raises(ServiceError):
            gemini_error_handler.raise_if_model_busy(exc)


# ---------------------------------------------------------------------------
# Integration: Google search query fix (empty query filtering)
# ---------------------------------------------------------------------------


class TestGoogleSearchQueryFix:
    """
    Verify that empty/whitespace entries in web_search_queries are filtered out
    so the log never shows '; ; ' as the generated_search_query.
    """

    def _build_grounding(self, queries: list[str]):
        grounding = MagicMock()
        grounding.web_search_queries = queries
        grounding.grounding_chunks = []
        return grounding

    def test_empty_queries_fall_back_to_constructed_query(self):
        from app.services import cyber_law_service

        grounding = self._build_grounding(["", "  ", ""])
        candidate = MagicMock()
        candidate.content.parts = []
        candidate.grounding_metadata = grounding

        resp = MagicMock()
        resp.candidates = [candidate]

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = resp

        with patch("app.services.cyber_law_service.settings") as mock_settings:
            mock_settings.gemini_model = "fake-model"
            _, search_query = cyber_law_service._google_search_laws(
                "online harassment", "India", mock_client
            )

        # Constructed fallback: "cyber law <query> <country>"
        assert search_query.startswith("cyber law")
        assert ";" not in search_query or search_query.strip("; ").strip()

    def test_non_empty_queries_are_joined(self):
        from app.services import cyber_law_service

        grounding = self._build_grounding(["cyber law India 2025", "IT Act online harassment"])
        candidate = MagicMock()
        candidate.content.parts = []
        candidate.grounding_metadata = grounding

        resp = MagicMock()
        resp.candidates = [candidate]

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = resp

        with patch("app.services.cyber_law_service.settings") as mock_settings:
            mock_settings.gemini_model = "fake-model"
            _, search_query = cyber_law_service._google_search_laws(
                "online harassment", "India", mock_client
            )

        assert "cyber law India 2025" in search_query
        assert "IT Act online harassment" in search_query

    def test_mixed_empty_and_valid_queries_uses_only_valid(self):
        from app.services import cyber_law_service

        grounding = self._build_grounding(["", "Defamation Act UK 2013", "  "])
        candidate = MagicMock()
        candidate.content.parts = []
        candidate.grounding_metadata = grounding

        resp = MagicMock()
        resp.candidates = [candidate]

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = resp

        with patch("app.services.cyber_law_service.settings") as mock_settings:
            mock_settings.gemini_model = "fake-model"
            _, search_query = cyber_law_service._google_search_laws(
                "harassment", "United Kingdom", mock_client
            )

        assert "Defamation Act UK 2013" in search_query
        assert search_query.strip() != "; ;"
