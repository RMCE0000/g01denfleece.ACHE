"""Sponsorship answers are collected in the Chatwoot thread."""

import asyncio
import re

from contextvars import ContextVar

from app.errors import G01Error
from app.gemini_flow import lookup_public
from app.llm import complete_json
from app.mail import send_sponsor_payment_link
from app.config import get_settings
from app.sourcing import SPONSOR_TIERS, normalize_service_tag, sponsor_rejection_reason
from app.stripe_service import create_sponsor_checkout, retrieve_checkout_url, stripe_ready

message_read_override: ContextVar = ContextVar("g01_message_read_override", default=None)

_FIELD_ORDER = (
    "company_name",
    "founding_city",
    "founding_state",
    "sourcing_tier",
    "service_tags",
    "capabilities_summary",
    "is_franchise_or_chain",
    "billing_email",
)

_PROMPTS = {
    "listing_kind": "Is this sponsorship for your homestead, or for a separate local company?",
    "company_name": "What is the company name?",
    "founding_city": "What city was it founded in?",
    "founding_state": "What state was it founded in?",
    "sourcing_tier": "What type of company is it?",
    "service_tags": "What does it make or sell?",
    "capabilities_summary": "In one sentence, what does the business actually do?",
    "is_franchise_or_chain": "Is it a franchise or a chain? Say yes or no.",
    "billing_email": "What email should receive the payment link?",
}

_HOMESTEAD_PROMPTS = {
    "company_name": "What should neighbors call this homestead?",
    "founding_city": "What city is the homestead in?",
    "founding_state": "What state is the homestead in?",
    "service_tags": "What does the homestead offer?",
    "capabilities_summary": "In one sentence, what does the homestead actually do?",
    "is_franchise_or_chain": "Is it a franchise or a chain? Say yes or no.",
    "billing_email": "What email should receive the payment link?",
}

_EMAIL_FIND = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
_PAYMENT_MAIL = re.compile(r"\b(payment|pay|checkout|invoice|receipt)\b", re.I)
_PAYMENT_ASK = re.compile(
    r"\b(send|resend|email|inbox|didn't|did not|never (?:got|received)|not (?:get|receive|received)|missing|link)\b",
    re.I,
)
_SPONSOR_EMAIL_FOLLOWUP = re.compile(
    r"\b(?:send|resend) (?:that|the|this|my) (?:e-?mail|link)\b|"
    r"\b(?:check|confirm|verify) (?:that |if |whether )?(?:it|that|the e-?mail|the link|this) was sent\b|"
    r"\bwas (?:it|that|the e-?mail|the link) sent\b|"
    r"\bdid you send (?:it|that|the e-?mail|the link)\b",
    re.I,
)


def sponsor_name_key(value: str) -> str:
    return " ".join(str(value or "").casefold().split())


def listing_kind(answer: str) -> str | None:
    """Tell a homestead listing from a separate local company without internal codes."""
    cleaned = answer.strip().rstrip(".")
    compact = " ".join(cleaned.casefold().split())
    homestead = {
        "homestead",
        "my homestead",
        "our homestead",
        "the homestead",
        "for my homestead",
        "for our homestead",
        "for the homestead",
        "this homestead",
    }
    company = {
        "company",
        "a company",
        "local company",
        "a local company",
        "separate company",
        "a separate company",
        "separate local company",
        "a separate local company",
        "for a company",
        "for a local company",
        "for a separate local company",
    }
    if compact in homestead:
        return "homestead"
    if compact in company:
        return "company"
    mentions_homestead = bool(re.search(r"\bhomestead\b", cleaned, re.I))
    mentions_company = bool(re.search(r"\b(company|business|shop|store)\b", cleaned, re.I))
    if mentions_homestead and not mentions_company:
        return "homestead"
    if mentions_company:
        return "company"
    return None


def _resolved_kind(draft: dict) -> str | None:
    kind = draft.get("listing_kind")
    if kind in ("homestead", "company"):
        return kind
    if any(draft.get(key) not in (None, "", []) for key in ("company_name", "founding_city", "founding_state", "sourcing_tier", "service_tags")):
        return "company"
    return None


