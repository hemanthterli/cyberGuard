from app.services.errors import ServiceError
from app.services.types import ProcessedResult


def process_text_content(text: str) -> ProcessedResult:
    normalized = text.strip()
    if not normalized:
        raise ServiceError("Empty text payload", code="invalid_input", status_code=400)
    return ProcessedResult(text=normalized, input_type="text", source_url=None, size_bytes=len(normalized))
