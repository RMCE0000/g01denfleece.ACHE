"""Code-side reading of a homesteader message.

Scores and side effects come from what was written in the thread, not from model guesses.
Gemini may still draft the prose reply when a key is configured.
"""

import re

from app.epistemic import (
    affirmed_contained,
    affirmed_energy_profit,
    affirmed_material,
    affirmed_material_surplus,
    extract_aesthetic,
    extract_energetic_pct,
    extract_hours,
    extract_vote,
    extract_zip,
)
from app.northstar import view_from_property
from app.sponsor_chat import absorb_next_answer, missing_fields, parse_labeled_sponsor_fields

_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_YES = re.compile(r"\b(yes|accept|i accept)\b", re.I)
_NO = re.compile(r"\b(no|decline)\b", re.I)
_DEMAND = re.compile(r"\b(demand|would (people|neighbors) buy|local market|is there a market)\b", re.I)
_BUSINESS = re.compile(
    r"started a business|starting a business|my new business|register as a (local )?sponsor|become a sponsor|sponsorship",
    re.I,
)
_CANCEL_SPONSOR = re.compile(r"\bcancel (the |my )?sponsor", re.I)
_NEED = re.compile(r"\b(need|buy|source|find|looking for|where can i)\b", re.I)
_ASK_RECORD = re.compile(
    r"\b(what are my scores|how am i doing|north star|where do i stand|my automated|my aesthetic|my material|my energetic|my contained)\b",
    re.I,
)
_KYC = re.compile(r"\b(verify my identity|identity verification|start kyc|stripe identity)\b", re.I)

_TAGS = (
    ("grow_lights", ("grow light", "grow lights", "aquaponics light")),
    ("pressure_washing", ("pressure washer", "pressure washing")),
    ("rain_catch", ("rainwater", "rain catch", "cistern")),
    ("chicken_coop", ("chicken coop", "chickens")),
    ("logistics", ("logistics sponsor", "haul it", "local logistics")),
    ("lumber", ("lumber", "timber")),
    ("general_goods", ("general goods",)),
)
_GOAL_PHRASES = (
    "aquaponics",
    "chicken coop",
    "rainwater catchment",
    "permaculture",
    "grow light",
    "timber frame",
)


def _blank() -> dict:
    return {
        "reply": "",
        "ledger_patch": {},
        "outside_aid_hours_per_week": None,
        "aesthetic_pct": None,
        "material_independent": None,
        "material_surplus_profitable": None,
        "energetic_pct": None,
        "energetic_profitable": None,
        "contained_zero_waste": None,
        "service_tag": None,
        "start_poll": False,
        "poll_topic": None,
        "poll_question": None,
        "vote_poll_id": None,
        "weekly_units": None,
        "price_per_unit": None,
        "match_id": None,
        "match_decision": None,
        "sponsor_active": False,
        "cancel_sponsor": False,
        "sponsor_fields": {},
        "report_scores": False,
        "request_kyc": False,
        "zip_code": None,
    }


def detect_service_tag(text: str) -> str | None:
    lowered = text.casefold()
    for tag, phrases in _TAGS:
        if any(phrase in lowered for phrase in phrases):
            if _NEED.search(text) or any(len(phrase.split()) > 1 and phrase in lowered for phrase in phrases):
                return tag
    return None


def _match_decision(text: str, matches: list[dict]) -> tuple[str | None, str | None]:
    found = _UUID.search(text or "")
    explicit = bool(found) or bool(re.fullmatch(r"(yes|accept|i accept|no|decline)([.!]|\s+[0-9a-f-]{36})?", (text or "").strip(), re.I))
    if not explicit:
        return None, None
    if _YES.search(text) and not _NO.search(text):
        decision = "accepted"
    elif _NO.search(text) and not _YES.search(text):
        decision = "declined"
    else:
        return None, None
    if found:
        return found.group(0).lower(), decision
    if len(matches) == 1:
        return matches[0]["id"], decision
    return None, None


def status_reply(prop: dict, locality: dict | None) -> str:
    star = view_from_property(prop)["northstar"]
    place = locality["name"] if locality else "your locality"
    ledger = prop.get("known_facts_ledger") or {}
    missing = []
    if ledger.get("acreage") in (None, "", []):
        missing.append("acreage")
    if not ledger.get("active_goals"):
        missing.append("what you want to build next")
    gap = ""
    if missing:
        gap = " I still need " + " and ".join(missing) + " from you."
    return (
        f"On the record for {place}: "
        f"Automated {star['automated']:.2f} from {float(prop['outside_aid_hours_per_week']):.2f} hours a week of your labor or outside aid. "
        f"Aesthetic {star['aesthetic']:.2f}, which is your own rating. "
        f"Material is {str(bool(star['material'])).lower()}. "
        f"Energetic is {star['energetic']:.2f} with surplus profit {str(bool(star['energetic_profitable'])).lower()}. "
        f"Contained is {str(bool(star['contained'])).lower()}."
        f"{gap}"
    )