def missing_fields(draft: dict) -> list[str]:
    if _resolved_kind(draft) is None:
        return ["listing_kind"]
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


_STATE_NAMES = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "district of columbia": "DC",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
}


def _state_code(answer: str) -> str | None:
    cleaned = answer.strip().rstrip(".")
    if re.fullmatch(r"[A-Za-z]{2}", cleaned):
        code = cleaned.upper()
        return code if code in _STATE_NAMES.values() else None
    return _STATE_NAMES.get(cleaned.casefold())


def company_type(answer: str) -> str | None:
    """Map a plain description to a sourcing tier. The homesteader never types the tier code."""
    cleaned = answer.strip().rstrip(".")
    compact = re.sub(r"[\s-]+", "_", cleaned.casefold())
    if compact in SPONSOR_TIERS:
        return compact
    if re.search(r"\b(deliver(?:y|ies)?|logistics|hauls?|trucking)\b", cleaned, re.I):
        return "local_logistics_proxy"
    if re.search(r"\b(manufactur\w*|makes?|making|grows?|growing|mills?|sews?|builds?|fabricat\w*|produces?|production)\b", cleaned, re.I):
        return "local_manufacturer"
    if re.search(r"\b(store|shop|stock|service|retail|sells?|selling|company|business|farm|brand)\b", cleaned, re.I):
        return "local_service_or_stock"
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9 &'.,-]{2,120}", cleaned):
        return "local_service_or_stock"
    return None


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
    billing = re.search(
        r"(?:billing email|payment email|email):\s*([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})",
        text,
        re.I,
    )
    if billing:
        fields["billing_email"] = billing.group(1).casefold()
    return fields


def message_has_email(text: str) -> bool:
    return bool(_EMAIL_FIND.search(text or ""))


_SPONSOR_STATUS = re.compile(
    r"\b(?:is )?(?:my |the |our )?(?:sponsorship|sponsor listing) (?:active|paid|on|live)\b|"
    r"\b(?:did|has) (?:my |the )?(?:sponsorship|payment|invoice) (?:go through|been paid|clear(?:ed)?)\b|"
    r"\bwas (?:the |my )?(?:sponsorship|invoice|payment) paid\b",
    re.I,
)


def sponsorship_status_request(text: str) -> bool:
    """A question about the stored listing, not a request to send the link again."""
    if _SPONSOR_EMAIL_FOLLOWUP.search(text or ""):
        return False
    return bool(_SPONSOR_STATUS.search(text or ""))


def payment_email_request(text: str) -> dict | None:
    """A homesteader asking for the payment message, with an address when they named one."""
    email = _EMAIL_FIND.search(text)
    if not _PAYMENT_MAIL.search(text) and not _SPONSOR_EMAIL_FOLLOWUP.search(text):
        return None
    if _PAYMENT_MAIL.search(text) and not _PAYMENT_ASK.search(text) and email is None:
        return None
    if (
        _PAYMENT_MAIL.search(text)
        and not _PAYMENT_ASK.search(text)
        and not _SPONSOR_EMAIL_FOLLOWUP.search(text)
        and not re.search(r"\b(link|email|inbox)\b", text, re.I)
    ):
        return None
    return {"to": email.group(0).casefold() if email else None}


def _yes_no(text: str) -> bool | None:
    """A yes or no that opens the message, even when the sentence continues."""
    cleaned = text.strip()
    if re.fullmatch(r"(?:yes|yeah|yep|yup|sure|no|nope|nah|true|false)", cleaned, re.I):
        return cleaned.casefold() in ("yes", "yeah", "yep", "yup", "sure", "true")
    if re.match(r"^(?:no|nope|nah|not)\b", cleaned, re.I):
        return False
    if re.match(r"^(?:yes|yeah|yep|yup|sure)\b", cleaned, re.I):
        return True
    return None


