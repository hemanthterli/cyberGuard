import logging
import re
import time
from app.services.errors import ServiceError

logger = logging.getLogger(__name__)

_LANGUAGE_ALIASES = {
    "en": "english",
    "english": "english",
    "hi": "hindi",
    "hindi": "hindi",
    "te": "telugu",
    "telugu": "telugu",
}

_LANGUAGE_CODES = {
    "english": "en",
    "hindi": "hi",
    "telugu": "te",
}

_PROTECTED_PATTERNS = [
    re.compile(r"\[[^\[\]\n]+\]"),
    re.compile(r"https?://[^\s]+"),
    re.compile(r"www\.[^\s]+"),
    re.compile(r"\b(?:Section|Sec\.?|Article|Act|IPC|CrPC|IT Act)\s*[A-Za-z0-9()./\-]+\b", re.IGNORECASE),
]

_TOKEN_PATTERN = re.compile(r"__PROTECTED_\d+__")

_MAX_TRANSLATION_CHARS = 3500
_TRANSLATION_RETRIES = 3


def normalize_language(language: str | None) -> str:
    if language is None:
        return "english"
    key = str(language).strip().lower()
    if not key:
        return "english"
    normalized = _LANGUAGE_ALIASES.get(key)
    if not normalized:
        raise ServiceError("Unsupported language", code="invalid_input", status_code=400)
    return normalized


def translate_text(text: str, target_language: str, *, context: str) -> str:
    normalized = normalize_language(target_language)
    if normalized == "english":
        return text
    if not text.strip():
        return text

    source_code = _LANGUAGE_CODES["english"]
    target_code = _LANGUAGE_CODES[normalized]
    translator = _build_translator(source_code, target_code)

    protected_text, token_map = _protect_fragments(text)
    translated = _translate_with_chunking(protected_text, translator, context=context)
    return _restore_fragments(translated, token_map)


def translate_object_values(values: dict[str, str], target_language: str, *, context: str) -> dict[str, str]:
    normalized = normalize_language(target_language)
    if normalized == "english":
        return values
    if not values:
        return values

    source_code = _LANGUAGE_CODES["english"]
    target_code = _LANGUAGE_CODES[normalized]
    translator = _build_translator(source_code, target_code)

    result: dict[str, str] = {}
    for key, original_value in values.items():
        text_value = str(original_value).strip()
        if not text_value:
            result[key] = str(original_value)
            continue
        protected_text, token_map = _protect_fragments(text_value)
        translated = _translate_with_chunking(protected_text, translator, context=f"{context}:{key}")
        restored = _restore_fragments(translated, token_map).strip()
        result[key] = restored or str(original_value)
    return result


def _build_translator(source_code: str, target_code: str):
    try:
        from deep_translator import GoogleTranslator
    except Exception as exc:  # noqa: BLE001
        logger.error("deep-translator not installed", exc_info=True)
        raise ServiceError("Translation dependency missing", code="dependency_missing", status_code=500) from exc

    try:
        return GoogleTranslator(source=source_code, target=target_code)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to initialize translator", exc_info=True)
        raise ServiceError("Translator initialization failed", code="dependency_missing", status_code=500) from exc


def _protect_fragments(text: str) -> tuple[str, dict[str, str]]:
    token_map: dict[str, str] = {}
    protected = text
    token_index = 0

    for pattern in _PROTECTED_PATTERNS:
        def _replace(match: re.Match[str]) -> str:
            nonlocal token_index
            token = f"__PROTECTED_{token_index}__"
            token_map[token] = match.group(0)
            token_index += 1
            return token

        protected = pattern.sub(_replace, protected)

    return protected, token_map


def _restore_fragments(text: str, token_map: dict[str, str]) -> str:
    def _replace(match: re.Match[str]) -> str:
        token = match.group(0)
        return token_map.get(token, token)

    return _TOKEN_PATTERN.sub(_replace, text)


def _translate_with_chunking(text: str, translator, *, context: str) -> str:
    chunks = _split_text(text, _MAX_TRANSLATION_CHARS)
    translated_chunks: list[str] = []
    for index, chunk in enumerate(chunks):
        translated_chunks.append(_translate_chunk(chunk, translator, context=f"{context}:{index}"))
    return "".join(translated_chunks)


def _split_text(text: str, max_len: int) -> list[str]:
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    remaining = text
    while len(remaining) > max_len:
        split_at = remaining.rfind("\n", 0, max_len)
        if split_at < int(max_len * 0.6):
            split_at = remaining.rfind(" ", 0, max_len)
        if split_at <= 0:
            split_at = max_len
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:]
    if remaining:
        chunks.append(remaining)
    return chunks


def _translate_chunk(chunk: str, translator, *, context: str) -> str:
    if not chunk.strip():
        return chunk

    last_error: Exception | None = None
    for attempt in range(1, _TRANSLATION_RETRIES + 1):
        try:
            translated = translator.translate(chunk)
            translated_text = str(translated).strip()
            if not translated_text:
                raise ServiceError("Translation returned empty output", code="model_failed", status_code=502)

            leading_ws = re.match(r"^\s*", chunk)
            trailing_ws = re.search(r"\s*$", chunk)
            return f"{leading_ws.group(0)}{translated_text}{trailing_ws.group(0)}"
        except ServiceError:
            raise
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < _TRANSLATION_RETRIES:
                time.sleep(0.6 * attempt)
                continue
            logger.error("Translation failed", extra={"context": context}, exc_info=True)

    raise ServiceError("Failed to translate output", code="model_failed", status_code=502) from last_error
