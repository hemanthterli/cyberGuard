import os
from fastapi import Header, HTTPException


def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    required = os.getenv("API_KEY")
    if not required:
        return
    if x_api_key != required:
        raise HTTPException(status_code=401, detail="Unauthorized")
