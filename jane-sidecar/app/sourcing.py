"""Deterministic 4-tier sponsor ranking. The SQL twin is g01_recommendation_score."""

from decimal import Decimal, ROUND_HALF_UP
import math
import re

from app.constitution import BANNED_RETAILER_STEMS, WALMART_STEM

TIER_WEIGHTS = {
    "homestead_fabrication": Decimal("1.00"),
    "local_manufacturer": Decimal("0.85"),
    "local_service_or_stock": Decimal("0.70"),
    "local_logistics_proxy": Decimal("0.50"),
}

SPONSOR_TIERS = (
    "local_manufacturer",
    "local_service_or_stock",
    "local_logistics_proxy",
)

_SEARCH_STOP_WORDS = {
    "and", "for", "from", "get", "help", "local", "need", "some", "that",
    "the", "their", "this", "with",
}

EARTH_RADIUS_MILES = 3958.7613


def normalize_service_tag(raw: str) -> str | None:
    tag = re.sub(r"[^a-z0-9_]+", "_", str(raw or "").strip().lower().replace("-", "_")).strip("_")
    return tag if re.fullmatch(r"[a-z0-9_]{2,120}", tag) else None


def _search_terms(raw: str) -> set[str]:
    terms: set[str] = set()
    for word in re.findall(r"[a-z0-9]+", str(raw or "").casefold().replace("_", " ")):
        if word in _SEARCH_STOP_WORDS or len(word) < 2:
            continue
        # Prefix stems make tomato/tomatoes and print/printed/printing meet
        # without asking Gemini to invent a product category.
        terms.add(word[:5] if len(word) >= 5 else word)
    return terms


def company_norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (name or "").casefold())


def is_rogers_origin(locality_city: str, locality_state: str, founding_city: str, founding_state: str) -> bool:
    return (
        (locality_city or "").casefold() == "rogers"
        and (locality_state or "").casefold() == "ar"
        and (founding_city or "").casefold() == "rogers"
        and (founding_state or "").casefold() == "ar"
    )


def sponsor_rejection_reason(
    *,
    company_name: str,
    is_franchise_or_chain: bool,
    locality_city: str,
    locality_state: str,
    founding_city: str,
    founding_state: str,
    capabilities_summary: str = "",
) -> str | None:
    """Return a human-readable rejection, or None when the sponsor may be listed."""
    norm = company_norm(company_name)
    rogers = is_rogers_origin(locality_city, locality_state, founding_city, founding_state)
    if any(stem in norm for stem in BANNED_RETAILER_STEMS):
        return "g01 does not list internet or big-box retailers"
    if WALMART_STEM in norm and not rogers:
        return "Walmart may only appear in Rogers, Arkansas"
    if is_franchise_or_chain and not rogers:
        return "franchise chains are excluded outside the Rogers, Arkansas origin exception"
    if (founding_state or "").casefold() != (locality_state or "").casefold():
        return "founding state must sit inside the sponsor locality"
    if re.search(r"amazon\.|homedepot\.|lowes\.|walmart\.|wal-mart\.", capabilities_summary or "", re.I):
        return "sponsor text cannot link to a banned retailer"
    return None


def tier_weight(tier: str) -> Decimal:
    return TIER_WEIGHTS.get(tier, Decimal("0"))


def haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlng / 2) ** 2
    return EARTH_RADIUS_MILES * 2 * math.asin(math.sqrt(a))


