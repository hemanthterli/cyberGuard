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


class CoreDecisionData(BaseModel):
    bullying: str
    description: str
    phrases: str
    source: str
    impact_action: str
    core_cybercrime: str


class CoreDecisionResponse(BaseModel):
    success: bool
    message: str
    data: CoreDecisionData | None
    meta: ResponseMeta
    error: ErrorInfo | None = None


class ComplaintLaw(BaseModel):
    law: str
    description: str


class RAGSource(BaseModel):
    title: str
    url: str | None = None
    category: str | None = None


class ComplaintOutput(BaseModel):
    summary: str
    detected_phrases: list[str]
    applicable_laws: list[ComplaintLaw]
    recommended_actions: list[str]
    country: str = ""
    rag_sources: list[RAGSource] = Field(default_factory=list)


class CyberLawsResponse(BaseModel):
    success: bool
    message: str
    data: ComplaintOutput | None
    meta: ResponseMeta
    error: ErrorInfo | None = None
