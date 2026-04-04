import json
import logging
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.schemas.requests import CyberLawsInput
from app.schemas.responses import ComplaintLaw, ComplaintOutput, RAGSource
from app.services import gemini_error_handler, language_service, location_service
from app.services.errors import ServiceError

logger = logging.getLogger(__name__)

_db_cache: dict[str, Any] = {}
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
    output_language = language_service.normalize_language(payload.language)
    jurisdiction = location_service.normalize_location(payload.location)
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
    rag_source_metas: list[RAGSource] = []
    if not retrieved_laws:
        core_cybercrime = str(core_decision.get("core_cybercrime", "")).strip()
        if core_cybercrime:
            retrieved_laws, rag_source_metas = _retrieve_docs_with_metadata(core_cybercrime, jurisdiction)

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

    jurisdiction_label = location_service.get_location_label(jurisdiction)
    prompt = _build_prompt(content, core_decision, retrieved_laws, jurisdiction_label)

    try:
        response = client.models.generate_content(
            model=settings.gemini_complaint_model,
            contents=prompt,
            config=config,
        )
    except Exception as exc:  # noqa: BLE001
        gemini_error_handler.raise_if_model_busy(exc)
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

    result = _parse_output(args)
    result = ComplaintOutput(
        summary=result.summary,
        detected_phrases=result.detected_phrases,
        applicable_laws=result.applicable_laws,
        recommended_actions=result.recommended_actions,
        rag_sources=rag_source_metas,
    )
    translated = _translate_output(result, output_language)
    return _attach_jurisdiction_notice(translated, jurisdiction, output_language)


def retrieve_laws(core_cybercrime: str, location: str) -> list[str]:
    query = core_cybercrime.strip()
    if not query:
        raise ServiceError("Empty core_cybercrime", code="invalid_input", status_code=400)
    snippets, _ = _retrieve_docs_with_metadata(query, location)
    return snippets


def _retrieve_docs_with_metadata(
    query: str, location: str
) -> tuple[list[str], list[RAGSource]]:
    normalized_location = location_service.normalize_location(location)
    db = _get_db(normalized_location)
    try:
        results = db.similarity_search_with_score(query, k=settings.cyberlaw_top_k)
    except Exception as exc:  # noqa: BLE001
        gemini_error_handler.raise_if_model_busy(exc)
        raise ServiceError("Failed to retrieve cyber laws", code="model_failed", status_code=502) from exc

    snippets: list[str] = []
    sources: list[RAGSource] = []
    for doc, score in results:
        snippets.append(_format_doc(doc, score))
        if hasattr(doc, "metadata") and isinstance(doc.metadata, dict):
            raw_url = doc.metadata.get("url")
            sources.append(
                RAGSource(
                    title=str(doc.metadata.get("title") or ""),
                    url=str(raw_url) if raw_url else None,
                    category=doc.metadata.get("category") or None,
                )
            )
    return snippets, sources


def _get_db(location: str):
    global _embeddings
    if location in _db_cache:
        return _db_cache[location]

    try:
        from langchain_community.vectorstores import FAISS
        from langchain_google_genai import GoogleGenerativeAIEmbeddings
    except Exception as exc:  # noqa: BLE001
        logger.error("LangChain dependencies missing", exc_info=True)
        raise ServiceError("RAG dependencies not available", code="dependency_missing", status_code=500) from exc

    if not settings.gemini_api_key:
        raise ServiceError("GEMINI_API_KEY not configured", code="config_error", status_code=500)

    index_path = _get_index_path_for_location(location)
    if not index_path.is_absolute():
        base_dir = Path(__file__).resolve().parents[2]
        index_path = base_dir / index_path

    if not index_path.exists():
        raise ServiceError("Cyber law index not found", code="config_error", status_code=500)

    if _embeddings is None:
        _embeddings = GoogleGenerativeAIEmbeddings(model=settings.cyberlaw_embedding_model)

    db = FAISS.load_local(
        str(index_path),
        _embeddings,
        allow_dangerous_deserialization=True,
    )
    _db_cache[location] = db
    return db


def _get_index_path_for_location(location: str) -> Path:
    location_paths = {
        "india": settings.cyberlaw_india_faiss_path,
        "uk": settings.cyberlaw_uk_faiss_path,
        "usa": settings.cyberlaw_usa_faiss_path,
    }
    selected = location_paths.get(location)
    if not selected:
        raise ServiceError("Unsupported location", code="invalid_input", status_code=400)
    return Path(selected)


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


def _build_prompt(
    content: str,
    core_decision: dict[str, Any],
    retrieved_laws: list[str],
    jurisdiction: str,
) -> str:
    return (
        f"You are a legal assistant for {jurisdiction} cyber safety.\n\n"
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


def _translate_output(result: ComplaintOutput, language: str) -> ComplaintOutput:
    translated_summary = language_service.translate_object_values(
        {"summary": result.summary},
        language,
        context="cyber laws summary",
    )["summary"]

    translated_laws: list[ComplaintLaw] = []
    for item in result.applicable_laws:
        translated_description = language_service.translate_text(
            item.description,
            language,
            context="cyber law description",
        )
        translated_laws.append(ComplaintLaw(law=item.law, description=translated_description))

    translated_actions = [
        language_service.translate_text(action, language, context="recommended action")
        for action in result.recommended_actions
    ]
    translated_phrases = [
        language_service.translate_text(phrase, language, context="detected phrase")
        for phrase in result.detected_phrases
    ]

    return ComplaintOutput(
        summary=translated_summary,
        detected_phrases=translated_phrases,
        applicable_laws=translated_laws,
        recommended_actions=translated_actions,
        country=result.country,
        rag_sources=result.rag_sources,
    )


def _attach_jurisdiction_notice(result: ComplaintOutput, location: str, language: str) -> ComplaintOutput:
    country_label = location_service.get_location_label(location)
    notice = f"The following cyber laws are based on {country_label}."
    localized_notice = language_service.translate_text(
        notice,
        language,
        context="jurisdiction notice",
    )
    summary_with_notice = f"{localized_notice}\n\n{result.summary}" if result.summary else localized_notice
    return ComplaintOutput(
        summary=summary_with_notice,
        detected_phrases=result.detected_phrases,
        applicable_laws=result.applicable_laws,
        recommended_actions=result.recommended_actions,
        country=country_label,
        rag_sources=result.rag_sources,
    )
