import logging

import requests

from app.core.config import settings
from app.services.errors import ServiceError

logger = logging.getLogger(__name__)


def fetch_markdown(url: str) -> str:
    api_url = f"https://markdown.new/{url}"
    try:
        response = requests.get(api_url, timeout=settings.request_timeout_seconds)
    except requests.RequestException as exc:
        logger.error("Markdown fetch failed", exc_info=True)
        raise ServiceError("Failed to fetch content", code="fetch_failed", status_code=502) from exc

    if response.status_code >= 400:
        raise ServiceError(
            f"Content service returned {response.status_code}",
            code="fetch_failed",
            status_code=502,
        )

    text = response.text.strip()
    if not text:
        raise ServiceError("Empty content", code="empty_result", status_code=404)

    return text
