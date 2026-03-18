import time
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from app.schemas.requests import SourceInput
from app.schemas.responses import ProcessedTextData, ResponseMeta, StandardResponse
from app.services import audio_service, image_service, news_service, text_service, youtube_service
from app.services.errors import ServiceError
from app.services.types import ProcessedResult
from app.utils.auth import require_api_key

router = APIRouter()


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
    "error": {"code": "validation_error", "detail": "Provide exactly one input"},
}

ERROR_RESPONSES: dict[int, dict[str, Any]] = {
    400: {"description": "Bad Request", "model": StandardResponse, "content": {"application/json": {"example": ERROR_EXAMPLE}}},
    401: {"description": "Unauthorized", "model": StandardResponse, "content": {"application/json": {"example": ERROR_EXAMPLE}}},
    403: {"description": "Forbidden", "model": StandardResponse, "content": {"application/json": {"example": ERROR_EXAMPLE}}},
    404: {"description": "Not Found", "model": StandardResponse, "content": {"application/json": {"example": ERROR_EXAMPLE}}},
    422: {"description": "Validation Error", "model": StandardResponse, "content": {"application/json": {"example": ERROR_EXAMPLE}}},
    500: {"description": "Internal Server Error", "model": StandardResponse, "content": {"application/json": {"example": ERROR_EXAMPLE}}},
}

REQUEST_EXAMPLES: dict[str, Any] = {
    "text": {
        "summary": "Text input",
        "value": {"text": "Sample input text"},
    },
    "url": {
        "summary": "URL input",
        "value": {"url": "https://example.com/resource"},
    },
    "file_base64": {
        "summary": "Base64 file input",
        "value": {
            "file_base64": "BASE64_ENCODED_CONTENT",
            "filename": "input.txt",
            "mime_type": "text/plain",
        },
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


def _service_call(func, payload: SourceInput, source: str, request: Request) -> StandardResponse:
    start = time.perf_counter()
    try:
        result = func(payload)
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "detail": exc.message})
    duration_ms = int((time.perf_counter() - start) * 1000)
    request_id = getattr(request.state, "request_id", str(uuid4()))
    return _build_response(result, request_id, source, duration_ms)


@router.post(
    "/audio",
    response_model=StandardResponse,
    responses=ERROR_RESPONSES,
    summary="Process audio input",
)
async def audio_endpoint(
    payload: SourceInput = Body(..., examples=REQUEST_EXAMPLES),
    request: Request,
    _: None = Depends(require_api_key),
) -> StandardResponse:
    return _service_call(audio_service.process_audio, payload, "audio", request)


@router.post(
    "/image",
    response_model=StandardResponse,
    responses=ERROR_RESPONSES,
    summary="Process image input",
)
async def image_endpoint(
    payload: SourceInput = Body(..., examples=REQUEST_EXAMPLES),
    request: Request,
    _: None = Depends(require_api_key),
) -> StandardResponse:
    return _service_call(image_service.process_image, payload, "image", request)


@router.post(
    "/youtube",
    response_model=StandardResponse,
    responses=ERROR_RESPONSES,
    summary="Process YouTube input",
)
async def youtube_endpoint(
    payload: SourceInput = Body(..., examples=REQUEST_EXAMPLES),
    request: Request,
    _: None = Depends(require_api_key),
) -> StandardResponse:
    return _service_call(youtube_service.process_youtube, payload, "youtube", request)


@router.post(
    "/news-article",
    response_model=StandardResponse,
    responses=ERROR_RESPONSES,
    summary="Process news article input",
)
async def news_article_endpoint(
    payload: SourceInput = Body(..., examples=REQUEST_EXAMPLES),
    request: Request,
    _: None = Depends(require_api_key),
) -> StandardResponse:
    return _service_call(news_service.process_news_article, payload, "news-article", request)


@router.post(
    "/text",
    response_model=StandardResponse,
    responses=ERROR_RESPONSES,
    summary="Process text input",
)
async def text_endpoint(
    payload: SourceInput = Body(..., examples=REQUEST_EXAMPLES),
    request: Request,
    _: None = Depends(require_api_key),
) -> StandardResponse:
    return _service_call(text_service.process_text, payload, "text", request)
