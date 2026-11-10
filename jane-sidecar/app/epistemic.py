"""Keep ledger and boolean scores tied to words the user actually said."""

import re

from app.northstar import DEFAULT_LEDGER, clamp_aesthetic, clamp_energetic, clamp_utilized

LEDGER_LIST_KEYS = (
    "soil_and_water",
    "energy_systems",
    "livestock_and_crops",
    "waste_containment",
    "skills_and_equipment",
    "active_goals",
)

_MATERIAL_TRUE = re.compile(
    r"live indefinitely off|live off (the |our )?(property|land|homestead)|material(ly)? independent|feed ourselves indefinitely",
    re.I,
)
_MATERIAL_SURPLUS = re.compile(r"sell(ing)? (the |our )?surplus|surplus at a profit", re.I)
_CONTAINED_TRUE = re.compile(
    r"zero (harmful )?waste|leaks nothing|no harmful waste|nothing leaves the property|fully contained",
    re.I,
)
_INSURED_TRUE = re.compile(
    r"\b(?:we are|we're|property and (?:all )?(?:the )?homesteaders are|homestead is|property is)\s+perfectly insured\b",
    re.I,
)
_UTILIZED_FULL = re.compile(r"\bfully recorded on (?:our |the )?(?:cutting[- ]edge )?financial tools\b", re.I)
_UTILIZED_NONE = re.compile(r"\bnot recorded on (?:any )?financial tools\b", re.I)
_UTILIZED_PCT = re.compile(
    r"(?:financial tools|utilized)[^\d]{0,32}(\d{1,3}(?:\.\d+)?)|(\d{1,3}(?:\.\d+)?)\s*(?:%|percent).{0,32}financial tools",
    re.I,
)
_ENERGY_PROFIT = re.compile(
    r"sell(ing)? (surplus )?(power|energy|electricity).{0,40}profit|surplus energy.{0,40}profit|net profit on (power|energy)",
    re.I,
)
_HOURS = re.compile(r"(\d+(?:\.\d+)?)\s*hours?", re.I)
_AESTHETIC = re.compile(
    r"(?:beauty|aesthetic|beautiful)[^\d]{0,48}(\d{1,3}(?:\.\d+)?)|(\d{1,3}(?:\.\d+)?)\s*(?:out of|/)\s*100",
    re.I,
)
_ENERGETIC_PCT = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:%|percent)\s*(?:of )?(?:our |my )?(?:power|energy|electricity)",
    re.I,
)
_ZIP = re.compile(r"\b(\d{5})(?:-\d{4})?\b")
_PIN_LAT = re.compile(r"lat(?:itude)?\s*(?:is|:)?\s*(-?\d+(?:\.\d+)?)", re.I)
_PIN_LNG = re.compile(r"(?:lng|lon(?:gitude)?)\s*(?:is|:)?\s*(-?\d+(?:\.\d+)?)", re.I)
_STREET = re.compile(r"(?:street address|my address|address)\s*(?:is|:|-)?\s*([^\n]{4,180})", re.I)
_SPONSOR_FORM = re.compile(r"company\s*:", re.I)
_VOTE_UNITS = re.compile(r"(\d+(?:\.\d+)?)")
_PRICE = re.compile(r"\$\s*(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*(?:dollars|usd)", re.I)


def _mentioned(value: str, user_text: str) -> bool:
    return value.casefold() in user_text.casefold()


def gate_ledger_patch(existing: dict, patch: dict, user_text: str) -> dict:
    """Copy only ledger values whose text appears in the user message."""
    merged = {key: (list(value) if isinstance(value, list) else value) for key, value in {**DEFAULT_LEDGER, **(existing or {})}.items()}
    if not isinstance(patch, dict):
        return merged
    if "acreage" in patch and patch["acreage"] is not None and _mentioned(str(patch["acreage"]), user_text):
        merged["acreage"] = patch["acreage"]
    for key in LEDGER_LIST_KEYS:
        incoming = patch.get(key)
        if not isinstance(incoming, list):
            continue
        bucket = list(merged.get(key) or [])
        for item in incoming:
            text = str(item).strip()
            if text and _mentioned(text, user_text) and text not in bucket:
                bucket.append(text)
        merged[key] = bucket
    return merged


def affirmed_material(user_text: str) -> bool:
    return bool(_MATERIAL_TRUE.search(user_text or ""))


def affirmed_material_surplus(user_text: str) -> bool:
    return bool(_MATERIAL_SURPLUS.search(user_text or ""))


def affirmed_contained(user_text: str) -> bool:
    return bool(_CONTAINED_TRUE.search(user_text or ""))


def affirmed_energy_profit(user_text: str) -> bool:
    return bool(_ENERGY_PROFIT.search(user_text or ""))


def affirmed_insured(user_text: str) -> bool:
    """True only when they say the homestead is perfectly insured, not when they want a policy."""
    return bool(_INSURED_TRUE.search(user_text or ""))


def extract_utilized(user_text: str) -> float | None:
    text = user_text or ""
    if _UTILIZED_NONE.search(text):
        return 0.0
    if _UTILIZED_FULL.search(text):
        return 100.0
    match = _UTILIZED_PCT.search(text)
    if not match:
        return None
    raw = next(group for group in match.groups() if group is not None)
    try:
        return clamp_utilized(float(raw))
    except ValueError:
        return None


def extract_hours(user_text: str) -> float | None:
    match = _HOURS.search(user_text or "")
    if not match:
        return None
    value = float(match.group(1))
    if value < 0 or value > 168:
        return None
    return value


def extract_aesthetic(user_text: str) -> float | None:
    match = _AESTHETIC.search(user_text or "")
    if not match:
        return None
    raw = next(group for group in match.groups() if group is not None)
    try:
        return clamp_aesthetic(float(raw))
    except ValueError:
        return None


def extract_energetic_pct(user_text: str) -> float | None:
    match = _ENERGETIC_PCT.search(user_text or "")
    if not match:
        return None
    try:
        return clamp_energetic(float(match.group(1)))
    except ValueError:
        return None


def extract_zip(user_text: str) -> str | None:
    match = _ZIP.search(user_text or "")
    return match.group(1) if match else None


def extract_pin(user_text: str) -> tuple[float, float] | None:
    """Homestead coordinates. A labeled sponsor application keeps its own lat and lng."""
    text = user_text or ""
    if _SPONSOR_FORM.search(text):
        return None
    lat_match = _PIN_LAT.search(text)
    lng_match = _PIN_LNG.search(text)
    if not lat_match or not lng_match:
        return None
    lat = float(lat_match.group(1))
    lng = float(lng_match.group(1))
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    return lat, lng


def extract_street(user_text: str) -> str | None:
    text = user_text or ""
    if _SPONSOR_FORM.search(text):
        return None
    match = _STREET.search(text)
    if not match:
        return None
    street = match.group(1).strip().rstrip(".")
    return street or None


def extract_vote(user_text: str) -> tuple[float, float]:
    price_match = _PRICE.search(user_text or "")
    price = 0.0
    if price_match:
        price = float(next(group for group in price_match.groups() if group is not None))
    stripped = _PRICE.sub(" ", user_text or "")
    unit_match = _VOTE_UNITS.search(stripped)
    units = float(unit_match.group(1)) if unit_match else 0.0
    return units, price
