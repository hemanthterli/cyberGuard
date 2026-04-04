import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.schemas.requests import CyberLawsInput
from app.schemas.responses import ComplaintLaw, ComplaintOutput
from app.services import gemini_error_handler, language_service, location_service
from app.services.errors import ServiceError

logger = logging.getLogger(__name__)

_MIN_REQUIRED_LAWS = 3
_STAGE_COUNTRY = "country_rag"
_STAGE_INTERNATIONAL = "international_rag"
_STAGE_SEARCH = "gemini_search"
_MODEL_BUSY_RETRY_ATTEMPTS = 5
_MODEL_BUSY_RETRY_SLEEP_SECONDS = 5

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
                        "source": {"type": "string"},
                    },
                    "required": ["law", "description", "source"],
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

_REWRITE_QUERY_FUNCTION = {
    "name": "rewrite_query",
    "description": "Rewrite the query to improve legal retrieval coverage while preserving user intent",
    "parameters": {
        "type": "object",
        "properties": {
            "rewritten_query": {"type": "string"},
            "reason": {"type": "string"},
        },
        "required": ["rewritten_query", "reason"],
    },
}

_VALIDATE_COVERAGE_FUNCTION = {
    "name": "validate_law_coverage",
    "description": "Validate relevance and sufficiency of collected cyber laws",
    "parameters": {
        "type": "object",
        "properties": {
            "is_sufficient": {"type": "boolean"},
            "reason": {"type": "string"},
            "law_count": {"type": "integer"},
            "relevant_laws": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": ["is_sufficient", "reason", "law_count"],
    },
}

_ROUTING_FUNCTION = {
    "name": "decide_routing",
    "description": "Decide next retrieval step for agentic cyber law workflow",
    "parameters": {
        "type": "object",
        "properties": {
            "route": {
                "type": "string",
                "enum": ["proceed", "international_rag", "gemini_search"],
            },
            "reason": {"type": "string"},
        },
        "required": ["route", "reason"],
    },
}


@dataclass(frozen=True)
class LawCandidate:
    law: str
    description: str
    source: str
    stage: str
    score: float | None = None


def _trace(event: str, **fields: Any) -> None:
    payload = {
        "component": "cyber_law_service",
        "event": event,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }
    payload.update(fields)
    line = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    print(line)


def _is_model_busy_exception(exc: Exception) -> bool:
    if isinstance(exc, ServiceError):
        return exc.code == "model_busy"
    try:
        gemini_error_handler.raise_if_model_busy(exc)
    except ServiceError as busy_error:
        return busy_error.code == "model_busy"
    return False


def _run_with_model_busy_retry(stage: str, step: str, operation):
    last_exception: Exception | None = None
    for attempt in range(1, _MODEL_BUSY_RETRY_ATTEMPTS + 1):
        _trace(
            "step_attempt",
            stage=stage,
            step=step,
            attempt=attempt,
            max_attempts=_MODEL_BUSY_RETRY_ATTEMPTS,
        )
        try:
            result = operation()
            _trace("step_success", stage=stage, step=step, attempt=attempt)
            return result
        except Exception as exc:  # noqa: BLE001
            last_exception = exc
            if not _is_model_busy_exception(exc):
                _trace(
                    "step_failed_non_busy",
                    stage=stage,
                    step=step,
                    attempt=attempt,
                    error=str(exc),
                )
                raise
            if attempt < _MODEL_BUSY_RETRY_ATTEMPTS:
                _trace(
                    "step_retry_busy",
                    stage=stage,
                    step=step,
                    attempt=attempt,
                    sleep_seconds=_MODEL_BUSY_RETRY_SLEEP_SECONDS,
                    error=str(exc),
                )
                time.sleep(_MODEL_BUSY_RETRY_SLEEP_SECONDS)
                continue
            _trace(
                "step_failed_busy_exhausted",
                stage=stage,
                step=step,
                attempt=attempt,
                error=str(exc),
            )
            gemini_error_handler.raise_if_model_busy(exc)
            raise

    if last_exception is not None:
        raise last_exception
    raise ServiceError("Unknown retry failure", code="model_failed", status_code=502)


def analyze_cyber_laws(payload: CyberLawsInput) -> ComplaintOutput:
    _trace("pipeline_start", location=payload.location, language=payload.language)
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

    query = str(core_decision.get("core_cybercrime", "")).strip() or content[:240]
    retrieved_laws_context = [
        law.strip()
        for law in payload.retrieved_laws
        if isinstance(law, str) and law.strip()
    ]

    client, types_mod = _build_gemini_client()

    state = {
        "collected_laws": [],
        "sources": [],
        "coverage_count": 0,
        "stage_history": [],
    }

    _trace("stage_start", stage=_STAGE_COUNTRY, query=query, jurisdiction=jurisdiction)
    country_candidates = _retrieve_law_candidates(query, jurisdiction, _STAGE_COUNTRY)
    _collect_candidates(state, country_candidates, _STAGE_COUNTRY, query)

    validation = _validate_law_coverage(
        client,
        types_mod,
        query,
        state,
        _STAGE_COUNTRY,
        content,
        core_decision,
        retrieved_laws_context,
    )
    next_route = _decide_route(
        client,
        types_mod,
        validation,
        _STAGE_COUNTRY,
        ["proceed", "international_rag"],
    )
    _trace("routing_decision", stage=_STAGE_COUNTRY, route=next_route, validation=validation)

    if next_route == "international_rag":
        _trace("stage_start", stage=_STAGE_INTERNATIONAL, query=query, jurisdiction=jurisdiction)
        rewritten_query = _rewrite_query(
            client,
            types_mod,
            original_query=query,
            stage=_STAGE_INTERNATIONAL,
            reason=validation.get("reason", ""),
            state=state,
            core_decision=core_decision,
            content=content,
        )
        international_candidates = _retrieve_law_candidates(
            rewritten_query,
            "international",
            _STAGE_INTERNATIONAL,
        )
        _collect_candidates(state, international_candidates, _STAGE_INTERNATIONAL, rewritten_query)

        validation = _validate_law_coverage(
            client,
            types_mod,
            rewritten_query,
            state,
            _STAGE_INTERNATIONAL,
            content,
            core_decision,
            retrieved_laws_context,
        )
        next_route = _decide_route(
            client,
            types_mod,
            validation,
            _STAGE_INTERNATIONAL,
            ["proceed", "gemini_search"],
        )
        _trace("routing_decision", stage=_STAGE_INTERNATIONAL, route=next_route, validation=validation)

        if next_route == "gemini_search":
            search_query = _rewrite_query(
                client,
                types_mod,
                original_query=rewritten_query,
                stage=_STAGE_SEARCH,
                reason=validation.get("reason", ""),
                state=state,
                core_decision=core_decision,
                content=content,
            )
            _trace("stage_start", stage=_STAGE_SEARCH, query=search_query, jurisdiction=jurisdiction)
            search_candidates = _search_laws_with_google(
                client,
                types_mod,
                search_query,
                jurisdiction,
            )
            _collect_candidates(state, search_candidates, _STAGE_SEARCH, search_query)

            validation = _validate_law_coverage(
                client,
                types_mod,
                search_query,
                state,
                _STAGE_SEARCH,
                content,
                core_decision,
                retrieved_laws_context,
            )

    ranked_candidates = _rank_candidates(state["collected_laws"])
    _trace(
        "aggregation_ready",
        total_candidates=len(ranked_candidates),
        unique_sources=len(state["sources"]),
        coverage_count=state["coverage_count"],
    )
    synthesized = _generate_final_response(
        client,
        types_mod,
        content,
        core_decision,
        ranked_candidates,
        retrieved_laws_context,
        state["stage_history"],
    )
    finalized = _enforce_membership_and_sources(synthesized, ranked_candidates)
    translated = _translate_output(finalized, output_language)

    insufficient = len(translated.applicable_laws) < _MIN_REQUIRED_LAWS or not bool(validation.get("is_sufficient"))
    insufficient_reason = str(validation.get("reason", "")).strip()
    _trace(
        "pipeline_end",
        final_law_count=len(translated.applicable_laws),
        insufficient=insufficient,
        insufficient_reason=insufficient_reason,
    )
    return _attach_jurisdiction_notice(
        translated,
        jurisdiction,
        output_language,
        insufficient=insufficient,
        insufficient_reason=insufficient_reason,
    )


def retrieve_laws(core_cybercrime: str, location: str) -> list[str]:
    query = core_cybercrime.strip()
    if not query:
        raise ServiceError("Empty core_cybercrime", code="invalid_input", status_code=400)

    normalized_location = location_service.normalize_location(location)
    candidates = _retrieve_law_candidates(query, normalized_location, _STAGE_COUNTRY)
    return [
        f"Title: {candidate.law}\nURL: {candidate.source}\n{candidate.description}"
        for candidate in candidates
    ]


def _build_gemini_client():
    _trace("gemini_client_build_start")
    try:
        from google import genai
        from google.genai import types
    except Exception as exc:  # noqa: BLE001
        logger.error("google-genai not installed", exc_info=True)
        raise ServiceError("Gemini client not available", code="dependency_missing", status_code=500) from exc

    if not settings.gemini_api_key:
        raise ServiceError("GEMINI_API_KEY not configured", code="config_error", status_code=500)

    _trace("gemini_client_build_done")
    return genai.Client(api_key=settings.gemini_api_key), types


def _collect_candidates(state: dict[str, Any], candidates: list[LawCandidate], stage: str, query: str) -> None:
    added = 0
    for candidate in candidates:
        if _candidate_exists(state["collected_laws"], candidate):
            continue
        state["collected_laws"].append(candidate)
        added += 1
        if candidate.source and candidate.source not in state["sources"]:
            state["sources"].append(candidate.source)

    state["coverage_count"] = len(state["collected_laws"])
    state["stage_history"].append(
        {
            "stage": stage,
            "query": query,
            "added": added,
            "total": len(state["collected_laws"]),
        }
    )
    _trace(
        "stage_collected",
        stage=stage,
        query=query,
        added=added,
        total=len(state["collected_laws"]),
    )


def _candidate_exists(existing: list[LawCandidate], candidate: LawCandidate) -> bool:
    candidate_key = _candidate_key(candidate.law, candidate.source)
    for item in existing:
        if _candidate_key(item.law, item.source) == candidate_key:
            return True
    return False


def _candidate_key(law: str, source: str) -> str:
    return f"{_normalize_text(law)}::{source.strip().lower()}"


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value.lower())).strip()