def absorb_next_answer(text: str, draft: dict, locality: dict | None = None) -> dict:
    """When Jane asked one question, the next message is that answer."""
    pending = missing_fields(draft)
    if not pending:
        return {}
    answer = text.strip()
    key = pending[0]
    if key == "listing_kind":
        kind = listing_kind(answer)
        if not kind:
            return {}
        fields = {"listing_kind": kind}
        if kind == "homestead" and locality:
            city = str(locality.get("primary_city") or "").strip()
            state = str(locality.get("state_code") or "").strip().upper()
            if city:
                fields["founding_city"] = city
            if state:
                fields["founding_state"] = state
            fields["sourcing_tier"] = "local_service_or_stock"
        return fields
    if key == "founding_state":
        state = _state_code(answer)
        return {"founding_state": state} if state else {}
    if key == "sourcing_tier":
        tier = company_type(answer)
        return {"sourcing_tier": tier} if tier else {}
    if key == "service_tags":
        tag = _tag(answer.split(",")[0])
        if not tag:
            return {}
        company = str(draft.get("company_name") or "The homestead").strip().rstrip(".")
        offered = "offers" if draft.get("listing_kind") == "homestead" else "makes or sells"
        summary = answer if len(answer) >= 8 else f"{company} {offered} {answer.rstrip('.')}."
        fields = {"service_tags": [tag], "capabilities_summary": summary}
        if draft.get("listing_kind") == "homestead":
            typed = company_type(answer)
            if typed:
                fields["sourcing_tier"] = typed
        return fields
    if key == "is_franchise_or_chain":
        answered = _yes_no(answer)
        return {"is_franchise_or_chain": answered} if answered is not None else {}
    if key == "capabilities_summary" and len(answer) >= 8:
        return {"capabilities_summary": answer}
    if key == "billing_email":
        found = _EMAIL_FIND.search(answer)
        return {"billing_email": found.group(0).casefold()} if found else {}
    if key in ("company_name", "founding_city") and answer and "\n" not in answer and len(answer) <= 120:
        return {key: answer.rstrip(".")}
    return {}


def _rich_answer(text: str) -> bool:
    stripped = text.strip()
    return len(stripped) > 40 or stripped.count(" ") > 6


def _company_name_from_text(text: str, locality: dict | None) -> str | None:
    called = re.search(
        r"\b(?:called|named|name is|name's)\s+([A-Z][\w'&-]*(?:\s+[A-Z][\w'&-]*){0,3})",
        text,
    )
    if called:
        return called.group(1).strip()
    city = str((locality or {}).get("primary_city") or "").casefold()
    for sentence in re.split(r"[.!?]+", text):
        candidate = sentence.strip()
        if not candidate or len(candidate.split()) > 4:
            continue
        if re.match(r"^(i|we|it|they|my|our|a|the)\b", candidate, re.I):
            continue
        if listing_kind(candidate):
            continue
        if city and candidate.casefold() == city:
            continue
        if re.match(r"^[A-Z0-9]", candidate):
            return candidate
    camel = re.search(r"\b[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+\b", text)
    return camel.group(0) if camel else None


