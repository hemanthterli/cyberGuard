from app.core.config import settings
from app.schemas.requests import SourceInput
from app.services.errors import ServiceError
from app.services.types import ProcessedResult
from app.services.web_service import fetch_markdown
from app.utils.base64_utils import decode_base64
from app.utils.text_utils import bytes_to_text


def process_text(payload: SourceInput) -> ProcessedResult:
    if payload.text is not None:
        text = payload.text.strip()
        if not text:
            raise ServiceError("Empty text payload", code="invalid_input", status_code=400)
        return ProcessedResult(text=text, input_type="text", source_url=None, size_bytes=len(text))

    if payload.url is not None:
        markdown_text = fetch_markdown(str(payload.url))
        return ProcessedResult(
            text=markdown_text,
            input_type="url",
            source_url=str(payload.url),
            size_bytes=len(markdown_text),
        )

    if payload.file_base64 is not None:
        data = decode_base64(payload.file_base64, settings.max_download_bytes)
        text = bytes_to_text(data).strip()
        if not text:
            raise ServiceError("Empty file payload", code="invalid_input", status_code=400)
        return ProcessedResult(text=text, input_type="file", source_url=None, size_bytes=len(text))

    raise ServiceError("No input provided", code="invalid_input", status_code=400)
