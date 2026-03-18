from app.services.errors import ServiceError
from app.services.types import ProcessedResult
from app.services.web_service import fetch_markdown


def process_news_url(url: str) -> ProcessedResult:
    normalized = url.strip()
    if not normalized:
        raise ServiceError("Empty URL", code="invalid_input", status_code=400)
    markdown_text = fetch_markdown(normalized)
    return ProcessedResult(
        text=markdown_text,
        input_type="url",
        source_url=normalized,
        size_bytes=len(markdown_text),
    )
