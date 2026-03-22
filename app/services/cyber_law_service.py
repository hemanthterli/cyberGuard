import json
import logging
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.schemas.requests import CyberLawsInput
from app.schemas.responses import ComplaintLaw, ComplaintOutput
from app.services.errors import ServiceError

logger = logging.getLogger(__name__)

_db = None
_embeddings = None

_COMPLAINT_FUNCTION = {
    "name": "generate_cyber_law_complaint",
    "description": "Generate structured legal analysis and complaint guidance",
    "parameters": {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "Explanation of the issue"},
            "detected_phrases": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Key phrases from the content",
            },
            "applicable_laws": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "law": {"type": "string"},
                        "description": {"type": "string"},
                    },
                    "required": ["law", "description"],
                },
                "description": "Relevant laws drawn from retrieved content",
            },
            "recommended_actions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Actionable next steps",
            },
        },
        "required": ["summary", "detected_phrases", "applicable_laws", "recommended_actions"],
    },
}


def analyze_cyber_laws(payload: CyberLawsInput) -> ComplaintOutput:
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

    retrieved_laws = [law for law in payload.retrieved_laws if isinstance(law, str) and law.strip()]
    if not retrieved_laws:
        core_cybercrime = str(core_decision.get("core_cybercrime", "")).strip()
        if core_cybercrime:
            retrieved_laws = retrieve_laws(core_cybercrime)

    try:
        from google import genai
        from google.genai import types
    except Exception as exc:  # noqa: BLE001
        logger.error("google-genai not installed", exc_info=True)
        raise ServiceError("Gemini client not available", code="dependency_missing", status_code=500) from exc

    if not settings.gemini_api_key:
        raise ServiceError("GEMINI_API_KEY not configured", code="config_error", status_code=500)

    client = genai.Client(api_key=settings.gemini_api_key)

    tools = types.Tool(function_declarations=[_COMPLAINT_FUNCTION])
    config = types.GenerateContentConfig(
        tools=[tools],
        tool_config=types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(mode="ANY")
        ),
        temperature=0.2,
        top_p=0.9,
        max_output_tokens=2048,
    )

    prompt = _build_prompt(content, core_decision, retrieved_laws)

    try:
        response = client.models.generate_content(
            model=settings.gemini_complaint_model,
            contents=prompt,
            config=config,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Gemini complaint generation failed", exc_info=True)
        raise ServiceError("Failed to generate complaint", code="model_failed", status_code=502) from exc

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

    return _parse_output(args)


def retrieve_laws(core_cybercrime: str) -> list[str]:
    query = core_cybercrime.strip()
    if not query:
        raise ServiceError("Empty core_cybercrime", code="invalid_input", status_code=400)

    db = _get_db()
    results = db.similarity_search_with_score(query, k=settings.cyberlaw_top_k)
    snippets: list[str] = []
    for doc, score in results:
        snippets.append(_format_doc(doc, score))

    return snippets


def _get_db():
    global _db, _embeddings
    if _db is not None:
        return _db

    try:
        from langchain_community.vectorstores import FAISS
        from langchain_google_genai import GoogleGenerativeAIEmbeddings
    except Exception as exc:  # noqa: BLE001
        logger.error("LangChain dependencies missing", exc_info=True)
        raise ServiceError("RAG dependencies not available", code="dependency_missing", status_code=500) from exc

    if not settings.gemini_api_key:
        raise ServiceError("GEMINI_API_KEY not configured", code="config_error", status_code=500)

    index_path = Path(settings.cyberlaw_faiss_path)
    if not index_path.is_absolute():
        base_dir = Path(__file__).resolve().parents[2]
        index_path = base_dir / index_path

    if not index_path.exists():
        raise ServiceError("Cyber law index not found", code="config_error", status_code=500)

    _embeddings = GoogleGenerativeAIEmbeddings(model=settings.cyberlaw_embedding_model)
    _db = FAISS.load_local(
        str(index_path),
        _embeddings,
        allow_dangerous_deserialization=True,
    )
    return _db


def _format_doc(doc, score: float) -> str:
    text = doc.page_content.strip()
    if len(text) > settings.cyberlaw_snippet_chars:
        text = text[: settings.cyberlaw_snippet_chars].rstrip() + "..."
    title = doc.metadata.get("title") if hasattr(doc, "metadata") else None
    url = doc.metadata.get("url") if hasattr(doc, "metadata") else None
    prefix_parts = []
    if title:
        prefix_parts.append(f"Title: {title}")
    if url:
        prefix_parts.append(f"URL: {url}")
    prefix_parts.append(f"Score: {score:.4f}")
    prefix = "\n".join(prefix_parts)
    return f"{prefix}\n{text}"


def _build_prompt(content: str, core_decision: dict[str, Any], retrieved_laws: list[str]) -> str:
    return (
        "You are a legal assistant for Indian cyber safety.\n\n"
        "Use ONLY the provided retrieved laws. Do NOT hallucinate any laws.\n"
        "Be clear, structured, and supportive.\n\n"
        "Inputs:\n"
        f"CONTENT:\n{content}\n\n"
        f"CORE_DECISION:\n{json.dumps(core_decision, ensure_ascii=False)}\n\n"
        f"RETRIEVED_LAWS:\n{json.dumps(retrieved_laws, ensure_ascii=False)}\n\n"
        "Return the output via function call only."
    )


def _parse_output(args: dict[str, Any]) -> ComplaintOutput:
    def _get_text(key: str) -> str:
        value = args.get(key)
        if value is None:
            raise ServiceError("Incomplete model output", code="model_failed", status_code=502)
        text = str(value).strip()
        if not text:
            raise ServiceError("Incomplete model output", code="model_failed", status_code=502)
        return text

    detected_phrases = args.get("detected_phrases") or []
    if not isinstance(detected_phrases, list):
        detected_phrases = [str(detected_phrases)]
    detected_phrases = [str(item).strip() for item in detected_phrases if str(item).strip()]

    applicable_laws_raw = args.get("applicable_laws") or []
    applicable_laws: list[ComplaintLaw] = []
    if isinstance(applicable_laws_raw, list):
        for item in applicable_laws_raw:
            if isinstance(item, dict):
                law = str(item.get("law", "")).strip()
                description = str(item.get("description", "")).strip()
                if law and description:
                    applicable_laws.append(ComplaintLaw(law=law, description=description))

    recommended_actions = args.get("recommended_actions") or []
    if not isinstance(recommended_actions, list):
        recommended_actions = [str(recommended_actions)]
    recommended_actions = [
        str(item).strip()
        for item in recommended_actions
        if str(item).strip()
    ]

    return ComplaintOutput(
        summary=_get_text("summary"),
        detected_phrases=detected_phrases,
        applicable_laws=applicable_laws,
        recommended_actions=recommended_actions,
    )
