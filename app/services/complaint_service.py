import json
import logging
from typing import Any

from app.core.config import settings
from app.schemas.requests import ComplaintGenerationInput
from app.schemas.responses import ComplaintLaw, ComplaintOutput
from app.services.errors import ServiceError

logger = logging.getLogger(__name__)


def generate_complaint(payload: ComplaintGenerationInput) -> ComplaintOutput:
    content = payload.content.strip()
    if not content:
        raise ServiceError("Empty content", code="invalid_input", status_code=400)

    if not isinstance(payload.core_decision, dict):
        raise ServiceError("Invalid core_decision", code="invalid_input", status_code=400)

    core_decision = payload.core_decision
    required_keys = [
        "bullying",
        "description",
        "phrases",
        "source",
        "impact_action",
        "core_cybercrime",
    ]
    for key in required_keys:
        if key not in core_decision:
            raise ServiceError("Incomplete core_decision", code="invalid_input", status_code=400)

    try:
        from google import genai
        from google.genai import types
    except Exception as exc:  # noqa: BLE001
        logger.error("google-genai not installed", exc_info=True)
        raise ServiceError("Gemini client not available", code="dependency_missing", status_code=500) from exc

    if not settings.gemini_api_key:
        raise ServiceError("GEMINI_API_KEY not configured", code="config_error", status_code=500)

    client = genai.Client(api_key=settings.gemini_api_key)

    prompt = _build_prompt(
        content=content,
        core_decision=core_decision,
        retrieved_laws=payload.retrieved_laws,
    )

    config = types.GenerateContentConfig(
        temperature=0.2,
        top_p=0.9,
        max_output_tokens=2048,
    )

    try:
        response = client.models.generate_content(
            model=settings.gemini_complaint_model,
            contents=prompt,
            config=config,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Gemini complaint generation failed", exc_info=True)
        raise ServiceError("Failed to generate complaint", code="model_failed", status_code=502) from exc

    raw_text = _extract_text(response)
    if not raw_text:
        raise ServiceError("Model returned empty output", code="model_failed", status_code=502)

    parsed = _parse_json(raw_text)
    return _normalize_output(parsed)


def _build_prompt(content: str, core_decision: dict[str, Any], retrieved_laws: list[str]) -> str:
    return (
        "You are a legal assistant for Indian cyber safety.\n\n"
        "Use ONLY the provided retrieved laws. Do NOT hallucinate any laws.\n"
        "Be clear, structured, and supportive.\n\n"
        "Inputs:\n"
        f"CONTENT:\n{content}\n\n"
        f"CORE_DECISION:\n{json.dumps(core_decision, ensure_ascii=False)}\n\n"
        f"RETRIEVED_LAWS:\n{json.dumps(retrieved_laws, ensure_ascii=False)}\n\n"
        "Return ONLY valid JSON with this structure:\n"
        "{\n"
        "  \"summary\": \"...\",\n"
        "  \"detected_phrases\": [\"...\"],\n"
        "  \"applicable_laws\": [\n"
        "    {\"law\": \"Act/Section\", \"description\": \"...\"}\n"
        "  ],\n"
        "  \"recommended_actions\": [\"Step 1...\", \"Step 2...\"]\n"
        "}\n"
    )


def _extract_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if text:
        return str(text).strip()
    try:
        candidate = response.candidates[0]
        part = candidate.content.parts[0]
        return str(getattr(part, "text", "")).strip()
    except Exception:  # noqa: BLE001
        return ""


def _parse_json(raw_text: str) -> dict[str, Any]:
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        pass

    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ServiceError("Invalid model output", code="model_failed", status_code=502)

    try:
        return json.loads(raw_text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ServiceError("Invalid model output", code="model_failed", status_code=502) from exc


def _normalize_output(data: dict[str, Any]) -> ComplaintOutput:
    summary = str(data.get("summary", "")).strip()
    if not summary:
        raise ServiceError("Invalid model output", code="model_failed", status_code=502)

    detected_phrases = data.get("detected_phrases") or []
    if not isinstance(detected_phrases, list):
        detected_phrases = [str(detected_phrases)]
    detected_phrases = [str(item).strip() for item in detected_phrases if str(item).strip()]

    applicable_laws_raw = data.get("applicable_laws") or []
    applicable_laws: list[ComplaintLaw] = []
    if isinstance(applicable_laws_raw, list):
        for item in applicable_laws_raw:
            if isinstance(item, dict):
                law = str(item.get("law", "")).strip()
                description = str(item.get("description", "")).strip()
                if law and description:
                    applicable_laws.append(ComplaintLaw(law=law, description=description))

    recommended_actions_raw = data.get("recommended_actions") or []
    if not isinstance(recommended_actions_raw, list):
        recommended_actions_raw = [str(recommended_actions_raw)]
    recommended_actions = [
        str(item).strip()
        for item in recommended_actions_raw
        if str(item).strip()
    ]

    return ComplaintOutput(
        summary=summary,
        detected_phrases=detected_phrases,
        applicable_laws=applicable_laws,
        recommended_actions=recommended_actions,
    )