def _scan_sponsor_facts(text: str, draft: dict, locality: dict | None) -> dict:
    """Read every sponsorship fact in the message, not only the next blank."""
    fields: dict = {}
    if not draft.get("listing_kind"):
        kind = listing_kind(text)
        if kind:
            fields["listing_kind"] = kind
            if kind == "homestead" and locality:
                city = str(locality.get("primary_city") or "").strip()
                state = str(locality.get("state_code") or "").strip().upper()
                if city:
                    fields["founding_city"] = city
                if state:
                    fields["founding_state"] = state
                fields["sourcing_tier"] = "local_service_or_stock"
    if not draft.get("billing_email") and "billing_email" not in fields:
        email = _EMAIL_FIND.search(text)
        if email and not re.search(r"(?:billing email|payment email|email):", text, re.I):
            fields["billing_email"] = email.group(0).casefold()
    if locality and not draft.get("founding_city") and "founding_city" not in fields:
        city = str(locality.get("primary_city") or "").strip()
        if city and city.casefold() in text.casefold():
            fields["founding_city"] = city
    if not draft.get("founding_state") and "founding_state" not in fields:
        for name, code in _STATE_NAMES.items():
            if re.search(rf"\b{re.escape(name)}\b", text, re.I):
                fields["founding_state"] = code
                break
    offer = re.search(
        r"\b(?:i|we)\s+(?:make|makes|making|grow|grows|growing|sell|sells|selling|sew|sews|mill|mills|build|builds|deliver|delivers|haul|hauls)\s+(.+)",
        text,
        re.I,
    )
    brand = re.search(
        r"\b(?:we are|we're|i am)\s+(?:a|an)\s+([a-z0-9][a-z0-9 ]{0,40}?)\s+brand\b",
        text,
        re.I,
    )
    if brand and not draft.get("service_tags") and "service_tags" not in fields:
        fields.update(_offer_fields(f"{brand.group(1).strip()} brand"))
    if offer and not draft.get("service_tags") and "service_tags" not in fields:
        product = re.split(r"\b(?:here|in|at|for)\b", offer.group(1), maxsplit=1, flags=re.I)[0]
        product = product.strip(" .!")
        tag = _tag(product.split(",")[0])
        if tag:
            fields["service_tags"] = [tag]
            fields["capabilities_summary"] = offer.group(0).strip().rstrip(".!")
            typed = company_type(offer.group(0))
            if typed and not draft.get("sourcing_tier"):
                fields["sourcing_tier"] = typed
    if not draft.get("company_name") and "company_name" not in fields:
        name = _company_name_from_text(text, locality)
        if name:
            fields["company_name"] = name
    if draft.get("is_franchise_or_chain") is None and "is_franchise_or_chain" not in fields:
        if re.search(r"\b(not a franchise|not a chain|no franchise|independently owned)\b", text, re.I):
            fields["is_franchise_or_chain"] = False
        elif re.search(r"\b(is a franchise|is a chain|we're a franchise|we are a franchise)\b", text, re.I):
            fields["is_franchise_or_chain"] = True
    return fields


def read_sponsor_message(text: str, draft: dict, locality: dict | None = None) -> dict:
    """Keep every fact the homesteader already gave, then fill one short blank if needed."""
    fields = _scan_sponsor_facts(text, draft, locality)
    combined = {**draft, **fields}
    if not missing_fields(combined):
        return fields
    extra = absorb_next_answer(text, combined, locality)
    for key, value in extra.items():
        if key in fields:
            continue
        if key in ("company_name", "founding_city") and _rich_answer(text):
            continue
        if key == "company_name" and listing_kind(str(value)):
            continue
        fields[key] = value
    return fields


_READ_SYSTEM = (
    "Extract sponsorship facts explicitly stated in the message. "
    "Return one JSON object and omit every key the message does not state. Do not infer. "
    "\"I want to become a sponsor\" does not state whether it is a homestead or a company. "
    "Keys you may include: listing_kind (homestead or company), company_name, founding_city, "
    "founding_state, what_they_do, is_franchise_or_chain (true or false), billing_email."
)


def _stated(text: str, value: str) -> bool:
    return bool(value) and value.casefold() in text.casefold()


def _offer_fields(what: str) -> dict:
    cleaned = " ".join(what.split()).strip(" .!")
    if not cleaned:
        return {}
    product = re.sub(r"\b(a|an|the|brand|company|business|local)\b", " ", cleaned, flags=re.I)
    product = " ".join(product.split())
    tag = _tag(product or cleaned)
    fields = {"capabilities_summary": cleaned}
    if tag:
        fields["service_tags"] = [tag]
    if re.search(
        r"\b(manufactur\w*|makes?|making|grows?|growing|deliver(?:y|ies)?|hauls?|trucking|store|shop|stock|service|retail|sells?|selling|company|business|farm|brand)\b",
        cleaned,
        re.I,
    ):
        typed = company_type(cleaned)
        if typed:
            fields["sourcing_tier"] = typed
    return fields


def sole_state_code(text: str) -> str | None:
    """One US state from a lookup answer. Two states is not a guess."""
    found = set()
    for name, code in _STATE_NAMES.items():
        if re.search(rf"\b{re.escape(name)}\b", text or "", re.I):
            found.add(code)
    stripped = (text or "").strip().rstrip(".")
    if re.fullmatch(r"[A-Za-z]{2}", stripped):
        code = stripped.upper()
        if code in _STATE_NAMES.values():
            found.add(code)
    if len(found) != 1:
        return None
    return found.pop()


