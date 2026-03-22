import logging

import requests

from app.core.config import settings
from app.services.errors import ServiceError
from app.services.types import ProcessedResult

logger = logging.getLogger(__name__)

OCR_SPACE_URL = "https://api.ocr.space/parse/image"


def process_image_bytes(image_bytes: bytes, content_type: str | None, filename: str | None) -> ProcessedResult:
    if not image_bytes:
        raise ServiceError("Empty image payload", code="invalid_input", status_code=400)
    safe_name = _safe_filename(filename, content_type)
    logger.info(
        "OCR request received",
        extra={
            "bytes": len(image_bytes),
            "content_type": content_type or "unknown",
            "file_name": safe_name,
        },
    )
    return _ocr_bytes(image_bytes, content_type, safe_name, input_type="file", source_url=None)


def _ocr_bytes(
    image_bytes: bytes,
    content_type: str | None,
    filename: str,
    input_type: str,
    source_url: str | None,
) -> ProcessedResult:
    if not settings.ocr_space_api_key:
        logger.error("OCR API key not configured")
        raise ServiceError("OCR API key not configured", code="config_error", status_code=500)

    if not image_bytes:
        raise ServiceError("Empty image payload", code="invalid_input", status_code=400)

    files = {
        "file": (filename, image_bytes, content_type or "application/octet-stream"),
    }

    data = {
        "apikey": settings.ocr_space_api_key,
        "language": "eng",
    }
    filetype = _filetype_from_name(filename)
    if filetype:
        data["filetype"] = filetype

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

    logger.info(
        "OCR response received",
        extra={"status_code": response.status_code},
    )
    if response.status_code >= 400:
        logger.warning(
            "OCR service error",
            extra={
                "status_code": response.status_code,
                "body_snippet": response.text[:500],
            },
        )
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


def _safe_filename(filename: str | None, content_type: str | None) -> str:
    if filename and "." in filename:
        return filename
    extension = _extension_from_content_type(content_type)
    return f"image.{extension}"


def _extension_from_content_type(content_type: str | None) -> str:
    mapping = {
        "image/jpeg": "jpg",
        "image/png": "png",
    }
    return mapping.get(content_type or "", "jpg")


def _filetype_from_name(filename: str) -> str | None:
    if "." not in filename:
        return None
    ext = filename.rsplit(".", 1)[1].lower()
    if ext in {"jpg", "jpeg"}:
        return "JPG"
    if ext == "png":
        return "PNG"
    return None