def _preview_text(value: Any, *, max_len: int = 320) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= max_len:
        return compact
    return f"{compact[:max_len]}..."


def _rank_candidates(candidates: list[LawCandidate]) -> list[LawCandidate]:
    stage_priority = {
        _STAGE_COUNTRY: 0,
        _STAGE_INTERNATIONAL: 1,
        _STAGE_SEARCH: 2,
    }
    return sorted(
        candidates,
        key=lambda item: (
            stage_priority.get(item.stage, 99),
            item.score if item.score is not None else 9999.0,
            item.law.lower(),
        ),
    )


def _validate_law_coverage(
    client,
    types_mod,
    query: str,
    state: dict[str, Any],
    stage: str,
    content: str,
    core_decision: dict[str, Any],
    retrieved_laws_context: list[str],
) -> dict[str, Any]:
    _trace("validate_start", stage=stage, query=query, candidate_count=len(state["collected_laws"]))
    payload = {
        "query": query,
        "stage": stage,
        "minimum_required": _MIN_REQUIRED_LAWS,
        "content": content,
        "core_decision": core_decision,
        "retrieved_laws_context": retrieved_laws_context,
        "collected_laws": [
            {
                "law": item.law,
                "description": item.description,
                "source": item.source,
                "stage": item.stage,
            }
            for item in state["collected_laws"]
        ],
    }

    prompt = (
        "Evaluate if collected laws are relevant and sufficient for the query. "
        f"Sufficiency requires at least {_MIN_REQUIRED_LAWS} relevant laws. "
        "Count only relevant laws. Return function call only.\n\n"
        f"INPUT:\n{json.dumps(payload, ensure_ascii=False)}"
    )

    try:
        args = _call_function_tool(
            client,
            types_mod,
            _VALIDATE_COVERAGE_FUNCTION,
            prompt,
            max_output_tokens=768,
            trace_stage=stage,
            trace_query=query,
            trace_step="validate_law_coverage",
        )
    except ServiceError as exc:
        if exc.code != "model_failed":
            raise
        fallback_count = len(state["collected_laws"])
        fallback_result = {
            "is_sufficient": False,
            "reason": "Fallback validation used because model returned non-structured output; forcing next fallback stage.",
            "law_count": fallback_count,
        }
        _trace("validate_fallback", stage=stage, fallback=fallback_result)
        return fallback_result

    is_sufficient = bool(args.get("is_sufficient", False))
    reason = str(args.get("reason", "")).strip()
    law_count = _to_int(args.get("law_count"), default=len(state["collected_laws"]))

    result = {
        "is_sufficient": is_sufficient,
        "reason": reason,
        "law_count": law_count,
    }
    _trace("validate_result", stage=stage, result=result)
    return result


