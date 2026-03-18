from dataclasses import dataclass


@dataclass(frozen=True)
class ProcessedResult:
    text: str
    input_type: str
    source_url: str | None
    size_bytes: int | None