def _public_city(city: str) -> str | None:
    cleaned = " ".join(str(city or "").split())
    if not cleaned or "@" in cleaned or not re.fullmatch(r"[A-Za-z][A-Za-z .'-]{1,80}", cleaned):
        return None
    return cleaned


def normalize_stated_facts(text: str, raw: dict) -> dict:
    """Keep a structured read only where the message itself contains the fact."""
    if not isinstance(raw, dict):
        return {}
    fields: dict = {}
    kind = str(raw.get("listing_kind") or "").strip().casefold()
    if kind == "homestead" and re.search(r"\bhomestead\b", text, re.I):
        fields["listing_kind"] = "homestead"
    elif kind == "company" and re.search(r"\b(company|business|shop|store)\b", text, re.I):
        fields["listing_kind"] = "company"
    name = str(raw.get("company_name") or "").strip().rstrip(".")
    if name and _stated(text, name) and not listing_kind(name) and len(name) <= 120:
        fields["company_name"] = name
    city = str(raw.get("founding_city") or "").strip().rstrip(".")
    if city and _stated(text, city) and len(city) <= 80:
        fields["founding_city"] = city
    state = _state_code(str(raw.get("founding_state") or ""))
    if state is None:
        state = sole_state_code(str(raw.get("founding_state") or ""))
    if state and sole_state_code(text) == state:
        fields["founding_state"] = state
    what = str(raw.get("what_they_do") or raw.get("capabilities_summary") or "").strip()
    if what and _stated(text, what):
        fields.update(_offer_fields(what))
    if "is_franchise_or_chain" in raw and re.search(r"\b(franchise|chain)\b", text, re.I):
        spoken = _yes_no(text)
        fields["is_franchise_or_chain"] = spoken if spoken is not None else raw.get("is_franchise_or_chain") in (True, "true", "yes", "Yes")
    email = str(raw.get("billing_email") or "")
    found = _EMAIL_FIND.search(text)
    if found and email and found.group(0).casefold() == email.strip().casefold():
        fields["billing_email"] = found.group(0).casefold()
    return fields


async def extract_stated_facts(text: str) -> dict:
    """Read the whole message. A missing model returns nothing rather than a guess."""
    override = message_read_override.get()
    if override is not None:
        result = override(text)
        if hasattr(result, "__await__"):
            result = await result
        return normalize_stated_facts(text, result if isinstance(result, dict) else {})
    if not get_settings().gemini_api_key:
        return {}
    try:
        raw = await complete_json(get_settings().gemini_chat_model, _READ_SYSTEM, text)
    except Exception:
        return {}
    return normalize_stated_facts(text, raw if isinstance(raw, dict) else {})


async def lookup_state_for_city(city: str) -> str | None:
    """Ask the public web which state a city is in. The question names only the city."""
    public = _public_city(city)
    if not public:
        return None
    found = await lookup_public(f"Which single US state is {public} in?")
    if not found:
        return None
    return sole_state_code(found)


def _speaker_text(lines: list[dict], *, jane: bool) -> str:
    parts = []
    for line in lines:
        content = " ".join(str(line.get("content") or "").split())
        if not content:
            continue
        is_jane = line.get("role") == "jane"
        if is_jane == jane:
            parts.append(content)
    return "\n".join(parts)


def franchise_from_thread(lines: list[dict]) -> bool | None:
    """A yes or no counts when it answers the franchise question already in the thread."""
    waiting = False
    for line in lines:
        text = str(line.get("content") or "").strip()
        if not text:
            continue
        if line.get("role") == "jane":
            if re.search(r"\b(franchise|chain)\b", text, re.I):
                waiting = True
            continue
        if not waiting:
            continue
        answer = _yes_no(text)
        if answer is not None:
            return answer
        if re.search(r"\b(not a franchise|not a chain|no franchise|independently owned)\b", text, re.I):
            return False
        if re.search(r"\b(is a franchise|is a chain|we're a franchise|we are a franchise)\b", text, re.I):
            return True
    return None