def _decide_route(
    client,
    types_mod,
    validation: dict[str, Any],
    stage: str,
    allowed_routes: list[str],
) -> str:
    _trace("route_start", stage=stage, allowed_routes=allowed_routes, validation=validation)
    prompt = (
        "Choose the next route for this agentic retrieval workflow. "
        f"Only return one of these routes: {allowed_routes}. "
        "Return function call only.\n\n"
        f"STAGE: {stage}\n"
        f"VALIDATION: {json.dumps(validation, ensure_ascii=False)}"
    )

    try:
        args = _call_function_tool(
            client,
            types_mod,
            _ROUTING_FUNCTION,
            prompt,
            max_output_tokens=256,
            trace_stage=stage,
            trace_query=str(validation),
            trace_step="decide_routing",
        )
        route = str(args.get("route", "")).strip().lower()
    except ServiceError as exc:
        if exc.code != "model_failed":
            raise
        route = ""
        _trace("route_model_fallback_triggered", stage=stage, error=str(exc))

    if not bool(validation.get("is_sufficient")) and route == "proceed":
        _trace("route_override_due_insufficient_validation", stage=stage, previous_route=route)
        route = ""

    if route in allowed_routes:
        _trace("route_selected", stage=stage, route=route)
        return route

    if bool(validation.get("is_sufficient")) and "proceed" in allowed_routes:
        _trace("route_fallback_selected", stage=stage, route="proceed")
        return "proceed"
    if "international_rag" in allowed_routes:
        _trace("route_fallback_selected", stage=stage, route="international_rag")
        return "international_rag"
    if "gemini_search" in allowed_routes:
        _trace("route_fallback_selected", stage=stage, route="gemini_search")
        return "gemini_search"
    _trace("route_fallback_selected", stage=stage, route=allowed_routes[0])
    return allowed_routes[0]


