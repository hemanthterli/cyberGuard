import logging
from typing import Tuple

import requests

from app.core.config import settings
from app.services.errors import ServiceError

logger = logging.getLogger(__name__)


def fetch_url_bytes(url: str) -> Tuple[bytes, str | None]:
    try:
        with requests.get(url, stream=True, timeout=settings.request_timeout_seconds) as response:
            if response.status_code >= 400:
                raise ServiceError(
                    f"Upstream returned {response.status_code}",
                    code="fetch_failed",
                    status_code=502,
                )

            content_type = response.headers.get("Content-Type")
            data = bytearray()
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    data.extend(chunk)
                    if len(data) > settings.max_download_bytes:
                        raise ServiceError(
                            "Downloaded file too large",
                            code="payload_too_large",
                            status_code=413,
                        )

            return bytes(data), content_type
    except ServiceError:
        raise
    except requests.RequestException as exc:
        logger.error("HTTP request failed", exc_info=True)
        raise ServiceError("Failed to fetch URL", code="fetch_failed", status_code=502) from exc
