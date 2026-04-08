import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

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

_RERANK_FUNCTION = {
    "name": "filter_and_rank_laws",
    "description": (
        "Evaluate all retrieved cyber laws and regulations. "
        "Filter out laws that are NOT relevant to the user query. "
        "Return ONLY the highly relevant laws, re-ranked by semantic relevance to the query "
        "(most relevant first). Do not include irrelevant or duplicate laws."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "relevant_laws": {
                "type": "array",
                "description": "Filtered and re-ranked laws, most relevant first",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Name of the law or provision"},
                        "description": {
                            "type": "string",
                            "description": "Summary of the law and its relevance to the query",
                        },
                        "source": {
                            "type": "string",
                            "description": "Origin: 'rag' or 'google_search'",
                        },
                        "url": {"type": "string", "description": "Reference URL if available"},
                        "country": {"type": "string", "description": "Country or jurisdiction"},
                    },
                    "required": ["title", "description", "source", "country"],
                },
            }
        },
        "required": ["relevant_laws"],
    },
}

_IST = timezone(timedelta(hours=5, minutes=30))


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

    # --- Initialise Gemini client early (required by enrichment pipeline) ---
    try:
        from google import genai
        from google.genai import types
    except Exception as exc:  # noqa: BLE001
        logger.error("google-genai not installed", exc_info=True)
        raise ServiceError("Gemini client not available", code="dependency_missing", status_code=500) from exc

    if not settings.gemini_api_key:
        raise ServiceError("GEMINI_API_KEY not configured", code="config_error", status_code=500)

    client = genai.Client(api_key=settings.gemini_api_key)

    # --- RAG retrieval: get structured results for the enrichment pipeline ---
    jurisdiction_label = location_service.get_location_label(jurisdiction)
    core_cybercrime = str(core_decision.get("core_cybercrime", "")).strip()
    rag_structured: list[dict[str, Any]] = []
    rag_source_metas: list[RAGSource] = []

    supplied_laws = [law for law in payload.retrieved_laws if isinstance(law, str) and law.strip()]
    if supplied_laws:
        rag_structured = _format_supplied_as_structured(supplied_laws, jurisdiction_label)
    elif core_cybercrime:
        rag_structured, rag_source_metas = _retrieve_structured_laws(
            core_cybercrime, jurisdiction, jurisdiction_label
        )

    # --- Enrichment pipeline: Google Search + Gemini LLM re-ranking ---
    search_query_hint = core_cybercrime or content[:200]
    enriched_laws, google_sources = _run_enrichment_pipeline(
        query=search_query_hint,
        country_label=jurisdiction_label,
        rag_structured=rag_structured,
        client=client,
    )
    rag_source_metas = rag_source_metas + google_sources

    # Convert enriched (or original RAG) laws to string snippets for prompt injection
    if enriched_laws:
        retrieved_laws: list[str] = [_structured_to_snippet(law) for law in enriched_laws]
    else:
        retrieved_laws = [_structured_to_snippet(law) for law in rag_structured]

    # --- Complaint generation config (unchanged) ---
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

    prompt = _build_prompt(content, core_decision, retrieved_laws, jurisdiction_label)

    try:
        response = gemini_error_handler.call_with_retry(
            client.models.generate_content,
            model=settings.gemini_complaint_model,
            contents=prompt,
            config=config,
            validate=gemini_error_handler.validate_has_function_call,
        )
    except ServiceError:
        raise
    except Exception as exc:  # noqa: BLE001
        gemini_error_handler.raise_if_model_busy(exc)
        logger.error("Gemini complaint generation failed after retries", exc_info=True)
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


# ---------------------------------------------------------------------------
# Enrichment pipeline helpers
# ---------------------------------------------------------------------------


def _retrieve_structured_laws(
    query: str, location: str, country_label: str
) -> tuple[list[dict[str, Any]], list[RAGSource]]:
    """Retrieve laws from FAISS as structured dicts suitable for the enrichment pipeline."""
    normalized_location = location_service.normalize_location(location)
    db = _get_db(normalized_location)
    try:
        results = db.similarity_search_with_score(query, k=settings.cyberlaw_top_k)
    except Exception as exc:  # noqa: BLE001
        gemini_error_handler.raise_if_model_busy(exc)
        raise ServiceError("Failed to retrieve cyber laws", code="model_failed", status_code=502) from exc

    structured: list[dict[str, Any]] = []
    sources: list[RAGSource] = []
    for doc, score in results:
        text = doc.page_content.strip()
        if len(text) > settings.cyberlaw_snippet_chars:
            text = text[: settings.cyberlaw_snippet_chars].rstrip() + "..."
        metadata = doc.metadata if hasattr(doc, "metadata") else {}
        title = str(metadata.get("title") or "")
        url = str(metadata.get("url") or "")
        structured.append(
            {
                "title": title or f"Cyber Law (relevance: {score:.4f})",
                "description": text,
                "source": "rag",
                "url": url,
                "country": country_label,
            }
        )
        sources.append(
            RAGSource(
                title=title,
                url=url if url else None,
                category=metadata.get("category") or None,
            )
        )
    return structured, sources


