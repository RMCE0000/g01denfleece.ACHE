"""Sponsorship answers are collected in the Chatwoot thread."""

import re

from app.errors import G01Error
from app.sourcing import SPONSOR_TIERS, normalize_service_tag, sponsor_rejection_reason
from app.stripe_service import create_sponsor_checkout

_FIELD_ORDER = (
    "company_name",
    "founding_city",
    "founding_state",
    "sourcing_tier",
    "service_tags",
    "capabilities_summary",
    "is_franchise_or_chain",
)

_PROMPTS = {
    "company_name": "What is the company name?",
    "founding_city": "What city was it founded in?",
    "founding_state": "What state was it founded in? Two letters, such as LA.",
    "sourcing_tier": "Which tier is it: local_manufacturer, local_service_or_stock, or local_logistics_proxy?",
    "service_tags": "What should I tag it as? One tag is enough, such as rain_catch or grow_lights.",
    "capabilities_summary": "In one sentence, what does the business actually do?",
    "is_franchise_or_chain": "Is it a franchise or a chain? Say yes or no.",
}


def missing_fields(draft: dict) -> list[str]:
    missing = []
    for key in _FIELD_ORDER:
        value = draft.get(key)
        if key == "service_tags":
            if not value:
                missing.append(key)
        elif key == "is_franchise_or_chain":
            if value is None:
                missing.append(key)
        elif value in (None, ""):
            missing.append(key)
    return missing


def _tag(raw: str) -> str | None:
    return normalize_service_tag(raw)


def parse_labeled_sponsor_fields(text: str) -> dict:
    """Read labeled answers. Free-text follow-ups are handled separately."""
    fields: dict = {}
    company = re.search(r"company(?: name)?:\s*(.+)", text, re.I)
    if company:
        fields["company_name"] = company.group(1).split("\n", 1)[0].strip().rstrip(".")
    city = re.search(r"founding city:\s*(.+)", text, re.I)
    if city:
        fields["founding_city"] = city.group(1).split("\n", 1)[0].strip().rstrip(".")
    state = re.search(r"founding state:\s*([A-Za-z]{2})", text, re.I)
    if state:
        fields["founding_state"] = state.group(1).upper()
    tier = re.search(r"tier:\s*(local_manufacturer|local_service_or_stock|local_logistics_proxy)", text, re.I)
    if tier:
        fields["sourcing_tier"] = tier.group(1)
    tags = re.search(r"tags?:\s*(.+)", text, re.I)
    if tags:
        parsed = [tag for item in tags.group(1).split("\n", 1)[0].split(",") if (tag := _tag(item))]
        if parsed:
            fields["service_tags"] = parsed
    summary = re.search(r"summary:\s*(.+)", text, re.I)
    if summary:
        fields["capabilities_summary"] = summary.group(1).strip()
    franchise = re.search(r"franchise:\s*(yes|no|true|false)", text, re.I)
    if franchise:
        fields["is_franchise_or_chain"] = franchise.group(1).casefold() in ("yes", "true")
    latitude = re.search(r"lat(?:itude)?:\s*(-?\d+(?:\.\d+)?)", text, re.I)
    if latitude:
        fields["lat"] = float(latitude.group(1))
    longitude = re.search(r"(?:lng|longitude):\s*(-?\d+(?:\.\d+)?)", text, re.I)
    if longitude:
        fields["lng"] = float(longitude.group(1))
    promo = re.search(r"promo(?: code)?:\s*([A-Za-z0-9_-]+)", text, re.I)
    if promo:
        fields["promo_code"] = promo.group(1)
    return fields


def absorb_next_answer(text: str, draft: dict) -> dict:
    """When Jane asked one question, the next message is that answer."""
    pending = missing_fields(draft)
    if not pending:
        return {}
    answer = text.strip()
    key = pending[0]
    if key == "founding_state" and re.fullmatch(r"[A-Za-z]{2}", answer):
        return {"founding_state": answer.upper()}
    if key == "sourcing_tier" and answer in SPONSOR_TIERS:
        return {"sourcing_tier": answer}
    if key == "service_tags":
        tag = _tag(answer.split(",")[0])
        return {"service_tags": [tag]} if tag else {}
    if key == "is_franchise_or_chain" and re.fullmatch(r"yes|no|true|false", answer, re.I):
        return {"is_franchise_or_chain": answer.casefold() in ("yes", "true")}
    if key == "capabilities_summary" and len(answer) >= 8:
        return {"capabilities_summary": answer}
    if key in ("company_name", "founding_city") and answer and "\n" not in answer and len(answer) <= 120:
        return {key: answer.rstrip(".")}
    return {}


def next_prompt(draft: dict) -> str:
    missing = missing_fields(draft)
    if not missing:
        return ""
    return _PROMPTS[missing[0]]


async def file_sponsor_application(store, prop: dict, locality: dict, draft: dict) -> str:
    """Create an inactive sponsor and, when Stripe is configured, put the payment link in the thread."""
    latitude = draft.get("lat", prop["lat"])
    longitude = draft.get("lng", prop["lng"])
    reason = sponsor_rejection_reason(
        company_name=draft["company_name"],
        is_franchise_or_chain=bool(draft["is_franchise_or_chain"]),
        locality_city=locality["primary_city"],
        locality_state=locality["state_code"],
        founding_city=draft["founding_city"],
        founding_state=draft["founding_state"],
        capabilities_summary=draft["capabilities_summary"],
    )
    if reason:
        await store.save_sponsor_draft(prop["id"], None)
        return reason.rstrip(".") + ". I did not file the listing."

    promo = None
    if draft.get("promo_code"):
        promo = await store.get_promo(draft["promo_code"])
        if not promo or not promo["active"] or promo["current_uses"] >= promo["max_uses"]:
            return "That promo code is not usable. Say a different code, or say promo: none."
        if promo.get("restricted_locality_id") and promo["restricted_locality_id"] != prop["locality_id"]:
            return "That promo code is for a different locality."

    sponsor = await store.create_sponsor(
        {
            "property_id": prop["id"],
            "locality_id": prop["locality_id"],
            "company_name": draft["company_name"],
            "founding_city": draft["founding_city"],
            "founding_state": draft["founding_state"],
            "is_franchise_or_chain": bool(draft["is_franchise_or_chain"]),
            "sourcing_tier": draft["sourcing_tier"],
            "service_tags": list(draft["service_tags"]),
            "capabilities_summary": draft["capabilities_summary"],
            "lat": float(latitude),
            "lng": float(longitude),
            "applied_promo_code": promo["code"] if promo else None,
            "is_active_sponsor": False,
        }
    )
    await store.save_sponsor_draft(prop["id"], None)
    try:
        checkout = await create_sponsor_checkout(sponsor["id"], promo)
    except G01Error as exc:
        if exc.status_code == 503:
            return (
                f"I filed {sponsor['company_name']} as an inactive sponsor. "
                "Stripe is not configured, so I did not open a payment page and the listing stays off the registry."
            )
        raise
    await store.attach_checkout(checkout["id"], sponsor["id"])
    return (
        f"I filed {sponsor['company_name']} as an inactive sponsor. "
        f"The listing turns on after Stripe marks this payment paid: {checkout['url']}"
    )
