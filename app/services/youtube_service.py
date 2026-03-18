import logging
import tempfile
from pathlib import Path

import webvtt
import yt_dlp

from app.services.errors import ServiceError
from app.services.types import ProcessedResult

logger = logging.getLogger(__name__)


def process_youtube_url(url: str) -> ProcessedResult:
    normalized = _normalize_youtube_url(url)
    return _download_captions(normalized, input_type="url", source_url=normalized)


def _normalize_youtube_url(value: str) -> str:
    value = value.strip()
    if not value:
        raise ServiceError("Empty YouTube URL", code="invalid_input", status_code=400)
    if not (value.startswith("http://") or value.startswith("https://")):
        raise ServiceError("YouTube URL must start with http(s)", code="invalid_input", status_code=400)
    if "youtube.com" not in value and "youtu.be" not in value:
        raise ServiceError("YouTube URL is required", code="invalid_input", status_code=400)
    return value


def _download_captions(url: str, input_type: str, source_url: str | None = None) -> ProcessedResult:
    with tempfile.TemporaryDirectory() as tmpdir:
        ydl_opts = {
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["en"],
            "outtmpl": f"{tmpdir}/%(id)s.%(ext)s",
            "quiet": True,
            "no_warnings": True,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                video_id = info.get("id")
        except Exception as exc:  # noqa: BLE001
            logger.error("YouTube extraction failed", exc_info=True)
            raise ServiceError("Failed to fetch YouTube captions", code="youtube_failed", status_code=502) from exc

        if not video_id:
            raise ServiceError("Unable to resolve video", code="youtube_failed", status_code=404)

        vtt_files = list(Path(tmpdir).glob("*.vtt"))
        if not vtt_files:
            raise ServiceError("No captions available", code="empty_result", status_code=404)

        text_parts: list[str] = []
        try:
            for caption in webvtt.read(str(vtt_files[0])):
                if caption.text:
                    text_parts.append(caption.text.strip())
        except Exception as exc:  # noqa: BLE001
            logger.error("Caption parsing failed", exc_info=True)
            raise ServiceError("Failed to parse captions", code="youtube_failed", status_code=502) from exc

        text = " ".join(text_parts).strip()
        if not text:
            raise ServiceError("No captions available", code="empty_result", status_code=404)

        return ProcessedResult(
            text=text,
            input_type=input_type,
            source_url=source_url,
            size_bytes=None,
        )
