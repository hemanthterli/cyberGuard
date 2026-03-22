import logging
import time
from typing import Any, Callable
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from app.core.config import settings
from app.schemas.requests import ContentEnhancementInput, CoreDecisionInput, TextInput, UrlInput
from app.schemas.responses import (
    CoreDecisionData,
    CoreDecisionResponse,
    ProcessedTextData,
    ResponseMeta,
    StandardResponse,
)
from app.services import audio_service, image_service, news_service, text_service, youtube_service
from app.services import content_enhancement_service
from app.services import core_decision_service
from app.services.errors import ServiceError
from app.services.types import ProcessedResult

router = APIRouter()
logger = logging.getLogger(__name__)


ERROR_EXAMPLE = {
    "success": False,
    "message": "Validation error",
    "data": None,
    "meta": {
        "request_id": "uuid",
        "source": "audio",
        "input_type": "unknown",
        "duration_ms": 0,
        "size_bytes": None,
        "source_url": None,
    },
    "error": {"code": "validation_error", "detail": "Provide valid input"},
}

ERROR_RESPONSES: dict[int, dict[str, Any]] = {
    400: {
        "description": "Bad Request",
        "model": StandardResponse,
        "content": {"application/json": {"example": ERROR_EXAMPLE}},
    },
    404: {
        "description": "Not Found",
        "model": StandardResponse,
        "content": {"application/json": {"example": ERROR_EXAMPLE}},
    },
    413: {
        "description": "Payload Too Large",
        "model": StandardResponse,
        "content": {"application/json": {"example": ERROR_EXAMPLE}},
    },
    422: {
        "description": "Validation Error",
        "model": StandardResponse,
        "content": {"application/json": {"example": ERROR_EXAMPLE}},
    },
    500: {
        "description": "Internal Server Error",
        "model": StandardResponse,
        "content": {"application/json": {"example": ERROR_EXAMPLE}},
    },
}


def _build_response(
    result: ProcessedResult,
    request_id: str,
    source: str,
    duration_ms: int,
) -> StandardResponse:
    meta = ResponseMeta(
        request_id=request_id,
        source=source,
        input_type=result.input_type,
        duration_ms=duration_ms,
        size_bytes=result.size_bytes,
        source_url=result.source_url,
    )
    data = ProcessedTextData(text=result.text)
    return StandardResponse(
        success=True,
        message=f"{source.replace('-', ' ').title()} processed successfully",
        data=data,
        meta=meta,
        error=None,
    )


def _service_call(
    func: Callable[..., ProcessedResult],
    source: str,
    request: Request,
    *args,
    **kwargs,
) -> StandardResponse:
    start = time.perf_counter()
    try:
        logger.info("Request start", extra={"source": source})
        result = func(*args, **kwargs)
    except ServiceError as exc:
        logger.warning(
            "Service error",
            extra={"source": source, "code": exc.code, "status_code": exc.status_code},
        )
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "detail": exc.message})
    duration_ms = int((time.perf_counter() - start) * 1000)
    request_id = getattr(request.state, "request_id", str(uuid4()))
    logger.info("Request complete", extra={"source": source, "duration_ms": duration_ms})
    return _build_response(result, request_id, source, duration_ms)


def _build_decision_response(
    result: CoreDecisionData,
    request_id: str,
    source: str,
    duration_ms: int,
) -> CoreDecisionResponse:
    meta = ResponseMeta(
        request_id=request_id,
        source=source,
        input_type="json",
        duration_ms=duration_ms,
        size_bytes=None,
        source_url=None,
    )
    return CoreDecisionResponse(
        success=True,
        message="Core decision processed successfully",
        data=result,
        meta=meta,
        error=None,
    )


