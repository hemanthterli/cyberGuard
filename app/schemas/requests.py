from pydantic import BaseModel, Field, HttpUrl, model_validator


class SourceInput(BaseModel):
    text: str | None = Field(default=None, min_length=1, examples=["Sample text input"])
    url: HttpUrl | None = Field(default=None, examples=["https://example.com/article"])
    file_base64: str | None = Field(default=None, min_length=1, examples=["BASE64_ENCODED_CONTENT"])
    filename: str | None = Field(default=None, min_length=1, examples=["file.txt"])
    mime_type: str | None = Field(default=None, min_length=1, examples=["text/plain"])

    @model_validator(mode="after")
    def validate_single_input(self) -> "SourceInput":
        provided = [self.text, self.url, self.file_base64]
        if sum(value is not None for value in provided) != 1:
            raise ValueError("Provide exactly one of text, url, or file_base64")
        if self.file_base64 and not self.filename:
            raise ValueError("filename is required when file_base64 is provided")
        return self