def _rewrite_query(
    client,
    types_mod,
    *,
    original_query: str,
    stage: str,
    reason: str,
    state: dict[str, Any],
    core_decision: dict[str, Any],
    content: str,
) -> str:
    _trace("rewrite_start", stage=stage, original_query=original_query)
    payload = {
        "original_query": original_query,
        "target_stage": stage,
        "insufficiency_reason": reason,
        "already_collected_laws": [item.law for item in state["collected_laws"]],
        "core_decision": core_decision,
        "content": content,
    }

    prompt = (
        "Rewrite the query to improve cyber law retrieval coverage without changing user intent. "
        "Avoid duplicates and include missing legal context. Return function call only.\n\n"
        f"INPUT:\n{json.dumps(payload, ensure_ascii=False)}"
    )

    try:
        args = _call_function_tool(
            client,
            types_mod,
            _REWRITE_QUERY_FUNCTION,
            prompt,
            max_output_tokens=384,
            trace_stage=stage,
            trace_query=original_query,
            trace_step="rewrite_query",
        )
        rewritten = str(args.get("rewritten_query", "")).strip()
        final_query = rewritten or original_query
    except ServiceError as exc:
        if exc.code != "model_failed":
            raise
        final_query = _fallback_query_for_stage(
            original_query=original_query,
            stage=stage,
            core_decision=core_decision,
            content=content,
        )
        _trace("rewrite_fallback", stage=stage, query=final_query)
    _trace("rewrite_done", stage=stage, rewritten_query=final_query)
    return final_query


def _fallback_query_for_stage(
    *,
    original_query: str,
    stage: str,
    core_decision: dict[str, Any],
    content: str,
) -> str:
    if stage != _STAGE_SEARCH:
        return original_query
    core = str(core_decision.get("core_cybercrime", "")).strip()
    desc = str(core_decision.get("description", "")).strip()
    base = core or desc or content[:200]
    compact = re.sub(r"\s+", " ", base).strip()
    compact = compact[:220]
    return f"cyber harassment defamation applicable laws legal sections {compact}".strip()