def _format_supplied_as_structured(
    supplied_laws: list[str], country_label: str
) -> list[dict[str, Any]]:
    """Convert pre-supplied string law snippets to structured dicts for the enrichment pipeline."""
    return [
        {
            "title": f"Pre-supplied Law {i + 1}",
            "description": law,
            "source": "rag",
            "url": "",
            "country": country_label,
        }
        for i, law in enumerate(supplied_laws)
    ]


def _structured_to_snippet(law: dict[str, Any]) -> str:
    """Convert a structured law dict back to a readable string snippet for prompt injection."""
    parts: list[str] = []
    if law.get("title"):
        parts.append(f"Title: {law['title']}")
    if law.get("url"):
        parts.append(f"URL: {law['url']}")
    if law.get("source"):
        parts.append(f"Source: {law['source']}")
    if law.get("country"):
        parts.append(f"Country: {law['country']}")
    description = str(law.get("description") or "").strip()
    if description:
        parts.append(description)
    return "\n".join(parts)


def _google_search_laws(
    query: str, country_label: str, client: Any
) -> tuple[list[dict[str, Any]], str]:
    """
    Perform a Google-grounded Gemini search for country-specific cyber laws.

    Returns (structured_law_dicts, search_query_used).
    Falls back to ([], constructed_search_query) on any error.
    """
    # Build a meaningful default search query incorporating country context
    search_query = f"cyber law {query} {country_label}"
    try:
        from google.genai import types as gtypes

        response = gemini_error_handler.call_with_retry(
            client.models.generate_content,
            model=settings.gemini_model,
            contents=(
                f"Summarize the most relevant cyber laws, regulations, and legal provisions "
                f"for the following issue in {country_label}: {query}"
            ),
            config=gtypes.GenerateContentConfig(
                tools=[{"google_search": {}}],
                temperature=0.1,
            ),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Google Search call failed during enrichment after retries", exc_info=True)
        return [], search_query

    candidates = getattr(response, "candidates", None)
    if not candidates:
        return [], search_query

    candidate = candidates[0]
    answer_text = ""
    for part in getattr(candidate.content, "parts", []):
        if hasattr(part, "text") and part.text:
            answer_text += part.text

    grounding = getattr(candidate, "grounding_metadata", None)
    grounding_chunks: list[Any] = []
    if grounding and hasattr(grounding, "grounding_chunks"):
        grounding_chunks = list(grounding.grounding_chunks or [])

    # Use search queries generated by the model — filter out empty/whitespace entries
    if grounding and hasattr(grounding, "web_search_queries"):
        used_queries = [
            str(q).strip()
            for q in (grounding.web_search_queries or [])
            if q and str(q).strip()
        ]
        if used_queries:
            search_query = "; ".join(used_queries[:3])
        # else: keep the constructed fallback search_query

    structured: list[dict[str, Any]] = []
    if grounding_chunks:
        for i, chunk in enumerate(grounding_chunks):
            if hasattr(chunk, "web") and chunk.web:
                uri = str(chunk.web.uri or "").strip()
                structured.append(
                    {
                        # Share the synthesized answer only on the first entry to avoid repetition
                        "title": str(chunk.web.title or f"Source {i + 1}"),
                        "description": answer_text[:2000] if i == 0 else "",
                        "source": "google_search",
                        "url": uri,
                        "country": country_label,
                    }
                )
    elif answer_text:
        # No grounding chunks — use the synthesised text as a single entry.
        # Record the search_query as a reference so logs stay traceable.
        structured.append(
            {
                "title": f"Google Search: {search_query}",
                "description": answer_text[:2000],
                "source": "google_search",
                "url": "",
                "country": country_label,
                "search_query_used": search_query,
            }
        )

    logger.info(
        "Google Search returned %d structured entries for query: %s",
        len(structured),
        search_query,
    )
    return structured, search_query


def _rerank_with_gemini(
    user_query: str,
    search_query: str,
    all_laws: list[dict[str, Any]],
    client: Any,
) -> list[dict[str, Any]]:
    """
    Use Gemini function calling to filter and re-rank all retrieved laws by relevance.

    Returns a filtered, re-ranked list (most relevant first).
    Falls back to returning all_laws unchanged on any error.
    """
    if not all_laws:
        return []

    try:
        from google.genai import types as gtypes
    except Exception as exc:  # noqa: BLE001
        logger.warning("google-genai import failed in re-ranking", exc_info=True)
        return all_laws

    tools = gtypes.Tool(function_declarations=[_RERANK_FUNCTION])
    rerank_config = gtypes.GenerateContentConfig(
        tools=[tools],
        tool_config=gtypes.ToolConfig(
            function_calling_config=gtypes.FunctionCallingConfig(mode="ANY")
        ),
        temperature=0.1,
        max_output_tokens=4096,
    )

    laws_json = json.dumps(all_laws, ensure_ascii=False)
    prompt = (
        f"User query: {user_query}\n"
        f"Country-aware search query used: {search_query}\n\n"
        f"Retrieved laws ({len(all_laws)} total):\n{laws_json}\n\n"
        "Evaluate each law. Return ONLY the ones that are highly relevant to the user's query. "
        "Re-rank by semantic relevance. Remove duplicates and irrelevant entries."
    )

    try:
        response = gemini_error_handler.call_with_retry(
            client.models.generate_content,
            model=settings.gemini_complaint_model,
            contents=prompt,
            config=rerank_config,
            validate=gemini_error_handler.validate_has_function_call,
        )
    except Exception as exc:  # noqa: BLE001  — always degrade gracefully
        logger.warning("Gemini re-ranking call failed after retries, using all laws: %s", exc)
        return all_laws

    try:
        candidate = response.candidates[0]
        part = candidate.content.parts[0]
        if not getattr(part, "function_call", None):
            logger.warning("Re-ranking: Gemini returned no function call, using all laws")
            return all_laws

        call = part.function_call
        args = getattr(call, "args", None)
        if not isinstance(args, dict):
            args = dict(args)  # type: ignore[arg-type]

        relevant_laws = args.get("relevant_laws")
        if not isinstance(relevant_laws, list) or not relevant_laws:
            logger.warning("Re-ranking returned empty relevant_laws, using all laws")
            return all_laws

        reranked = [
            {
                "title": str(law.get("title", "")),
                "description": str(law.get("description", "")),
                "source": str(law.get("source", "rag")),
                "url": str(law.get("url", "")),
                "country": str(law.get("country", "")),
            }
            for law in relevant_laws
            if isinstance(law, dict) and law.get("title")
        ]
        logger.info("Re-ranking reduced %d laws -> %d relevant laws", len(all_laws), len(reranked))
        return reranked or all_laws
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to parse re-ranking response, using all laws", exc_info=True)
        return all_laws


def _run_enrichment_pipeline(
    query: str,
    country_label: str,
    rag_structured: list[dict[str, Any]],
    client: Any,
) -> tuple[list[dict[str, Any]], list[RAGSource]]:
    """
    Orchestrate the enrichment pipeline:
      1. Google Search (country-aware)
      2. Merge RAG + Google results
      3. Gemini LLM re-ranking (function calling)
      4. Write enrichment log (IST timestamp subfolder)

    Returns (enriched_law_dicts, google_rag_sources).
    Degrades gracefully on partial failures — never raises.
    """
    session_id = str(uuid4())
    google_structured: list[dict[str, Any]] = []
    google_rag_sources: list[RAGSource] = []
    search_query = f"{query} {country_label}"

    # Step 1 — Google Search
    try:
        google_structured, search_query = _google_search_laws(query, country_label, client)
        google_rag_sources = [
            RAGSource(
                title=law.get("title", ""),
                url=law.get("url") or None,
                category="google_search",
            )
            for law in google_structured
            if law.get("url")
        ]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Google Search step failed in enrichment pipeline", exc_info=True)

    # Step 2 — Merge
    all_laws = rag_structured + google_structured

    if not all_laws:
        logger.warning("Enrichment pipeline: no laws from any source (query=%s)", query)
        _write_enrichment_log(
            session_id=session_id,
            user_query=query,
            country=country_label,
            search_query=search_query,
            rag_results=[],
            google_results=[],
            reranked_laws=[],
        )
        return [], google_rag_sources
    # Step 3 — LLM re-ranking
    reranked: list[dict[str, Any]] = all_laws  # safe default
    try:
        reranked = _rerank_with_gemini(query, search_query, all_laws, client)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Re-ranking step failed in enrichment pipeline, using all laws", exc_info=True)

    # Step 4 — Log
    _write_enrichment_log(
        session_id=session_id,
        user_query=query,
        country=country_label,
        search_query=search_query,
        rag_results=rag_structured,
        google_results=google_structured,
        reranked_laws=reranked,
    )

    return reranked, google_rag_sources


def _write_enrichment_log(
    session_id: str,
    user_query: str,
    country: str,
    search_query: str,
    rag_results: list[dict[str, Any]],
    google_results: list[dict[str, Any]],
    reranked_laws: list[dict[str, Any]],
) -> None:
    """Write the enrichment pipeline log to /logs/<DD_MM_YYYY_HH_MM_SS>/ (IST)."""
    now_ist = datetime.now(_IST)
    timestamp_folder = now_ist.strftime("%d_%m_%Y_%H_%M_%S")
    base_dir = Path(__file__).resolve().parents[2]
    log_dir = base_dir / "logs" / timestamp_folder
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_data: dict[str, Any] = {
            "session_id": session_id,
            "timestamp_ist": now_ist.isoformat(),
            "user_query": user_query,
            "country": country,
            "generated_search_query": search_query,
            "rag_results_count": len(rag_results),
            "google_results_count": len(google_results),
            "final_laws_count": len(reranked_laws),
            "rag_results": rag_results,
            "google_results": google_results,
            "final_selected_laws": reranked_laws,
        }
        log_file = log_dir / "enrichment_log.json"
        log_file.write_text(json.dumps(log_data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Enrichment log written: %s", str(log_file))
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to write enrichment log", exc_info=True)
