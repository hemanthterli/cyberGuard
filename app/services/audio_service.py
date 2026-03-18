import logging
import os
import tempfile

from faster_whisper import WhisperModel

from app.core.config import settings
from app.schemas.requests import SourceInput
from app.services.errors import ServiceError
from app.services.types import ProcessedResult
from app.utils.base64_utils import decode_base64
from app.utils.http import fetch_url_bytes

logger = logging.getLogger(__name__)

_model: WhisperModel | None = None


def _get_model() -> WhisperModel:
    global _model
    if _model is None:
        logger.info("Loading Whisper model", extra={"model": settings.whisper_model})
        _model = WhisperModel(
            settings.whisper_model,
            device=settings.whisper_device,
            compute_type=settings.whisper_compute_type,
        )
    return _model


def process_audio(payload: SourceInput) -> ProcessedResult:
    if payload.text is not None:
        text = payload.text.strip()
        if not text:
            raise ServiceError("Empty text payload", code="invalid_input", status_code=400)
        return ProcessedResult(text=text, input_type="text", source_url=None, size_bytes=len(text))

    if payload.url is not None:
        audio_bytes, _content_type = fetch_url_bytes(str(payload.url))
        return _transcribe_bytes(audio_bytes, input_type="url", source_url=str(payload.url))

    if payload.file_base64 is not None:
        audio_bytes = decode_base64(payload.file_base64, settings.max_download_bytes)
        return _transcribe_bytes(audio_bytes, input_type="file", source_url=None)

    raise ServiceError("No input provided", code="invalid_input", status_code=400)


def _transcribe_bytes(audio_bytes: bytes, input_type: str, source_url: str | None) -> ProcessedResult:
    if not audio_bytes:
        raise ServiceError("Empty audio payload", code="invalid_input", status_code=400)

    temp_file = tempfile.NamedTemporaryFile(delete=False)
    try:
        temp_file.write(audio_bytes)
        temp_file.close()

        model = _get_model()
        segments, _info = model.transcribe(temp_file.name)
        text_parts: list[str] = []
        for segment in segments:
            if segment.text:
                text_parts.append(segment.text.strip())
        text = " ".join(text_parts).strip()
        if not text:
            raise ServiceError("No speech detected", code="empty_result", status_code=422)

        return ProcessedResult(
            text=text,
            input_type=input_type,
            source_url=source_url,
            size_bytes=len(audio_bytes),
        )
    except ServiceError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("Audio transcription failed", exc_info=True)
        raise ServiceError("Failed to transcribe audio", code="transcription_failed", status_code=500) from exc
    finally:
        try:
            os.unlink(temp_file.name)
        except OSError:
            logger.warning("Failed to delete temp audio file", extra={"path": temp_file.name})
