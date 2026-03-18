import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "cyberGuard")
    api_key: str | None = os.getenv("API_KEY")
    ocr_space_api_key: str | None = os.getenv("OCR_SPACE_API_KEY")
    whisper_model: str = os.getenv("WHISPER_MODEL", "base")
    whisper_device: str = os.getenv("WHISPER_DEVICE", "cpu")
    whisper_compute_type: str = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
    max_download_bytes: int = int(os.getenv("MAX_DOWNLOAD_BYTES", "15728640"))  # 15 MB
    request_timeout_seconds: int = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "20"))


settings = Settings()
