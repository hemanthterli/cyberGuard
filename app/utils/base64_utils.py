import base64

from app.services.errors import ServiceError


def decode_base64(data: str, max_bytes: int) -> bytes:
    try:
        decoded = base64.b64decode(data, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise ServiceError("Invalid base64 payload", code="invalid_input", status_code=400) from exc
    if len(decoded) == 0:
        raise ServiceError("Empty file payload", code="invalid_input", status_code=400)
    if len(decoded) > max_bytes:
        raise ServiceError("File payload too large", code="payload_too_large", status_code=413)
    return decoded
