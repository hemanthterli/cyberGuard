import logging
from typing import Any

from app.core.config import settings
from app.schemas.requests import ContentEnhancementInput
from app.services import gemini_error_handler
from app.services.errors import ServiceError
from app.services.types import ProcessedResult

logger = logging.getLogger(__name__)


def enhance_content(payload: ContentEnhancementInput) -> ProcessedResult:
    source_type = payload.source_type.strip()
    source = (payload.source or "").strip() or None
    content = payload.content.strip()

    if not source_type:
        raise ServiceError("Empty source_type", code="invalid_input", status_code=400)
    if not content:
        raise ServiceError("Empty content", code="invalid_input", status_code=400)

    try:
        from google import genai
        from google.genai import types
    except Exception as exc:  # noqa: BLE001
        logger.error("google-genai not installed", exc_info=True)
        raise ServiceError("Gemini client not available", code="dependency_missing", status_code=500) from exc

    if not settings.gemini_api_key:
        raise ServiceError("GEMINI_API_KEY not configured", code="config_error", status_code=500)

    client = genai.Client(api_key=settings.gemini_api_key)
    prompt = _build_prompt(
        {
            "source_type": source_type,
            "source": source,
            "content": content,
        }
    )

    config = types.GenerateContentConfig(
        temperature=0.2,
        top_p=0.9,
        max_output_tokens=2048,
    )

    try:
        response = gemini_error_handler.call_with_retry(
            client.models.generate_content,
            model=settings.gemini_enhance_model,
            contents=prompt,
            config=config,
            validate=gemini_error_handler.validate_has_text,
        )
    except ServiceError:
        raise
    except Exception as exc:  # noqa: BLE001
        gemini_error_handler.raise_if_model_busy(exc)
        logger.error("Gemini enhancement failed after retries", exc_info=True)
        raise ServiceError("Failed to enhance content", code="model_failed", status_code=502) from exc

    text = _extract_text(response)
    if not text:
        raise ServiceError("Model returned empty content", code="model_failed", status_code=502)

    return ProcessedResult(
        text=text,
        input_type="json",
        source_url=source,
        size_bytes=len(content),
    )


def _build_prompt(payload: dict[str, Any]) -> str:
    return (
        "You are a content enhancement engine.\n"
        "The input comes from the specified source_type.\n\n"
        "Goals:\n"
        "- Clean and enhance formatting.\n"
        "- Remove noise like extra characters, links, metadata, OCR artifacts.\n"
        "- Improve readability and structure.\n\n"
        "Strict constraints:\n"
        "- Do NOT add new information.\n"
        "- Do NOT infer missing context.\n"
        "- Preserve the original meaning only.\n\n"
        "Input JSON:\n"
        f"{payload}\n\n"
        "Return only the cleaned, structured content."
    )


def _extract_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if text:
        return str(text).strip()
    try:
        candidate = response.candidates[0]
        part = candidate.content.parts[0]
        return str(getattr(part, "text", "")).strip()
    except Exception:  # noqa: BLE001
        return ""