def _search_laws_with_google(client, types_mod, query: str, jurisdiction: str) -> list[LawCandidate]:
    _trace("search_start", stage=_STAGE_SEARCH, query=query, jurisdiction=jurisdiction)
    prompt = (
        "Find cyber laws and legal sections relevant to this query. "
        "Prefer official legal or government sources and recent authoritative references.\n"
        f"Jurisdiction context: {location_service.get_location_label(jurisdiction)}\n"
        f"Query: {query}"
    )

    config = types_mod.GenerateContentConfig(
        tools=[{"google_search": {}}],
        temperature=0.1,
        top_p=0.9,
        max_output_tokens=1024,
    )

    try:
        response = _run_with_model_busy_retry(
            stage=_STAGE_SEARCH,
            step="gemini_google_search",
            operation=lambda: client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config=config,
            ),
        )
    except Exception as exc:  # noqa: BLE001
        gemini_error_handler.raise_if_model_busy(exc)
        logger.error("Gemini search retrieval failed", exc_info=True)
        raise ServiceError("Failed to search cyber laws", code="model_failed", status_code=502) from exc

    text_output = _extract_text_from_response(response)
    _trace("search_text_output", stage=_STAGE_SEARCH, text_preview=_preview_text(text_output, max_len=700))
    try:
        candidate = response.candidates[0]
    except Exception:
        _trace("search_response_missing_candidates", stage=_STAGE_SEARCH)
        return []

    grounding = getattr(candidate, "grounding_metadata", None)
    search_queries = list(getattr(grounding, "web_search_queries", []) or []) if grounding else []
    grounding_chunks = list(getattr(grounding, "grounding_chunks", []) or []) if grounding else []
    _trace(
        "search_response_metadata",
        stage=_STAGE_SEARCH,
        has_grounding=bool(grounding),
        web_search_queries_count=len(search_queries),
        grounding_chunks_count=len(grounding_chunks),
    )
    if not grounding:
        fallback_candidates = _extract_law_candidates_from_search_text(text_output)
        _trace("search_no_grounding", stage=_STAGE_SEARCH, fallback_candidates=len(fallback_candidates))
        _trace(
            "search_candidates_output",
            stage=_STAGE_SEARCH,
            candidates_preview=_preview_text([item.__dict__ for item in fallback_candidates], max_len=700),
        )
        return fallback_candidates

    candidates: list[LawCandidate] = []
    for idx, chunk in enumerate(grounding_chunks):
        web = getattr(chunk, "web", None)
        if not web:
            continue
        title = str(getattr(web, "title", "")).strip() or "Cyber law reference"
        source = str(getattr(web, "uri", "")).strip()
        if not source:
            continue

        description = text_output[:280].strip() if text_output else "Discovered from Google Search grounding results."
        candidates.append(
            LawCandidate(
                law=title,
                description=description,
                source=source,
                stage=_STAGE_SEARCH,
                score=float(idx),
            )
        )

    unique_candidates: list[LawCandidate] = []
    for candidate_item in candidates:
        if not _candidate_exists(unique_candidates, candidate_item):
            unique_candidates.append(candidate_item)
    if not unique_candidates:
        fallback_candidates = _extract_law_candidates_from_search_text(text_output)
        _trace("search_empty_grounding_candidates_fallback", stage=_STAGE_SEARCH, fallback_candidates=len(fallback_candidates))
        _trace(
            "search_candidates_output",
            stage=_STAGE_SEARCH,
            candidates_preview=_preview_text([item.__dict__ for item in fallback_candidates], max_len=700),
        )
        return fallback_candidates
    _trace("search_done", stage=_STAGE_SEARCH, found=len(unique_candidates))
    _trace(
        "search_candidates_output",
        stage=_STAGE_SEARCH,
        candidates_preview=_preview_text([item.__dict__ for item in unique_candidates], max_len=700),
    )
    return unique_candidates


def _extract_law_candidates_from_search_text(text_output: str) -> list[LawCandidate]:
    if not text_output.strip():
        return []

    candidates: list[LawCandidate] = []

    markdown_links = re.findall(r"\[([^\]]+)\]\((https?://[^)]+)\)", text_output)
    for idx, (title, url) in enumerate(markdown_links):
        clean_title = title.strip()
        clean_url = url.strip().rstrip(").,")
        if not clean_url:
            continue
        candidates.append(
            LawCandidate(
                law=clean_title or "Cyber law reference",
                description="Extracted from Gemini search response text.",
                source=clean_url,
                stage=_STAGE_SEARCH,
                score=float(idx),
            )
        )

    raw_urls = re.findall(r"https?://[^\s)\],]+", text_output)
    existing_urls = {item.source for item in candidates}
    for raw in raw_urls:
        clean_url = raw.strip().rstrip(").,")
        if not clean_url or clean_url in existing_urls:
            continue
        label = clean_url.split("/")[-1].replace("-", " ").replace("_", " ").strip() or "Cyber law reference"
        candidates.append(
            LawCandidate(
                law=label[:120],
                description="Extracted from Gemini search response text.",
                source=clean_url,
                stage=_STAGE_SEARCH,
                score=float(len(candidates)),
            )
        )
        existing_urls.add(clean_url)

    unique_candidates: list[LawCandidate] = []
    for item in candidates:
        if not _candidate_exists(unique_candidates, item):
            unique_candidates.append(item)
    return unique_candidates[: settings.cyberlaw_top_k]


