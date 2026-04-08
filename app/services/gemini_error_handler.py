import logging
import time
from typing import Any, Callable

from app.services.errors import ServiceError

logger = logging.getLogger(__name__)

MODEL_BUSY_MESSAGE = "Model is currently busy. Please try again in a few minutes."

_MAX_RETRIES: int = 5
_RETRY_DELAY_SECONDS: float = 5.0


def call_with_retry(
    fn: Callable[..., Any],
    *args: Any,
    max_retries: int = _MAX_RETRIES,
    delay: float = _RETRY_DELAY_SECONDS,
    validate: Callable[[Any], bool] | None = None,
    **kwargs: Any,
) -> Any:
    """
    Call ``fn(*args, **kwargs)`` with up to *max_retries* retry attempts and a
    *delay*-second sleep between each attempt.

    Retries are triggered by:
    * Any exception raised by ``fn``
    * A ``validate`` callback that returns ``False`` (empty / invalid output)

    ``ServiceError`` is intentionally NOT retried — it indicates a programming
    or configuration error that won't be resolved by retrying.

    Raises the last captured exception (or a generic ServiceError) when all
    attempts are exhausted.
    """
    last_exc: Exception | None = None
    total_attempts = max_retries + 1

    for attempt in range(1, total_attempts + 1):
        try:
            result = fn(*args, **kwargs)
            if validate is None or validate(result):
                return result
            # Response succeeded but output is invalid — treat as retryable failure
            last_exc = ServiceError(
                f"Gemini returned invalid/empty output (attempt {attempt}/{total_attempts})",
                code="model_failed",
                status_code=502,
            )
            logger.warning(
                "Gemini invalid/empty output on attempt %d/%d",
                attempt,
                total_attempts,
            )
        except ServiceError:
            raise  # Programming / config errors — do not retry
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.warning(
                "Gemini API call failed (attempt %d/%d): %s: %s",
                attempt,
                total_attempts,
                type(exc).__name__,
                exc,
            )

        if attempt < total_attempts:
            logger.info("Retrying Gemini call in %.0fs...", delay)
            time.sleep(delay)

    logger.error("Gemini call exhausted all %d attempts", total_attempts)
    if last_exc is not None:
        raise last_exc
    raise ServiceError("Unknown retry failure", code="model_failed", status_code=502)


def validate_has_text(response: Any) -> bool:
    """Return ``True`` when the response contains non-empty text output."""
    text = getattr(response, "text", None)
    if text and str(text).strip():
        return True
    try:
        text = response.candidates[0].content.parts[0].text
        return bool(text and str(text).strip())
    except Exception:  # noqa: BLE001
        return False


def validate_has_function_call(response: Any) -> bool:
    """Return ``True`` when the first candidate part contains a function_call."""
    try:
        return bool(response.candidates[0].content.parts[0].function_call)
    except Exception:  # noqa: BLE001
        return False


def raise_if_model_busy(exc: Exception) -> None:
    if not _is_model_busy_error(exc):
        return
    raise ServiceError(
        MODEL_BUSY_MESSAGE,
        code="model_busy",
        status_code=503,
    ) from exc


def _is_model_busy_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code in {429, 503}:
        return True

    text = str(exc).lower()
    markers = [
        "503",
        "429",
        "unavailable",
        "high demand",
        "resource_exhausted",
        "try again later",
        "try again in a few minutes",
    ]
    return any(marker in text for marker in markers)
