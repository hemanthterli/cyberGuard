import logging
import json
import re
from typing import Any

from app.core.config import settings
from app.schemas.requests import ComplaintDraftInput
from app.services import gemini_error_handler, language_service, location_service
from app.services.errors import ServiceError

logger = logging.getLogger(__name__)


def generate_complaint_letter(payload: ComplaintDraftInput) -> str:
    output_language = language_service.normalize_language(payload.language)
    jurisdiction = location_service.normalize_location(payload.location)
    jurisdiction_label = location_service.get_location_label(jurisdiction)
    summary = payload.summary.strip()
    if not summary:
        raise ServiceError("Empty summary", code="invalid_input", status_code=400)

    detected_phrases = [p.strip() for p in payload.detected_phrases if p and str(p).strip()]
    applicable_laws = payload.applicable_laws or []
    recommended_actions = [a.strip() for a in payload.recommended_actions if a and str(a).strip()]

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
        summary=summary,
        detected_phrases=detected_phrases,
        applicable_laws=applicable_laws,
        recommended_actions=recommended_actions,
        jurisdiction=jurisdiction_label,
    )

    config = types.GenerateContentConfig(
        temperature=0.2,
        top_p=0.9,
        max_output_tokens=2048,
    )

    try:
        response = gemini_error_handler.call_with_retry(
            client.models.generate_content,
            model=settings.gemini_complaint_model,
            contents=prompt,
            config=config,
            validate=gemini_error_handler.validate_has_text,
        )
    except ServiceError:
        raise
    except Exception as exc:  # noqa: BLE001
        gemini_error_handler.raise_if_model_busy(exc)
        logger.error("Gemini complaint drafting failed after retries", exc_info=True)
        raise ServiceError("Failed to draft complaint", code="model_failed", status_code=502) from exc

    text = _extract_text(response)
    if not text:
        raise ServiceError("Model returned empty complaint", code="model_failed", status_code=502)

    translated = language_service.translate_text(
        text,
        output_language,
        context="final complaint letter",
        preserve_bracketed=False,
    )
    return _localize_complaint_structure(translated, output_language)


def _build_prompt(
    summary: str,
    detected_phrases: list[str],
    applicable_laws: list[dict[str, Any]],
    recommended_actions: list[str],
    jurisdiction: str,
) -> str:
    return (
        "You are a Cyber Crime Complaint Drafter.\n"
        f"The legal jurisdiction for this complaint is: {jurisdiction}.\n"
        "Output only a formal complaint letter.\n"
        "Do NOT return JSON. Do NOT add explanations.\n"
        "Follow the structure provided and keep placeholders as written.\n\n"
        "Inputs:\n"
        f"JURISDICTION: {jurisdiction}\n\n"
        f"SUMMARY: {summary}\n\n"
        f"DETECTED_PHRASES: {json.dumps(detected_phrases, ensure_ascii=False)}\n\n"
        f"APPLICABLE_LAWS: {json.dumps(applicable_laws, ensure_ascii=False)}\n\n"
        f"RECOMMENDED_ACTIONS: {json.dumps(recommended_actions, ensure_ascii=False)}\n\n"
        "Structure:\n"
        "[Your Name]\n"
        "[Your Phone Number]\n"
        "[Your Email Address]\n"
        "[Your Address]\n\n"
        "[Date]\n\n"
        "To,\n"
        "[Recipient Name / Authority]\n"
        "[Organization Name]\n"
        "[Address]\n\n"
        "Subject: Cyber Crime Complaint\n\n"
        "Introduction:\n"
        "- State purpose of writing\n"
        "- Brief mention of incident\n\n"
        "Incident Description:\n"
        "- What happened\n"
        "- Nature of cybercrime\n"
        "- Date/time (if inferable or keep generic)\n\n"
        "Evidence / Indicators:\n"
        "- Mention detected phrases\n"
        "- Reference harmful content\n\n"
        "Applicable Laws:\n"
        "- Mention relevant cyber laws from input\n"
        "- Briefly connect them to the incident\n\n"
        "Impact:\n"
        "- Harm caused (reputation, mental distress, etc.)\n\n"
        "Request:\n"
        "- Ask for investigation and necessary action\n\n"
        "Sincerely,\n"
        "[Your Name]\n"
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


def _localize_complaint_structure(text: str, language: str) -> str:
    heading_map = {
        "hindi": {
            "To,": "प्रति,",
            "Subject: Cyber Crime Complaint": "विषय: साइबर अपराध शिकायत",
            "Introduction:": "परिचय:",
            "Incident Description:": "घटना विवरण:",
            "Evidence / Indicators:": "साक्ष्य / संकेतक:",
            "Applicable Laws:": "लागू कानून:",
            "Impact:": "प्रभाव:",
            "Request:": "अनुरोध:",
            "Sincerely,": "सादर,",
        },
        "telugu": {
            "To,": "కు,",
            "Subject: Cyber Crime Complaint": "విషయం: సైబర్ క్రైమ్ ఫిర్యాదు",
            "Introduction:": "పరిచయం:",
            "Incident Description:": "ఘటన వివరణ:",
            "Evidence / Indicators:": "సాక్ష్యాలు / సూచనలు:",
            "Applicable Laws:": "వర్తించే చట్టాలు:",
            "Impact:": "ప్రభావం:",
            "Request:": "అభ్యర్థన:",
            "Sincerely,": "భవదీయులు,",
        },
    }

    placeholder_map = {
        "hindi": {
            "[Your Name]": "[आपका नाम]",
            "[Your Phone Number]": "[आपका फ़ोन नंबर]",
            "[Your Email Address]": "[आपका ईमेल पता]",
            "[Your Address]": "[आपका पता]",
            "[Date]": "[तारीख]",
            "[Recipient Name / Authority]": "[प्राप्तकर्ता का नाम / प्राधिकरण]",
            "[Organization Name]": "[संगठन का नाम]",
            "[Address]": "[पता]",
        },
        "telugu": {
            "[Your Name]": "[మీ పేరు]",
            "[Your Phone Number]": "[మీ ఫోన్ నంబర్]",
            "[Your Email Address]": "[మీ ఇమెయిల్ చిరునామా]",
            "[Your Address]": "[మీ చిరునామా]",
            "[Date]": "[తేదీ]",
            "[Recipient Name / Authority]": "[గ్రహీత పేరు / అధికారి]",
            "[Organization Name]": "[సంస్థ పేరు]",
            "[Address]": "[చిరునామా]",
        },
    }

    localized = text

    for source, target in heading_map.get(language, {}).items():
        localized = re.sub(rf"(?im)^\s*{re.escape(source)}\s*$", target, localized)

    for source, target in placeholder_map.get(language, {}).items():
        localized = localized.replace(source, target)

    return localized
