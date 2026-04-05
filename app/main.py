import time
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes.data_sources import router
from app.core.config import settings
from app.core.logging import configure_logging
from app.schemas.responses import ErrorInfo, ResponseMeta, StandardResponse

configure_logging()

app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8002",
        "http://127.0.0.1:8002",
        "https://cyberguard-frontend-huwj.onrender.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid4()))
    request.state.request_id = request_id
    request.state.start_time = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


def _error_response(request: Request, status_code: int, code: str, detail: str) -> JSONResponse:
    request_id = getattr(request.state, "request_id", str(uuid4()))
    start_time = getattr(request.state, "start_time", None)
    duration_ms = int((time.perf_counter() - start_time) * 1000) if start_time else 0
    source = request.url.path.strip("/") or "root"

    meta = ResponseMeta(
        request_id=request_id,
        source=source,
        input_type="unknown",
        duration_ms=duration_ms,
        size_bytes=None,
        source_url=None,
    )

    response = StandardResponse(
        success=False,
        message=detail,
        data=None,
        meta=meta,
        error=ErrorInfo(code=code, detail=detail),
    )

    return JSONResponse(status_code=status_code, content=response.model_dump())


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    code = "http_error"
    detail = "Request failed"
    if isinstance(exc.detail, dict):
        code = exc.detail.get("code", code)
        detail = exc.detail.get("detail", detail)
    elif isinstance(exc.detail, str):
        detail = exc.detail
    return _error_response(request, exc.status_code, code, detail)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    detail = "Validation error"
    if exc.errors():
        detail = exc.errors()[0].get("msg", detail)
    return _error_response(request, 422, "validation_error", detail)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    return _error_response(request, 500, "internal_error", "Internal server error")
