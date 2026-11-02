"""Keep ledger and boolean scores tied to words the user actually said."""

import re

from app.northstar import DEFAULT_LEDGER, clamp_aesthetic, clamp_energetic

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


def extract_vote(user_text: str) -> tuple[float, float]:
    price_match = _PRICE.search(user_text or "")
    price = 0.0
    if price_match:
        price = float(next(group for group in price_match.groups() if group is not None))
    stripped = _PRICE.sub(" ", user_text or "")
    unit_match = _VOTE_UNITS.search(stripped)
    units = float(unit_match.group(1)) if unit_match else 0.0
    return units, price