async def application_from_thread(lines: list[dict], locality: dict | None = None) -> tuple[dict, str | None, str | None]:
    """Read the whole thread once, for filing. Jane's reply does not come from this form."""
    fields: dict = {}
    for line in lines:
        if line.get("role") == "jane":
            continue
        text = str(line.get("content") or "")
        if not text.strip():
            continue
        for key, value in read_sponsor_message(text, fields, locality).items():
            if fields.get(key) in (None, "", []):
                fields[key] = value
        for key, value in parse_labeled_sponsor_fields(text).items():
            if fields.get(key) in (None, "", []):
                fields[key] = value
    homesteader = _speaker_text(lines, jane=False)
    for key, value in (await extract_stated_facts(homesteader)).items():
        if fields.get(key) in (None, "", []):
            fields[key] = value
    franchise = franchise_from_thread(lines)
    if franchise is not None and fields.get("is_franchise_or_chain") is None:
        fields["is_franchise_or_chain"] = franchise
    found_note = None
    failed_city = None
    city = fields.get("founding_city")
    if city and not fields.get("founding_state"):
        public_city = _public_city(str(city))
        found = await lookup_public(f"Which single US state is {public_city} in?") if public_city else None
        state = sole_state_code(found or "")
        if state:
            fields["founding_state"] = state
            found_note = (
                f"Public lookup, use this and do not invent beyond it: {public_city} is in {found}. "
                "Do not ask which state."
            )
        else:
            failed_city = public_city or str(city)
    return fields, found_note, failed_city


async def enrich_sponsor_fields(text: str, draft: dict, locality: dict | None = None) -> tuple[dict, str | None]:
    """Add facts the whole message stated, then look up a missing state for a known city."""
    combined = {**draft, **read_sponsor_message(text, draft, locality)}
    for key, value in (await extract_stated_facts(text)).items():
        if combined.get(key) in (None, "", []):
            combined[key] = value
    failed_city = None
    city = combined.get("founding_city")
    if city and not combined.get("founding_state"):
        state = await lookup_state_for_city(str(city))
        if state:
            combined["founding_state"] = state
        else:
            failed_city = _public_city(str(city)) or str(city)
    added = {}
    for key, value in combined.items():
        if draft.get(key) in (None, "", []) and value not in (None, "", []):
            added[key] = value
    return added, failed_city


_MISSING_WORDS = {
    "listing_kind": "whether this is their homestead or a separate local company",
    "company_name": "what it is called",
    "founding_city": "the city where it was founded",
    "founding_state": "the state where it was founded",
    "sourcing_tier": "what type of company it is",
    "service_tags": "what it makes or sells",
    "capabilities_summary": "what it actually does",
    "is_franchise_or_chain": "whether it is a franchise or a chain",
    "billing_email": "the email that should receive the payment link",
}


def sponsorship_thread_note(lookup_note: str | None = None) -> str:
    """The thread is the sponsorship record. Jane thinks over it instead of a parsed form."""
    lookup = f" {lookup_note}" if lookup_note else ""
    return (
        "A sponsorship application is open. The conversation thread is the only record of what they have said. "
        "Read every message above before you answer. Think about the whole thread, not only the latest line. "
        "Acknowledge what they just said. Ask one thing the thread still does not answer. "
        "Do not ask again for anything already said, including a yes or no that answered your previous question. "
        "Do not say they chose a homestead or a company unless their words did. "
        "Do not mention tier codes, scores, weights, distance, or referral rotation."
        + lookup
    )


