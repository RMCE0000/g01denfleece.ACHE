"""Signed-in homesteaders and the private Chatwoot thread between two of them."""

import logging
import re
from uuid import uuid4

from app.chatwoot_client import ChatwootClient
from app.config import get_settings
from app.errors import G01Error

log = logging.getLogger(__name__)

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def login_url() -> str:
    return get_settings().chatwoot_public_url.rstrip("/") + "/app/login"


def conversation_url(conversation_id: int) -> str:
    settings = get_settings()
    base = settings.chatwoot_public_url.rstrip("/")
    return f"{base}/app/accounts/{int(settings.chatwoot_account_id)}/conversations/{int(conversation_id)}"


def _email(value: str) -> str:
    email = (value or "").strip().casefold()
    if not _EMAIL.fullmatch(email):
        raise G01Error("email is not usable", 422)
    return email


def _zip(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) < 5:
        raise G01Error("ZIP code is not one of the seeded localities", 422)
    return digits[:5]


def _require_api(client: ChatwootClient) -> None:
    if not client.configured():
        raise G01Error("Chatwoot API token is not configured", 503)


def _require_platform(client: ChatwootClient) -> None:
    _require_api(client)
    if not client.platform_configured():
        raise G01Error("Chatwoot platform token is not configured", 503)


async def _say(store, client: ChatwootClient, conversation_id: int | None, content: str) -> None:
    delivered = False
    if conversation_id is not None and client.configured():
        try:
            await client.post_message(int(conversation_id), content)
            delivered = True
        except Exception:
            log.exception("Chatwoot did not accept Jane's message on conversation %s", conversation_id)
    await store.add_outbox(int(conversation_id) if conversation_id is not None else None, content, delivered)


def _public_homesteader(prop: dict, *, existing: bool) -> dict:
    conversation_id = prop.get("primary_conversation_id")
    return {
        "name": prop.get("display_name"),
        "email": prop.get("email"),
        "property_id": prop["id"],
        "chatwoot_user_id": prop.get("chatwoot_user_id"),
        "chatwoot_contact_id": prop.get("chatwoot_contact_id"),
        "conversation_id": conversation_id,
        "inbox_id": prop.get("chatwoot_inbox_id"),
        "login_url": login_url(),
        "conversation_url": conversation_url(int(conversation_id)) if conversation_id else None,
        "existing": existing,
    }


async def register_homesteader(store, fields: dict) -> dict:
    """Public login-page signup. An email that already has a sign-in does not get a new session."""
    email = _email(fields.get("email") or "")
    if await store.get_property_by_email(email):
        raise G01Error("That email already has a sign-in.", 409)
    created = await provision_homesteader(store, fields, reject_existing_user=True)
    return {
        "name": created["name"],
        "email": created["email"],
        "login_url": created["login_url"],
        "conversation_url": created["conversation_url"],
        "sso_url": created.get("sso_url"),
    }


async def provision_homesteader(store, fields: dict, *, reject_existing_user: bool = False) -> dict:
    """Create a Chatwoot sign-in, a private Jane inbox, and the property row."""
    name = " ".join(str(fields.get("name") or "").split())
    if not name:
        raise G01Error("name is required", 422)
    email = _email(fields.get("email") or "")
    password = str(fields.get("password") or "")
    if len(password) < 8:
        raise G01Error("password must be at least 8 characters", 422)
    zip_code = _zip(fields.get("zip_code") or "")
    locality = await store.locality_for_zip(zip_code)
    if locality is None:
        raise G01Error(f"ZIP {zip_code} is outside every locality on the record", 422)

    existing = await store.get_property_by_email(email)
    if existing:
        result = _public_homesteader(existing, existing=True)
        client = ChatwootClient(get_settings())
        if client.platform_configured() and existing.get("chatwoot_user_id"):
            result["sso_url"] = await client.sso_link(int(existing["chatwoot_user_id"]))
        return result

    client = ChatwootClient(get_settings())
    _require_platform(client)
    settings = get_settings()
    nonce = uuid4().hex if reject_existing_user else None
    user = await client.create_platform_user(name, email, password, signup_nonce=nonce)
    if nonce and (user.get("custom_attributes") or {}).get("g01_signup") != nonce:
        raise G01Error("That email already has a sign-in.", 409)
    user_id = int(user["id"])
    await client.add_account_user(user_id, role="agent")
    opened = await client.open_agent_conversation(
        inbox_name=f"Jane — {name}"[:80],
        greeting="I'm Jane. This thread stays open.",
        contact_name=name,
        contact_email=email,
        user_ids=[user_id, settings.jane_user_id],
    )
    intro = (
        f"I'm Jane. This is your open homestead thread for {locality['name']} (ZIP {zip_code}). "
        "Ask me for scores, a local part, or another homesteader. The thread stays open."
    )
    await _say(store, client, opened["conversation_id"], intro)
    prop = await store.create_property(
        {
            "chatwoot_account_id": settings.chatwoot_account_id,
            "chatwoot_user_id": user_id,
            "chatwoot_contact_id": opened["contact_id"],
            "primary_conversation_id": opened["conversation_id"],
            "chatwoot_inbox_id": opened["inbox_id"],
            "locality_id": locality["id"],
            "zip_code": zip_code,
            "lat": locality["center_lat"],
            "lng": locality["center_lng"],
            "email": email,
            "display_name": name,
        }
    )
    result = _public_homesteader(prop, existing=False)
    result["sso_url"] = await client.sso_link(user_id)
    return result


