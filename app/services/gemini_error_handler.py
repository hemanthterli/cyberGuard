from app.services.errors import ServiceError

MODEL_BUSY_MESSAGE = "Model is currently busy. Please try again in a few minutes."


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