def sponsorship_thinking_note(
    draft: dict,
    lookup_failed_city: str | None = None,
    lookup_found: str | None = None,
) -> str:
    """Private context so Jane can think about the answer instead of reciting a form."""
    recorded = []
    if draft.get("listing_kind") == "homestead":
        recorded.append("This listing is the homesteader's own homestead.")
    elif draft.get("listing_kind") == "company":
        recorded.append("This listing is a separate local company.")
    if draft.get("company_name"):
        recorded.append(f"Name: {draft['company_name']}.")
    if draft.get("founding_city"):
        recorded.append(f"City: {draft['founding_city']}.")
    if draft.get("founding_state"):
        recorded.append(f"State: {draft['founding_state']}.")
    if draft.get("capabilities_summary"):
        recorded.append(f"What they do: {draft['capabilities_summary']}.")
    elif draft.get("service_tags"):
        words = ", ".join(str(tag).replace("_", " ") for tag in draft["service_tags"])
        recorded.append(f"What they offer: {words}.")
    if draft.get("is_franchise_or_chain") is True:
        recorded.append("They said it is a franchise or a chain.")
    elif draft.get("is_franchise_or_chain") is False:
        recorded.append("They said it is not a franchise or a chain.")
    if draft.get("billing_email"):
        recorded.append(f"Payment email: {draft['billing_email']}.")
    missing_words = []
    for key in missing_fields(draft):
        if key == "company_name" and draft.get("listing_kind") == "homestead":
            missing_words.append("what neighbors should call the homestead")
        elif key == "service_tags" and draft.get("listing_kind") == "homestead":
            missing_words.append("what the homestead offers")
        else:
            missing_words.append(_MISSING_WORDS.get(key, key.replace("_", " ")))
    known = " ".join(recorded) if recorded else "nothing yet."
    lookup = ""
    if lookup_found:
        lookup = lookup_found.strip() + " "
    elif lookup_failed_city:
        lookup = (
            f"A public lookup for the state of {lookup_failed_city} did not return one clear answer. "
            "Tell them you could not look it up, then ask which state. "
        )
    return (
        "The homesteader is in the middle of a g01 sponsorship. "
        "Think about their latest answer before you reply. "
        f"Recorded so far: {known} "
        "Still needed, in this order: " + "; ".join(missing_words) + ". "
        + lookup
        + "Reply in your own words. Acknowledge what they just told you. "
        "Ask only for the first thing still needed. "
        "Do not ask again for anything already recorded. "
        "Do not claim they chose a homestead or a company unless Recorded so far says which one. "
        "Do not mention tier codes, scores, weights, distance, or referral rotation. "
        "Do not change the subject away from the sponsorship."
    )


def next_prompt(draft: dict) -> str:
    missing = missing_fields(draft)
    if not missing:
        return ""
    key = missing[0]
    if _resolved_kind(draft) == "homestead":
        return _HOMESTEAD_PROMPTS.get(key) or _PROMPTS[key]
    return _PROMPTS[key]


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

    existing = await store.inactive_sponsor_named(prop["id"], draft["company_name"])
    promo = None
    if draft.get("promo_code"):
        promo = await store.get_promo(draft["promo_code"])
        if not promo or not promo["active"] or promo["current_uses"] >= promo["max_uses"]:
            return "That promo code is not usable. Say a different code, or say promo: none."
        if promo.get("restricted_locality_id") and promo["restricted_locality_id"] != prop["locality_id"]:
            return "That promo code is for a different locality."

    if existing:
        sponsor = existing
    else:
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
    billing_email = str(draft.get("billing_email") or "").strip().casefold()
    try:
        checkout = await create_sponsor_checkout(
            sponsor["id"],
            promo,
            customer_email=billing_email or None,
            customer_id=sponsor.get("stripe_customer_id"),
            subscription_id=sponsor.get("stripe_subscription_id"),
        )
    except G01Error as exc:
        lead = _listing_lead(sponsor["company_name"], existing)
        if exc.status_code == 503:
            return (
                f"{lead} Stripe is not configured, so I did not open a payment page and the listing stays off the registry."
            )
        return f"{lead} {exc.message}"
    if checkout.get("customer_id") or checkout.get("subscription_id"):
        await store.remember_sponsor_billing(
            sponsor["id"],
            checkout.get("customer_id"),
            checkout.get("subscription_id"),
        )
    await store.attach_checkout(
        checkout["id"],
        sponsor["id"],
        url=checkout["url"],
        billing_email=billing_email or None,
    )
    mailed = await _mailed_payment_sentence(
        billing_email,
        sponsor["company_name"],
        checkout["url"],
        stripe_emailed=bool(checkout.get("stripe_emailed")),
    )
    return f"{_listing_lead(sponsor['company_name'], existing)} {mailed}"


def _listing_lead(name: str, existing: dict | None) -> str:
    if existing:
        return f"{name} already has an unpaid sponsorship, so I used that listing."
    return f"I filed {name} as an inactive sponsor."


