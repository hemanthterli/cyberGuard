from app.services.errors import ServiceError

_LOCATION_ALIASES = {
    "india": "india",
    "in": "india",
    "ind": "india",
    "united kingdom": "uk",
    "uk": "uk",
    "gb": "uk",
    "great britain": "uk",
    "united states": "usa",
    "united states of america": "usa",
    "usa": "usa",
    "us": "usa",
    "america": "usa",
}

_LOCATION_LABELS = {
    "india": "India",
    "uk": "United Kingdom",
    "usa": "United States",
}


def normalize_location(location: str | None) -> str:
    if location is None:
        return "india"
    key = str(location).strip().lower()
    if not key:
        return "india"
    normalized = _LOCATION_ALIASES.get(key)
    if not normalized:
        raise ServiceError("Unsupported location", code="invalid_input", status_code=400)
    return normalized


def get_location_label(location: str) -> str:
    normalized = normalize_location(location)
    return _LOCATION_LABELS[normalized]