async def resolve_homesteader(store, token: str) -> dict:
    raw = (token or "").strip()
    if not raw:
        raise G01Error("name the homesteader by email, Chatwoot user id, or property id", 422)
    if "@" in raw:
        found = await store.get_property_by_email(_email(raw))
    elif raw.isdigit():
        found = await store.get_property_by_user(int(raw))
    else:
        found = await store.get_property(raw)
    if found is None:
        raise G01Error("no homesteader matches that email, user id, or property id", 404)
    if not found.get("chatwoot_user_id"):
        raise G01Error(f"{found.get('display_name') or found.get('email') or 'that homesteader'} has no Chatwoot sign-in yet", 422)
    return found


async def open_peer_conversation(store, left: str, right: str, topic: str | None = None) -> dict:
    """Open a private inbox both homesteaders can use after they sign in."""
    peer_a = await resolve_homesteader(store, left)
    peer_b = await resolve_homesteader(store, right)
    if peer_a["id"] == peer_b["id"]:
        raise G01Error("choose two different homesteaders", 422)
    existing = await store.find_peer_between(peer_a["id"], peer_b["id"])
    if existing:
        return _peer_payload(peer_a, peer_b, existing, existing=True)

    client = ChatwootClient(get_settings())
    _require_api(client)
    settings = get_settings()
    name_a = peer_a.get("display_name") or peer_a.get("email") or "Homesteader"
    name_b = peer_b.get("display_name") or peer_b.get("email") or "Homesteader"
    inbox_name = f"{name_a} and {name_b}"[:80]
    opened = await client.open_agent_conversation(
        inbox_name=inbox_name,
        greeting="This homestead conversation stays open.",
        contact_name=inbox_name,
        contact_email=f"pair-{uuid4().hex[:12]}@example.com",
        user_ids=[peer_a["chatwoot_user_id"], peer_b["chatwoot_user_id"], settings.jane_user_id],
    )
    subject = f" about {topic.strip()}" if topic and topic.strip() else ""
    intro = (
        f"This conversation is {name_a} and {name_b}{subject}. "
        "I stay quiet unless you say my name. The thread stays open."
    )
    row = await store.remember_peer_conversation(
        opened["conversation_id"],
        peer_a["id"],
        peer_b["id"],
        inbox_id=opened["inbox_id"],
        topic=(topic or "").strip() or None,
    )
    await _say(store, client, opened["conversation_id"], intro)
    for speaker, other in ((peer_a, name_b), (peer_b, name_a)):
        if speaker.get("primary_conversation_id"):
            await _say(
                store,
                client,
                int(speaker["primary_conversation_id"]),
                f"I opened a conversation with {other}. In Chatwoot it is the inbox \"{inbox_name}\".",
            )
    return _peer_payload(peer_a, peer_b, row, existing=False)


def _peer_payload(peer_a: dict, peer_b: dict, row: dict, *, existing: bool) -> dict:
    def _side(prop: dict) -> dict:
        return {
            "name": prop.get("display_name"),
            "email": prop.get("email"),
            "property_id": prop["id"],
            "chatwoot_user_id": prop.get("chatwoot_user_id"),
        }

    return {
        "conversation_id": row["chatwoot_conversation_id"],
        "inbox_id": row.get("chatwoot_inbox_id"),
        "topic": row.get("topic"),
        "conversation_url": conversation_url(int(row["chatwoot_conversation_id"])),
        "login_url": login_url(),
        "left": _side(peer_a),
        "right": _side(peer_b),
        "existing": existing,
    }