def _generate_final_response(
    client,
    types_mod,
    content: str,
    core_decision: dict[str, Any],
    law_candidates: list[LawCandidate],
    retrieved_laws_context: list[str],
    stage_history: list[dict[str, Any]],
) -> ComplaintOutput:
    payload = {
        "content": content,
        "core_decision": core_decision,
        "candidate_laws": [
            {
                "law": item.law,
                "description": item.description,
                "source": item.source,
                "stage": item.stage,
            }
            for item in law_candidates
        ],
        "retrieved_laws_context": retrieved_laws_context,
        "stage_history": stage_history,
        "minimum_required": _MIN_REQUIRED_LAWS,
    }

    prompt = (
        "You are a cyber legal assistant. Use only laws present in candidate_laws. "
        "Do not invent law names or sources. Keep output concise and practical. "
        "Return output via function call only.\n\n"
        f"INPUT:\n{json.dumps(payload, ensure_ascii=False)}"
    )

    try:
        args = _call_function_tool(
            client,
            types_mod,
            _COMPLAINT_FUNCTION,
            prompt,
            max_output_tokens=2048,
            trace_stage="final_synthesis",
            trace_query=str(core_decision.get("core_cybercrime", "")),
            trace_step="generate_cyber_law_complaint",
        )
        return _parse_output(args)
    except ServiceError as exc:
        if exc.code != "model_failed":
            raise
        _trace("final_synthesis_fallback", error=str(exc), candidate_count=len(law_candidates))
        fallback_laws = [
            ComplaintLaw(law=item.law, description=item.description, source=item.source)
            for item in law_candidates[: max(_MIN_REQUIRED_LAWS, 1)]
        ]
        return ComplaintOutput(
            summary="Structured model output was unavailable; returning best available applicable laws from retrieval stages.",
            detected_phrases=[str(core_decision.get("phrases", "")).strip()] if str(core_decision.get("phrases", "")).strip() else [],
            applicable_laws=fallback_laws,
            recommended_actions=[
                "Preserve evidence (URLs, screenshots, timestamps).",
                "Report abusive content on the hosting platform.",
                "Consult local law enforcement or legal counsel for next legal steps.",
            ],
        )


def _enforce_membership_and_sources(result: ComplaintOutput, candidates: list[LawCandidate]) -> ComplaintOutput:
    if not candidates:
        return result

    lookup: dict[str, list[LawCandidate]] = {}
    for item in candidates:
        lookup.setdefault(_normalize_text(item.law), []).append(item)

    ensured_laws: list[ComplaintLaw] = []
    for law_item in result.applicable_laws:
        key = _normalize_text(law_item.law)
        matched = lookup.get(key)
        if not matched:
            matched = [candidate for candidate in candidates if key and key in _normalize_text(candidate.law)]
        if not matched:
            continue

        selected = matched[0]
        source = law_item.source.strip() if law_item.source.strip() else selected.source
        if source not in {candidate.source for candidate in matched}:
            source = selected.source

        description = law_item.description.strip() or selected.description
        ensured_candidate = ComplaintLaw(
            law=selected.law,
            description=description,
            source=source,
        )
        if any(_candidate_key(existing.law, existing.source) == _candidate_key(ensured_candidate.law, ensured_candidate.source) for existing in ensured_laws):
            continue
        ensured_laws.append(ensured_candidate)

    if not ensured_laws:
        for candidate in candidates[:_MIN_REQUIRED_LAWS]:
            ensured_laws.append(
                ComplaintLaw(
                    law=candidate.law,
                    description=candidate.description,
                    source=candidate.source,
                )
            )
    elif len(ensured_laws) < _MIN_REQUIRED_LAWS:
        existing_keys = {_candidate_key(item.law, item.source) for item in ensured_laws}
        for candidate in candidates:
            key = _candidate_key(candidate.law, candidate.source)
            if key in existing_keys:
                continue
            ensured_laws.append(
                ComplaintLaw(
                    law=candidate.law,
                    description=candidate.description,
                    source=candidate.source,
                )
            )
            existing_keys.add(key)
            if len(ensured_laws) >= _MIN_REQUIRED_LAWS:
                break

    return ComplaintOutput(
        summary=result.summary,
        detected_phrases=result.detected_phrases,
        applicable_laws=ensured_laws,
        recommended_actions=result.recommended_actions,
    )


