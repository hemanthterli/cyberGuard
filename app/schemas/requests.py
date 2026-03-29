from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class TextInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(..., min_length=1)


class UrlInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: HttpUrl


class CoreDecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str = Field(..., min_length=1)
    source_type: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    user_context: str | None = Field(default=None, min_length=0)
    language: str | None = Field(default="english", min_length=1)


class ContentEnhancementInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_type: str = Field(..., min_length=1)
    source: str | None = Field(default=None, min_length=1)
    content: str = Field(..., min_length=1)


class CyberLawsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(..., min_length=1)
    core_decision: dict = Field(..., description="Core decision output JSON")
    retrieved_laws: list[str] = Field(default_factory=list)
    language: str | None = Field(default="english", min_length=1)


class ComplaintDraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(..., min_length=1)
    detected_phrases: list[str] = Field(default_factory=list)
    applicable_laws: list[dict] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    language: str | None = Field(default="english", min_length=1)
