from pydantic import BaseModel, Field


class ErrorInfo(BaseModel):
    code: str = Field(..., examples=["invalid_input"])
    detail: str | None = Field(default=None, examples=["Provide a valid URL."])


class ResponseMeta(BaseModel):
    request_id: str
    source: str
    input_type: str
    duration_ms: int
    size_bytes: int | None = None
    source_url: str | None = None


class ProcessedTextData(BaseModel):
    text: str


class StandardResponse(BaseModel):
    success: bool
    message: str
    data: ProcessedTextData | None
    meta: ResponseMeta
    error: ErrorInfo | None = None