def _retrieve_law_candidates(query: str, location: str, stage: str) -> list[LawCandidate]:
    _trace("rag_retrieval_start", stage=stage, query=query, location=location)
    normalized_location = location if location == "international" else location_service.normalize_location(location)
    db = _get_db(normalized_location)

    try:
        results = _run_with_model_busy_retry(
            stage=stage,
            step="rag_similarity_search",
            operation=lambda: db.similarity_search_with_score(query, k=settings.cyberlaw_top_k),
        )
    except Exception as exc:  # noqa: BLE001
        gemini_error_handler.raise_if_model_busy(exc)
        raise ServiceError("Failed to retrieve cyber laws", code="model_failed", status_code=502) from exc

    candidates: list[LawCandidate] = []
    for doc, score in results:
        law_name = _extract_law_name(doc)
        source = _extract_source(doc)
        description = _extract_description(doc)
        if not law_name or not source:
            continue
        candidates.append(
            LawCandidate(
                law=law_name,
                description=description,
                source=source,
                stage=stage,
                score=float(score),
            )
        )
    _trace("rag_retrieval_done", stage=stage, location=normalized_location, found=len(candidates))
    return candidates


def _extract_law_name(doc: Any) -> str:
    metadata = getattr(doc, "metadata", {}) or {}
    title = str(metadata.get("title", "")).strip()
    if title:
        return title

    text = str(getattr(doc, "page_content", "")).strip()
    for line in text.splitlines():
        if line.lower().startswith("title:"):
            return line.split(":", 1)[-1].strip()
    return text[:120].strip()


def _extract_source(doc: Any) -> str:
    metadata = getattr(doc, "metadata", {}) or {}
    source = str(metadata.get("url", "")).strip() or str(metadata.get("source", "")).strip()
    return source


def _extract_description(doc: Any) -> str:
    text = str(getattr(doc, "page_content", "")).strip()
    if len(text) > settings.cyberlaw_snippet_chars:
        return text[: settings.cyberlaw_snippet_chars].rstrip() + "..."
    return text


def _get_db(location: str):
    global _embeddings
    if location in _db_cache:
        _trace("db_cache_hit", location=location)
        return _db_cache[location]
    _trace("db_load_start", location=location)

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
    _trace("db_load_done", location=location, index_path=str(index_path))
    return db


def _get_index_path_for_location(location: str) -> Path:
    location_paths = {
        "india": settings.cyberlaw_india_faiss_path,
        "uk": settings.cyberlaw_uk_faiss_path,
        "usa": settings.cyberlaw_usa_faiss_path,
        "international": settings.cyberlaw_international_faiss_path,
    }
    selected = location_paths.get(location)
    if not selected:
        raise ServiceError("Unsupported location", code="invalid_input", status_code=400)
    return Path(selected)


