from app.services.errors import ServiceError


def bytes_to_text(data: bytes) -> str:
    if not data:
        raise ServiceError("Empty text file", code="invalid_input", status_code=400)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace")
