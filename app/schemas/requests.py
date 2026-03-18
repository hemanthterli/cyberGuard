from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class TextInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(..., min_length=1)


class UrlInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: HttpUrl