def recommendation_score(
    *,
    sourcing_tier: str,
    distance_miles: float,
    max_radius_miles: float | None,
    referrals_last_14d: int,
    homesteader_rating: float,
    promo_boost_weight: float,
) -> Decimal:
    """Match g01_recommendation_score, rounded half-up to 4 decimal places."""
    radius = max(Decimal(str(max_radius_miles if max_radius_miles is not None else 25)), Decimal("0.0001"))
    distance = max(Decimal(str(distance_miles or 0)), Decimal("0"))
    dist_score = max(Decimal("0"), Decimal("1") - (distance / radius))
    rotation_score = Decimal("1") / (Decimal(1 + max(int(referrals_last_14d or 0), 0)))
    rating_score = min(Decimal("1"), max(Decimal("0"), Decimal(str(homesteader_rating if homesteader_rating is not None else 5)) / Decimal("5")))
    promo = Decimal(str(promo_boost_weight if promo_boost_weight is not None else 1))
    raw = tier_weight(sourcing_tier) * (
        Decimal("0.45") + Decimal("0.25") * dist_score + Decimal("0.20") * rotation_score + Decimal("0.10") * rating_score
    ) * promo
    return raw.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def sponsor_matches_tag(sponsor: dict, service_tag: str) -> bool:
    wanted = normalize_service_tag(service_tag)
    tags = [normalize_service_tag(tag) for tag in sponsor.get("service_tags") or []]
    if wanted and wanted in tags:
        return True
    profile_text = " ".join(
        [
            *(str(tag) for tag in sponsor.get("service_tags") or []),
            str(sponsor.get("capabilities_summary") or ""),
        ]
    )
    return bool(_search_terms(service_tag) & _search_terms(profile_text))


def rank_sponsor_rows(
    *,
    property_row: dict,
    locality: dict,
    sponsors: list[dict],
    service_tag: str,
    limit: int = 5,
) -> list[dict]:
    """Pure ranking used by the memory store and by tests. Postgres calls the SQL function."""
    ranked: list[dict] = []
    for sponsor in sponsors:
        if sponsor.get("locality_id") != property_row.get("locality_id"):
            continue
        if not sponsor.get("is_active_sponsor"):
            continue
        if not sponsor_matches_tag(sponsor, service_tag):
            continue
        reason = sponsor_rejection_reason(
            company_name=sponsor.get("company_name", ""),
            is_franchise_or_chain=bool(sponsor.get("is_franchise_or_chain")),
            locality_city=locality.get("primary_city", ""),
            locality_state=locality.get("state_code", ""),
            founding_city=sponsor.get("founding_city", ""),
            founding_state=sponsor.get("founding_state", ""),
            capabilities_summary=sponsor.get("capabilities_summary", ""),
        )
        if reason:
            continue
        distance = haversine_miles(property_row["lat"], property_row["lng"], sponsor["lat"], sponsor["lng"])
        score = recommendation_score(
            sourcing_tier=sponsor["sourcing_tier"],
            distance_miles=distance,
            max_radius_miles=locality.get("max_radius_miles", 25),
            referrals_last_14d=int(sponsor.get("referrals_last_14d") or 0),
            homesteader_rating=float(sponsor.get("homesteader_rating") if sponsor.get("homesteader_rating") is not None else 5),
            promo_boost_weight=float(sponsor.get("promo_boost_weight") if sponsor.get("promo_boost_weight") is not None else 1),
        )
        ranked.append(
            {
                "sponsor_id": sponsor["id"],
                "company_name": sponsor["company_name"],
                "sourcing_tier": sponsor["sourcing_tier"],
                "tier_weight": float(tier_weight(sponsor["sourcing_tier"])),
                "distance_miles": round(distance, 4),
                "score": float(score),
                "promo_boost_weight": float(sponsor.get("promo_boost_weight") or 1),
                "referrals_last_14d": int(sponsor.get("referrals_last_14d") or 0),
                "homesteader_rating": float(sponsor.get("homesteader_rating") if sponsor.get("homesteader_rating") is not None else 5),
                "capabilities_summary": str(sponsor.get("capabilities_summary") or "").strip(),
                "founding_city": str(sponsor.get("founding_city") or "").strip(),
                "founding_state": str(sponsor.get("founding_state") or "").strip(),
            }
        )
    ranked.sort(key=lambda row: (-row["score"], row["referrals_last_14d"], row["sponsor_id"]))
    return ranked[: max(limit, 1)]


def format_ladder(need: str, rows: list[dict]) -> str:
    if not rows:
        return f"I don't have an active g01 sponsor for {need} in your locality yet."
    lines = []
    for row in rows:
        summary = str(row.get("capabilities_summary") or "").strip()
        lines.append(f"{row['company_name']}{' — ' + summary if summary else ''}")
    return "\n".join(lines)