async def _mailed_payment_sentence(email: str, company: str, url: str, stripe_emailed: bool = False) -> str:
    if not email:
        return f"Tell me the email address that should receive the payment link: {url}"
    smtp_sent = False
    try:
        await asyncio.to_thread(send_sponsor_payment_link, to=email, company=company, url=url)
        smtp_sent = True
    except G01Error:
        smtp_sent = False
    if stripe_emailed:
        copy = " I also sent a copy from g01." if smtp_sent else ""
        return (
            f"Stripe emailed the payment link to {email}.{copy} "
            f"The listing turns on after Stripe marks this payment paid: {url}"
        )
    if smtp_sent:
        return (
            f"I sent the payment link to {email}. "
            f"The listing turns on after Stripe marks this payment paid: {url}"
        )
    return f"I could not send the payment email to {email}. Use this secure payment link: {url}"


async def resend_sponsor_payment(store, prop: dict, email: str | None) -> str:
    """Email an existing sponsorship payment link to the address the homesteader names."""
    checkout = await store.latest_open_checkout(prop["id"])
    sponsor = await store.get_sponsor(checkout["sponsor_id"]) if checkout else None
    if sponsor is None:
        sponsor = await store.latest_inactive_sponsor(prop["id"])
    if checkout is None and sponsor is None:
        draft = prop.get("sponsor_draft") if isinstance(prop.get("sponsor_draft"), dict) else None
        if draft is not None and missing_fields(draft):
            return "I checked. Stripe has no sponsorship invoice yet, so nothing was emailed."
        return (
            "I checked. Stripe has no sponsorship invoice for this homestead, so nothing was emailed. "
            'Say "start sponsorship" and I will ask whether it is for your homestead or a separate local company.'
        )
    target = (
        email
        or (checkout or {}).get("billing_email")
        or prop.get("email")
        or ""
    ).strip().casefold()
    if not target:
        return "Tell me the email address that should receive the payment link."
    if stripe_ready() and sponsor is not None:
        try:
            fresh = await create_sponsor_checkout(
                sponsor["id"],
                None,
                customer_email=target,
                customer_id=sponsor.get("stripe_customer_id"),
                subscription_id=sponsor.get("stripe_subscription_id"),
            )
        except G01Error as exc:
            return exc.message
        await store.remember_sponsor_billing(sponsor["id"], fresh.get("customer_id"), fresh.get("subscription_id"))
        await store.attach_checkout(fresh["id"], sponsor["id"], url=fresh["url"], billing_email=target)
        return await _mailed_payment_sentence(
            target,
            sponsor["company_name"],
            fresh["url"],
            stripe_emailed=bool(fresh.get("stripe_emailed")),
        )
    url = (checkout or {}).get("url")
    session_id = (checkout or {}).get("session_id")
    if not url and session_id:
        url = await retrieve_checkout_url(session_id)
    if session_id and url and sponsor is not None:
        await store.attach_checkout(session_id, sponsor["id"], url=url, billing_email=target)
    if not url:
        return f"I could not send the payment email to {target}. Stripe has no payment link for this sponsorship yet."
    return await _mailed_payment_sentence(target, sponsor["company_name"] if sponsor else "this sponsorship", url)


async def sponsorship_status(store, prop: dict) -> str:
    """Read the stored listing. Do not invent a payment that Stripe has not recorded."""
    sponsor = await store.latest_sponsor(prop["id"])
    if sponsor is None:
        return (
            "I checked. This homestead does not have a sponsorship listing yet. "
            'Say "start sponsorship" when you want to begin.'
        )
    name = sponsor["company_name"]
    if sponsor.get("is_active_sponsor"):
        return f"I checked. {name} is an active g01 sponsor. Stripe has marked the payment paid."
    checkout = await store.latest_open_checkout(prop["id"])
    url = (checkout or {}).get("url")
    if url:
        return (
            f"I checked. {name} is filed, and Stripe has not marked the payment paid yet. "
            f"The payment link is {url}"
        )
    return f"I checked. {name} is filed as an inactive sponsor. Stripe has no paid invoice for it yet."