def heuristic_decision(state: dict) -> dict:
    message = state.get("message") or {}
    text = message.get("content") or ""
    prop = state.get("property")
    locality = state.get("locality")
    decision = _blank()
    matches = state.get("matches") or []
    invites = state.get("invites") or []

    match_id, match_status = _match_decision(text, matches)
    if match_id and match_status:
        decision["match_id"] = match_id
        decision["match_decision"] = match_status
        decision["reply"] = "I recorded that answer on the collaboration. A shared thread opens only after both of you accept and both pass identity verification."
        return decision

    if prop is None:
        decision["zip_code"] = extract_zip(text)
        decision["reply"] = (
            "I don't have this homestead on the record yet. Send the ZIP code and I'll attach this open thread to a locality. "
            "I only know what you tell me."
        )
        return decision

    hours = extract_hours(text)
    if hours is not None:
        decision["outside_aid_hours_per_week"] = hours
    aesthetic = extract_aesthetic(text)
    if aesthetic is not None:
        decision["aesthetic_pct"] = aesthetic
    energetic = extract_energetic_pct(text)
    if energetic is not None:
        decision["energetic_pct"] = energetic
    if affirmed_material(text):
        decision["material_independent"] = True
    if affirmed_material_surplus(text):
        decision["material_surplus_profitable"] = True
    if affirmed_contained(text):
        decision["contained_zero_waste"] = True
    if affirmed_energy_profit(text):
        decision["energetic_profitable"] = True

    goals = []
    lowered = text.casefold()
    for phrase in _GOAL_PHRASES:
        if phrase in lowered:
            goals.append(phrase)
    if goals:
        decision["ledger_patch"] = {"active_goals": goals}
    acreage = re.search(r"(\d+(?:\.\d+)?)\s*acres?", text, re.I)
    if acreage:
        decision["ledger_patch"]["acreage"] = acreage.group(1)

    if invites and hours is None and aesthetic is None and re.search(r"\d", text):
        units, price = extract_vote(text)
        decision["vote_poll_id"] = invites[0]["poll_id"]
        decision["weekly_units"] = units
        decision["price_per_unit"] = price
        decision["reply"] = "I logged that as your answer to the neighborhood question. I won't fold it into a demand figure until the 24 hours are up."
        return decision

    if _ASK_RECORD.search(text):
        decision["report_scores"] = True

    if _KYC.search(text):
        decision["request_kyc"] = True
        decision["reply"] = "Identity verification happens from a Stripe link I post in this thread. A shared neighbor thread still waits until both of you are verified."

    if _CANCEL_SPONSOR.search(text):
        decision["cancel_sponsor"] = True
        decision["sponsor_active"] = True
        decision["reply"] = "I cleared the sponsorship application."
    else:
        draft = dict((prop or {}).get("sponsor_draft") or {})
        labeled = parse_labeled_sponsor_fields(text)
        absorb = {}
        sourcing_turn = bool(detect_service_tag(text))
        if draft and missing_fields(draft) and not labeled and not decision["report_scores"] and not sourcing_turn and not decision["request_kyc"]:
            absorb = absorb_next_answer(text, draft)
        if _BUSINESS.search(text) or labeled or absorb:
            decision["sponsor_active"] = True
            decision["sponsor_fields"] = {**labeled, **absorb}
            if not decision["reply"]:
                decision["reply"] = "We can file that sponsor from this thread. I only list a local company, and it stays inactive until Stripe says the payment is complete."

    if _DEMAND.search(text):
        tag = detect_service_tag(text) or "local_demand"
        decision["start_poll"] = True
        decision["poll_topic"] = tag
        decision["poll_question"] = (
            f"A homestead in your locality is considering {tag.replace('_', ' ')}. "
            "How many units a week would you want, and what price per unit would you pay?"
        )
        decision["reply"] = (
            "I'll ask other homesteads in this locality and bring the answers back after 24 hours. "
            "I won't invent a demand number, and I won't send your street address with the question."
        )

    tag = detect_service_tag(text)
    if tag and not decision["start_poll"]:
        decision["service_tag"] = tag
        if not decision["reply"]:
            decision["reply"] = "I'll stay inside your locality and start with what you can make on the homestead."

    wrote_score = any(
        decision[key] is not None
        for key in (
            "outside_aid_hours_per_week",
            "aesthetic_pct",
            "material_independent",
            "material_surplus_profitable",
            "energetic_pct",
            "energetic_profitable",
            "contained_zero_waste",
        )
    )
    if not decision["reply"] and not decision["report_scores"] and not wrote_score:
        decision["reply"] = status_reply(prop, locality)
    return decision
