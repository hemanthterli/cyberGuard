import logging
from typing import Any

from app.core.config import settings
from app.schemas.requests import CoreDecisionInput
from app.schemas.responses import CoreDecisionData
from app.services import gemini_error_handler
from app.services.errors import ServiceError
from app.services import language_service

logger = logging.getLogger(__name__)


_DECISION_FUNCTION = {
    "name": "analyze_bullying_content",
    "description": "Analyze content and decide if it is bullying, harassment, or negative targeting of a person",
    "parameters": {
        "type": "object",
        "properties": {
            "bullying": {
                "type": "string",
                "description": "yes or no",
            },
            "description": {
                "type": "string",
                "description": "Short explanation (15-20 words)",
            },
            "phrases": {
                "type": "string",
                "description": "Exact phrases from content that show bullying",
            },
            "source": {
                "type": "string",
                "description": "Source link given in input",
            },
            "impact_action": {
                "type": "string",
                "description": "Possible action user can take like report, complaint, legal action",
            },
            "core_cybercrime": {
                "type": "string",
                "description": "20-25 word summary of the detected cybercrime",
            },
        },
        "required": [
            "bullying",
            "description",
            "phrases",
            "source",
            "impact_action",
            "core_cybercrime",
        ],
    },
}


def analyze_bullying(data: CoreDecisionInput) -> CoreDecisionData:
    output_language = language_service.normalize_language(data.language)
    input_payload = {
        "source": data.source.strip(),
        "source_type": data.source_type.strip(),
        "content": data.content.strip(),
        "user_context": (data.user_context or "").strip() or None,
    }

    if not input_payload["source"]:
        raise ServiceError("Empty source", code="invalid_input", status_code=400)
    if not input_payload["source_type"]:
        raise ServiceError("Empty source_type", code="invalid_input", status_code=400)
    if not input_payload["content"]:
        raise ServiceError("Empty content", code="invalid_input", status_code=400)

    try:
        from google import genai
        from google.genai import types
    except Exception as exc:  # noqa: BLE001
        logger.error("google-genai not installed", exc_info=True)
        raise ServiceError("Gemini client not available", code="dependency_missing", status_code=500) from exc

    if not settings.gemini_api_key:
        raise ServiceError("GEMINI_API_KEY not configured", code="config_error", status_code=500)

    client = genai.Client(api_key=settings.gemini_api_key)

    tools = types.Tool(function_declarations=[_DECISION_FUNCTION])
    config = types.GenerateContentConfig(
        tools=[tools],
        tool_config=types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(mode="ANY")
        ),
    )

    prompt = _build_prompt(input_payload)

    try:
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config=config,
        )
    except Exception as exc:  # noqa: BLE001
        gemini_error_handler.raise_if_model_busy(exc)
        logger.error("Gemini request failed", exc_info=True)
        raise ServiceError("Failed to run decision model", code="model_failed", status_code=502) from exc

    try:
        candidate = response.candidates[0]
        part = candidate.content.parts[0]
    except Exception as exc:  # noqa: BLE001
        logger.error("Gemini response missing candidates", exc_info=True)
        raise ServiceError("Model returned no candidates", code="model_failed", status_code=502) from exc

    if not getattr(part, "function_call", None):
        logger.warning("Gemini returned no function call")
        raise ServiceError("Model did not return structured output", code="model_failed", status_code=502)

    call = part.function_call
    args = getattr(call, "args", None)
    if not isinstance(args, dict):
        try:
            args = dict(args)  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001
            logger.error("Invalid function args", exc_info=True)
            raise ServiceError("Invalid model output", code="model_failed", status_code=502) from exc

    result = _parse_output(args, input_payload["source"])
    return _translate_output(result, output_language)


def _build_prompt(payload: dict[str, Any]) -> str:
    return (
        "You are a cyber safety analyzer.\n\n"
        "Input JSON contains:\n"
        "- source\n"
        "- source_type\n"
        "- content\n"
        "- user_context\n\n"
        "Your job:\n\n"
        "1. Detect if content is bullying or targeting a person negatively\n"
        "2. If no -> bullying = no\n"
        "3. If yes -> bullying = yes\n"
        "4. Extract exact phrases causing bullying\n"
        "5. Give short description\n"
        "6. Return source exactly\n"
        "7. Suggest impact action\n"
        "8. Provide core_cybercrime: 20-25 word summary of the cybercrime saying which domain that crime comes under\n\n"
        f"Input:\n\n{payload}\n"
    )


def _parse_output(args: dict[str, Any], fallback_source: str) -> CoreDecisionData:
    def _get(key: str) -> str:
        value = args.get(key)
        if value is None:
            raise ServiceError("Incomplete model output", code="model_failed", status_code=502)
        text = str(value).strip()
        if not text:
            raise ServiceError("Incomplete model output", code="model_failed", status_code=502)
        return text

    return CoreDecisionData(
        bullying=_get("bullying"),
        description=_get("description"),
        phrases=_get("phrases"),
        source=_get("source") if args.get("source") else fallback_source,
        impact_action=_get("impact_action"),
        core_cybercrime=_get("core_cybercrime"),
    )


def _translate_output(result: CoreDecisionData, language: str) -> CoreDecisionData:
    translated_fields = language_service.translate_object_values(
        {
            "description": result.description,
            "phrases": result.phrases,
            "impact_action": result.impact_action,
            "core_cybercrime": result.core_cybercrime,
        },
        language,
        context="final analysis output",
    )

    return CoreDecisionData(
        bullying=result.bullying,
        description=translated_fields["description"],
        phrases=translated_fields["phrases"],
        source=result.source,
        impact_action=translated_fields["impact_action"],
        core_cybercrime=translated_fields["core_cybercrime"],
    )
