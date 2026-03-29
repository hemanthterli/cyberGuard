import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "cyberGuard")
    ocr_space_api_key: str | None = os.getenv("OCR_SPACE_API_KEY")
    gemini_api_key: str | None = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")
    gemini_enhance_model: str = os.getenv("GEMINI_ENHANCE_MODEL", gemini_model)
    gemini_complaint_model: str = os.getenv("GEMINI_COMPLAINT_MODEL", gemini_model)
    cyberlaw_india_faiss_path: str = os.getenv("CYBERLAW_INDIA_FAISS_PATH", "RAG/faiss_cyberlaw_index_india")
    cyberlaw_uk_faiss_path: str = os.getenv("CYBERLAW_UK_FAISS_PATH", "RAG/faiss_cyberlaw_index_uk")
    cyberlaw_usa_faiss_path: str = os.getenv("CYBERLAW_USA_FAISS_PATH", "RAG/faiss_cyberlaw_index_america")
    cyberlaw_top_k: int = int(os.getenv("CYBERLAW_TOP_K", "4"))
    cyberlaw_embedding_model: str = os.getenv("CYBERLAW_EMBEDDING_MODEL", "gemini-embedding-001")
    cyberlaw_snippet_chars: int = int(os.getenv("CYBERLAW_SNIPPET_CHARS", "1200"))
    whisper_model: str = os.getenv("WHISPER_MODEL", "base")
    whisper_device: str = os.getenv("WHISPER_DEVICE", "cpu")
    whisper_compute_type: str = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
    max_download_bytes: int = int(os.getenv("MAX_DOWNLOAD_BYTES", "15728640"))  # 15 MB
    request_timeout_seconds: int = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "20"))


settings = Settings()
