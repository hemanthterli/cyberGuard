import logging
from urllib.parse import parse_qs, urlparse

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    CouldNotRetrieveTranscript,
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
)

from app.services.errors import ServiceError
from app.services.types import ProcessedResult

logger = logging.getLogger(__name__)


def process_youtube_url(url: str) -> ProcessedResult:
    normalized = _normalize_youtube_url(url)
    video_id = _extract_video_id(normalized)
    transcript = _fetch_transcript(video_id)
    text = " ".join(
        [
            chunk.get("text", "").strip()
            for chunk in transcript
            if chunk.get("text")
        ]
    ).strip()

    if not text:
        raise ServiceError("No captions available", code="empty_result", status_code=404)

    return ProcessedResult(
        text=text,
        input_type="url",
        source_url=normalized,
        size_bytes=None,
    )


def _normalize_youtube_url(value: str) -> str:
    value = value.strip()
    if not value:
        raise ServiceError("Empty YouTube URL", code="invalid_input", status_code=400)
    if not (value.startswith("http://") or value.startswith("https://")):
        raise ServiceError("YouTube URL must start with http(s)", code="invalid_input", status_code=400)
    if "youtube.com" not in value and "youtu.be" not in value:
        raise ServiceError("YouTube URL is required", code="invalid_input", status_code=400)
    return value


def _extract_video_id(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    video_id = ""

    if "youtu.be" in host:
        video_id = parsed.path.lstrip("/")
    elif "youtube.com" in host:
        if parsed.path == "/watch":
            video_id = parse_qs(parsed.query).get("v", [""])[0]
        elif parsed.path.startswith("/shorts/"):
            parts = parsed.path.split("/")
            video_id = parts[2] if len(parts) > 2 else ""
        elif parsed.path.startswith("/embed/"):
            parts = parsed.path.split("/")
            video_id = parts[2] if len(parts) > 2 else ""
        else:
            video_id = parse_qs(parsed.query).get("v", [""])[0]

    if not video_id:
        raise ServiceError("Unable to resolve video", code="youtube_failed", status_code=404)
    return video_id


def _to_raw_transcript(transcript) -> list[dict]:
    if transcript is None:
        return []
    if hasattr(transcript, "to_raw_data"):
        return transcript.to_raw_data()
    if isinstance(transcript, list):
        return transcript
    try:
        return list(transcript)
    except TypeError:
        return []


def _fetch_transcript(video_id: str) -> list[dict]:
    api = YouTubeTranscriptApi()

    try:
        return _to_raw_transcript(api.fetch(video_id, languages=["en"]))
    except (NoTranscriptFound, TranscriptsDisabled):
        try:
            return _to_raw_transcript(api.fetch(video_id))
        except (NoTranscriptFound, TranscriptsDisabled) as exc:
            raise ServiceError("No captions available", code="empty_result", status_code=404) from exc
        except VideoUnavailable as exc:
            raise ServiceError("Video unavailable", code="youtube_failed", status_code=404) from exc
        except CouldNotRetrieveTranscript as exc:
            logger.error("YouTube transcript fetch failed", exc_info=True)
            raise ServiceError("Failed to fetch YouTube transcript", code="youtube_failed", status_code=502) from exc
        except Exception as exc:  # noqa: BLE001
            logger.error("YouTube transcript fetch failed", exc_info=True)
            raise ServiceError("Failed to fetch YouTube transcript", code="youtube_failed", status_code=502) from exc
    except VideoUnavailable as exc:
        raise ServiceError("Video unavailable", code="youtube_failed", status_code=404) from exc
    except CouldNotRetrieveTranscript as exc:
        logger.error("YouTube transcript fetch failed", exc_info=True)
        raise ServiceError("Failed to fetch YouTube transcript", code="youtube_failed", status_code=502) from exc
    except Exception as exc:  # noqa: BLE001
        logger.error("YouTube transcript fetch failed", exc_info=True)
        raise ServiceError("Failed to fetch YouTube transcript", code="youtube_failed", status_code=502) from exc
