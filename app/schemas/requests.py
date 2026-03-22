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
    user_context: str | None = Field(default=None, min_length=1)