def _decision_call(
    func: Callable[..., CoreDecisionData],
    source: str,
    request: Request,
    *args,
    **kwargs,
) -> CoreDecisionResponse:
    start = time.perf_counter()
    try:
        logger.info("Request start", extra={"source": source})
        result = func(*args, **kwargs)
    except ServiceError as exc:
        logger.warning(
            "Service error",
            extra={"source": source, "code": exc.code, "status_code": exc.status_code},
        )
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "detail": exc.message})
    duration_ms = int((time.perf_counter() - start) * 1000)
    request_id = getattr(request.state, "request_id", str(uuid4()))
    logger.info("Request complete", extra={"source": source, "duration_ms": duration_ms})
    return _build_decision_response(result, request_id, source, duration_ms)


async def _read_upload(
    file: UploadFile,
    *,
    allowed_types: set[str] | None = None,
    allowed_prefix: str | None = None,
) -> bytes:
    if not file:
        raise ServiceError("File is required", code="invalid_input", status_code=400)
    content_type = file.content_type or ""
    if allowed_prefix and not content_type.startswith(allowed_prefix):
        raise ServiceError("Unsupported file type", code="invalid_input", status_code=400)
    if allowed_types and content_type not in allowed_types:
        raise ServiceError("Unsupported file type", code="invalid_input", status_code=400)
    data = await file.read()
    if not data:
        raise ServiceError("Empty file payload", code="invalid_input", status_code=400)
    if len(data) > settings.max_download_bytes:
        raise ServiceError("File payload too large", code="payload_too_large", status_code=413)
    return data


@router.post(
    "/audio",
    response_model=StandardResponse,
    responses=ERROR_RESPONSES,
    summary="Process audio input",
)
async def audio_endpoint(request: Request, file: UploadFile = File(...)) -> StandardResponse:
    audio_bytes = await _read_upload(file, allowed_prefix="audio/")
    return _service_call(audio_service.process_audio_bytes, "audio", request, audio_bytes)


@router.post(
    "/image",
    response_model=StandardResponse,
    responses=ERROR_RESPONSES,
    summary="Process image input",
)
async def image_endpoint(request: Request, file: UploadFile = File(...)) -> StandardResponse:
    image_bytes = await _read_upload(file, allowed_types={"image/jpeg", "image/png"})
    return _service_call(
        image_service.process_image_bytes,
        "image",
        request,
        image_bytes,
        file.content_type,
        file.filename,
    )


@router.post(
    "/youtube",
    response_model=StandardResponse,
    responses=ERROR_RESPONSES,
    summary="Process YouTube input",
)
async def youtube_endpoint(payload: UrlInput, request: Request) -> StandardResponse:
    return _service_call(youtube_service.process_youtube_url, "youtube", request, str(payload.url))


@router.post(
    "/news-article",
    response_model=StandardResponse,
    responses=ERROR_RESPONSES,
    summary="Process news article input",
)
async def news_article_endpoint(payload: UrlInput, request: Request) -> StandardResponse:
    return _service_call(news_service.process_news_url, "news-article", request, str(payload.url))


@router.post(
    "/text",
    response_model=StandardResponse,
    responses=ERROR_RESPONSES,
    summary="Process text input",
)
async def text_endpoint(payload: TextInput, request: Request) -> StandardResponse:
    return _service_call(text_service.process_text_content, "text", request, payload.text)


@router.post(
    "/core-decision",
    response_model=CoreDecisionResponse,
    responses=ERROR_RESPONSES,
    summary="Analyze content for bullying/harassment",
)
async def core_decision_endpoint(payload: CoreDecisionInput, request: Request) -> CoreDecisionResponse:
    return _decision_call(core_decision_service.analyze_bullying, "core-decision", request, payload)


@router.post(
    "/content-enhancement",
    response_model=StandardResponse,
    responses=ERROR_RESPONSES,
    summary="Enhance and structure raw content",
    tags=["Content Processing"],
)
async def content_enhancement_endpoint(
    payload: ContentEnhancementInput,
    request: Request,
) -> StandardResponse:
    return _service_call(
        content_enhancement_service.enhance_content,
        "content-enhancement",
        request,
        payload,
    )
