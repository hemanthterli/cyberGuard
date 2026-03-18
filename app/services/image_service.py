import logging

import requests

from app.core.config import settings
from app.schemas.requests import SourceInput
from app.services.errors import ServiceError
from app.services.types import ProcessedResult
from app.utils.base64_utils import decode_base64
from app.utils.http import fetch_url_bytes

logger = logging.getLogger(__name__)

OCR_SPACE_URL = "https://api.ocr.space/parse/image"


def process_image(payload: SourceInput) -> ProcessedResult:
    if payload.text is not None:
        text = payload.text.strip()
        if not text:
            raise ServiceError("Empty text payload", code="invalid_input", status_code=400)
        return ProcessedResult(text=text, input_type="text", source_url=None, size_bytes=len(text))

    if payload.url is not None:
        image_bytes, content_type = fetch_url_bytes(str(payload.url))
        return _ocr_bytes(image_bytes, content_type, input_type="url", source_url=str(payload.url))

    if payload.file_base64 is not None:
        image_bytes = decode_base64(payload.file_base64, settings.max_download_bytes)
        return _ocr_bytes(image_bytes, payload.mime_type, input_type="file", source_url=None)

    raise ServiceError("No input provided", code="invalid_input", status_code=400)


def _ocr_bytes(
    image_bytes: bytes,
    content_type: str | None,
    input_type: str,
    source_url: str | None,
) -> ProcessedResult:
    if not settings.ocr_space_api_key:
        raise ServiceError("OCR API key not configured", code="config_error", status_code=500)

    if not image_bytes:
        raise ServiceError("Empty image payload", code="invalid_input", status_code=400)

    files = {
        "file": ("image", image_bytes, content_type or "application/octet-stream"),
    }

    data = {
        "apikey": settings.ocr_space_api_key,
        "language": "eng",
    }

    try:
        response = requests.post(
            OCR_SPACE_URL,
            files=files,
            data=data,
            timeout=settings.request_timeout_seconds,
        )
    except requests.RequestException as exc:
        logger.error("OCR request failed", exc_info=True)
        raise ServiceError("Failed to reach OCR service", code="ocr_unavailable", status_code=502) from exc

    if response.status_code >= 400:
        raise ServiceError(
            f"OCR service returned {response.status_code}",
            code="ocr_failed",
            status_code=502,
        )

    try:
        result = response.json()
    except ValueError as exc:
        logger.error("OCR response parsing failed", exc_info=True)
        raise ServiceError("Invalid OCR response", code="ocr_failed", status_code=502) from exc
    if result.get("IsErroredOnProcessing"):
        message = result.get("ErrorMessage") or "OCR processing failed"
        if isinstance(message, list):
            message = "; ".join(str(m) for m in message)
        raise ServiceError(str(message), code="ocr_failed", status_code=422)

    parsed = result.get("ParsedResults") or []
    if not parsed:
        raise ServiceError("No text detected", code="empty_result", status_code=422)

    text = parsed[0].get("ParsedText", "").strip()
    if not text:
        raise ServiceError("No text detected", code="empty_result", status_code=422)

    return ProcessedResult(
        text=text,
        input_type=input_type,
        source_url=source_url,
        size_bytes=len(image_bytes),
    )