def _call_function_tool(
    client,
    types_mod,
    function_declaration: dict[str, Any],
    prompt: str,
    *,
    max_output_tokens: int,
    trace_stage: str = "function_tool",
    trace_query: str = "",
    trace_step: str = "",
) -> dict[str, Any]:
    tools = types_mod.Tool(function_declarations=[function_declaration])
    config = types_mod.GenerateContentConfig(
        tools=[tools],
        tool_config=types_mod.ToolConfig(
            function_calling_config=types_mod.FunctionCallingConfig(mode="ANY")
        ),
        temperature=0.1,
        top_p=0.9,
        max_output_tokens=max_output_tokens,
    )

    model_failed_error: Exception | None = None
    for structure_attempt in range(1, 3):
        effective_prompt = prompt
        if structure_attempt > 1:
            effective_prompt = (
                f"{prompt}\n\n"
                "CRITICAL: Return output as a function call only. "
                "Do not answer in plain text."
            )

        _trace(
            "function_call_generation_start",
            function_name=function_declaration.get("name"),
            structure_attempt=structure_attempt,
            stage=trace_stage,
            step=trace_step or function_declaration.get("name"),
            query_preview=_preview_text(trace_query),
            prompt_preview=_preview_text(effective_prompt, max_len=500),
        )

        try:
            response = _run_with_model_busy_retry(
                stage="function_tool",
                step=f"generate_content:{function_declaration.get('name', 'unknown')}",
                operation=lambda: client.models.generate_content(
                    model=settings.gemini_complaint_model,
                    contents=effective_prompt,
                    config=config,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            gemini_error_handler.raise_if_model_busy(exc)
            logger.error("Gemini function-call request failed", exc_info=True)
            raise ServiceError("Failed to generate structured output", code="model_failed", status_code=502) from exc

        call = _extract_function_call(response)
        if call:
            args = getattr(call, "args", None)
            if isinstance(args, dict):
                _trace(
                    "function_call_generation_done",
                    function_name=function_declaration.get("name"),
                    structure_attempt=structure_attempt,
                    response_mode="function_call",
                    output_preview=_preview_text(args, max_len=700),
                )
                return args
            try:
                parsed = dict(args)  # type: ignore[arg-type]
                _trace(
                    "function_call_generation_done",
                    function_name=function_declaration.get("name"),
                    structure_attempt=structure_attempt,
                    response_mode="function_call_dict_cast",
                    output_preview=_preview_text(parsed, max_len=700),
                )
                return parsed
            except Exception as exc:  # noqa: BLE001
                logger.error("Invalid function args", exc_info=True)
                model_failed_error = exc
                continue

        text_fallback = _extract_json_object_from_response_text(response)
        if isinstance(text_fallback, dict):
            _trace(
                "function_call_text_json_fallback",
                function_name=function_declaration.get("name"),
                structure_attempt=structure_attempt,
                output_preview=_preview_text(text_fallback, max_len=700),
            )
            return text_fallback

        raw_text = _extract_text_from_response(response)
        _trace(
            "function_call_missing_structured_output",
            function_name=function_declaration.get("name"),
            structure_attempt=structure_attempt,
            response_text_preview=_preview_text(raw_text, max_len=700),
        )
        model_failed_error = ServiceError(
            "Model did not return structured output",
            code="model_failed",
            status_code=502,
        )

    if isinstance(model_failed_error, ServiceError):
        raise model_failed_error
    if model_failed_error is not None:
        raise ServiceError("Invalid model output", code="model_failed", status_code=502) from model_failed_error
    raise ServiceError("Model did not return structured output", code="model_failed", status_code=502)


def _extract_function_call(response: Any):
    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        parts = getattr(getattr(candidate, "content", None), "parts", None) or []
        for part in parts:
            function_call = getattr(part, "function_call", None)
            if function_call:
                return function_call
    return None


def _extract_text_from_response(response: Any) -> str:
    text_parts: list[str] = []
    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        parts = getattr(getattr(candidate, "content", None), "parts", None) or []
        for part in parts:
            text = getattr(part, "text", None)
            if text:
                text_parts.append(str(text).strip())
    return "\n".join([item for item in text_parts if item])


def _extract_json_object_from_response_text(response: Any) -> dict[str, Any] | None:
    text = _extract_text_from_response(response).strip()
    if not text:
        return None

    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    for candidate in (cleaned, _slice_first_json_object(cleaned)):
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _slice_first_json_object(text: str) -> str | None:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start : end + 1]


def _to_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


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
                source = str(item.get("source", "")).strip()
                if law and description and source:
                    applicable_laws.append(ComplaintLaw(law=law, description=description, source=source))

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
        translated_laws.append(
            ComplaintLaw(
                law=item.law,
                description=translated_description,
                source=item.source,
            )
        )

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
    )


def _attach_jurisdiction_notice(
    result: ComplaintOutput,
    location: str,
    language: str,
    *,
    insufficient: bool,
    insufficient_reason: str,
) -> ComplaintOutput:
    country_label = location_service.get_location_label(location)
    notice = f"The following cyber laws are based on {country_label}."
    localized_notice = language_service.translate_text(
        notice,
        language,
        context="jurisdiction notice",
    )

    suffix = ""
    if insufficient:
        warning_text = (
            f"Warning: fewer than {_MIN_REQUIRED_LAWS} relevant laws were found after country, "
            "international, and search validation."
        )
        if insufficient_reason:
            warning_text = f"{warning_text} Reason: {insufficient_reason}"
        suffix = language_service.translate_text(
            warning_text,
            language,
            context="law insufficiency warning",
        )

    summary_parts = [localized_notice]
    if suffix:
        summary_parts.append(suffix)
    if result.summary:
        summary_parts.append(result.summary)

    return ComplaintOutput(
        summary="\n\n".join(summary_parts),
        detected_phrases=result.detected_phrases,
        applicable_laws=result.applicable_laws,
        recommended_actions=result.recommended_actions,
    )
