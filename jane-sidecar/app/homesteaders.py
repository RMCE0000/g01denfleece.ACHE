"""Signed-in homesteaders and the private g01 thread between two of them."""

import asyncio
import logging
import re
from uuid import UUID, uuid4

import httpx
from sqlalchemy.exc import IntegrityError

from app.chatwoot_client import ChatwootClient
from app.config import get_settings
from app.errors import G01Error

log = logging.getLogger(__name__)

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_USERNAME = re.compile(r"^[a-z][a-z0-9._-]{2,31}$")
_PASSWORD_SPECIALS = set("!@#$%^&*()_+-=[]{}|'\"/\\.,`<>:;?~")
_PASSWORD_HELP = (
    "Password must be at least 8 characters and include uppercase, lowercase, "
    "a number, and a special character."
)
_PASSWORD_LENGTH = "Password must be 72 characters or fewer."
_UNSTORABLE = "contains a character that cannot be stored."
# g01 stores passwords with bcrypt, which rejects secrets longer than 72 bytes
# or containing a null with an unhandled exception. That reached the browser as a plain error 500.
_PEER_LOCKS: dict[tuple[str, str], asyncio.Lock] = {}


def login_url() -> str:
    return get_settings().chatwoot_public_url.rstrip("/") + "/app/login"


def conversation_url(conversation_id: int) -> str:
    settings = get_settings()
    base = settings.chatwoot_public_url.rstrip("/")
    return f"{base}/app/accounts/{int(settings.chatwoot_account_id)}/conversations/{int(conversation_id)}"


def _unstorable(value: str) -> bool:
    return any(ord(char) < 32 or ord(char) == 127 for char in value)


def _email(value: str) -> str:
    email = (value or "").strip().casefold()
    if _unstorable(email) or not _EMAIL.fullmatch(email):
        raise G01Error("email is not usable", 422)
    return email


def _zip(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) < 5:
        raise G01Error("ZIP code is not one of the seeded localities", 422)
    return digits[:5]


def _password(value: str) -> str:
    password = str(value or "")
    if _unstorable(password):
        raise G01Error(f"Password {_UNSTORABLE}", 422)
    if len(password) > 72 or len(password.encode("utf-8")) > 72:
        raise G01Error(_PASSWORD_LENGTH, 422)
    if not (
        len(password) >= 8
        and any(char.isupper() for char in password)
        and any(char.islower() for char in password)
        and any(char.isdigit() for char in password)
        and any(char in _PASSWORD_SPECIALS for char in password)
    ):
        raise G01Error(_PASSWORD_HELP, 422)
    return password


def _signup_failure(exc: BaseException) -> str:
    orig = getattr(exc, "orig", None)
    detail = " ".join(str(orig or exc).split())
    detail = detail.split("[SQL", 1)[0].strip()[:240]
    if not detail:
        detail = exc.__class__.__name__
    return f"Account was not created. {detail}"


def _username(value: str | None, email: str) -> str:
    username = (value or "").strip().casefold().removeprefix("@")
    if _unstorable(username):
        raise G01Error(f"Username {_UNSTORABLE}", 422)
    if not username:
        username = re.sub(r"[^a-z0-9._-]", "-", email.split("@", 1)[0].casefold())
    if not _USERNAME.fullmatch(username):
        raise G01Error("username must start with a letter and use 3–32 lowercase letters, numbers, dots, dashes, or underscores", 422)
    return username


def _require_api(client: ChatwootClient) -> None:
    if not client.configured():
        raise G01Error("g01 API token is not configured", 503)


def _require_platform(client: ChatwootClient) -> None:
    _require_api(client)
    if not client.platform_configured():
        raise G01Error("g01 platform token is not configured", 503)


async def _say(store, client: ChatwootClient, conversation_id: int | None, content: str) -> None:
    delivered = False
    if conversation_id is not None and client.configured():
        try:
            await client.post_message(int(conversation_id), content)
            delivered = True
        except Exception:
            log.exception("g01 did not accept Jane's message on conversation %s", conversation_id)
    await store.add_outbox(int(conversation_id) if conversation_id is not None else None, content, delivered)
    if conversation_id is not None:
        await store.append_transcript(
            conversation_id=int(conversation_id),
            message_id=None,
            role="jane",
            speaker="Jane",
            content=content,
        )


async def _sync_homesteader_metadata(client: ChatwootClient, prop: dict, locality: dict) -> None:
    """Mirror safe, filterable g01 context into ordinary g01 surfaces."""
    try:
        await client.set_contact_labels(int(prop["chatwoot_contact_id"]), ["g01-homesteader"])
        await client.update_contact_custom_attributes(
            int(prop["chatwoot_contact_id"]),
            {
                "g01_member": True,
                "g01_locality": locality.get("name") or "",
            },
        )
        await client.set_conversation_labels(
            int(prop["primary_conversation_id"]),
            ["g01-homestead", "g01-jane"],
        )
        await client.update_conversation_custom_attributes(
            int(prop["primary_conversation_id"]),
            {
                "g01_kind": "jane",
                "g01_property_id": str(prop["id"]),
                "g01_locality": locality.get("name") or "",
            },
        )
    except Exception:
        # The g01 conversation is still usable if metadata synchronization
        # fails; a later bootstrap or operator run can repair labels.
        log.exception("g01 metadata did not synchronize for property %s", prop.get("id"))


async def _sync_peer_metadata(client: ChatwootClient, row: dict, peer_a: dict, peer_b: dict) -> None:
    try:
        conversation_id = int(row["chatwoot_conversation_id"])
        await client.set_conversation_labels(conversation_id, ["g01-homestead", "g01-connection"])
        await client.update_conversation_custom_attributes(
            conversation_id,
            {
                "g01_kind": "connection",
                "g01_topic": row.get("topic") or "",
                "g01_property_a_id": str(peer_a["id"]),
                "g01_property_b_id": str(peer_b["id"]),
            },
        )
    except Exception:
        log.exception("g01 metadata did not synchronize for peer conversation %s", row.get("chatwoot_conversation_id"))


async def sync_workspace_metadata(store) -> None:
    """Backfill native g01 labels and attributes for existing records."""
    client = ChatwootClient(get_settings())
    if not client.configured():
        return
    properties = await store.list_properties()
    by_id = {str(prop["id"]): prop for prop in properties}
    localities = {str(row["id"]): row for row in await store.list_localities()}
    for prop in properties:
        if prop.get("chatwoot_contact_id") and prop.get("primary_conversation_id"):
            await _sync_homesteader_metadata(client, prop, localities.get(str(prop.get("locality_id")), {}))
    for row in await store.list_peer_conversations():
        peer_a = by_id.get(str(row.get("property_a_id")))
        peer_b = by_id.get(str(row.get("property_b_id")))
        if peer_a and peer_b:
            await _sync_peer_metadata(client, row, peer_a, peer_b)


def _public_homesteader(prop: dict, *, existing: bool) -> dict:
    conversation_id = prop.get("primary_conversation_id")
    return {
        "name": prop.get("display_name"),
        "email": prop.get("email"),
        "username": prop.get("username"),
        "property_id": prop["id"],
        "chatwoot_user_id": prop.get("chatwoot_user_id"),
        "chatwoot_contact_id": prop.get("chatwoot_contact_id"),
        "conversation_id": conversation_id,
        "inbox_id": prop.get("chatwoot_inbox_id"),
        "login_url": login_url(),
        "conversation_url": conversation_url(int(conversation_id)) if conversation_id else None,
        "existing": existing,
    }


def _platform_user_was_created(user: dict, nonce: str) -> bool:
    """Accept a new user or resume a g01-created user left unattached by an older failed signup."""
    attributes = user.get("custom_attributes")
    if isinstance(attributes, dict):
        if attributes.get("g01_signup") == nonce:
            return True
        # Earlier g01 code could create the platform user and then reject the
        # response before adding an account. Only resume that identifiable,
        # account-less g01 user; never claim an ordinary g01 user.
        return (
            attributes.get("g01") is True
            and user.get("account_id") is None
            and user.get("accounts") == []
        )
    # A just-created platform user has not been attached to an account yet.
    # Older g01 serializers omit custom_attributes, but still expose the
    # empty account list. Existing users already attached to g01 do not.
    accounts = user.get("accounts")
    return user.get("account_id") is None and isinstance(accounts, list) and not accounts


async def register_homesteader(store, fields: dict) -> dict:
    """Public login-page signup. An email that already has a sign-in does not get a new session."""
    email = _email(fields.get("email") or "")
    try:
        if await store.get_property_by_email(email):
            raise G01Error("That email already has a sign-in.", 409)
        created = await provision_homesteader(store, fields, reject_existing_user=True)
    except G01Error:
        raise
    except httpx.HTTPError as exc:
        log.warning("signup could not reach g01: %s", exc.__class__.__name__)
        raise G01Error("g01 could not be reached. Try again.", 503) from exc
    except IntegrityError as exc:
        raise G01Error("That email or username is already in use.", 409) from exc
    except Exception as exc:
        # The login form can only show a JSON detail. An unhandled exception
        # becomes a plain "Internal Server Error", which is the error 500 people saw.
        log.exception("signup failed")
        raise G01Error(_signup_failure(exc), 500) from exc
    return {
        "name": created["name"],
        "email": created["email"],
        "username": created["username"],
        "login_url": created["login_url"],
        "conversation_url": created["conversation_url"],
        "sso_url": created.get("sso_url"),
    }


async def provision_homesteader(store, fields: dict, *, reject_existing_user: bool = False) -> dict:
    """Create a g01 sign-in, a private Jane inbox, and the property row."""
    name = " ".join(str(fields.get("name") or "").split())
    if not name:
        raise G01Error("name is required", 422)
    if _unstorable(name):
        raise G01Error(f"Name {_UNSTORABLE}", 422)
    email = _email(fields.get("email") or "")
    username = _username(fields.get("username"), email)
    password = _password(fields.get("password") or "")
    zip_code = _zip(fields.get("zip_code") or "")
    locality = await store.locality_for_zip(zip_code)
    if locality is None:
        raise G01Error(f"ZIP {zip_code} is outside every locality on the record", 422)
    try:
        lat = float(locality["center_lat"])
        lng = float(locality["center_lng"])
    except (KeyError, TypeError, ValueError):
        raise G01Error("That locality is missing a map point, so the account was not created.", 422) from None

    existing = await store.get_property_by_email(email)
    if existing:
        result = _public_homesteader(existing, existing=True)
        client = ChatwootClient(get_settings())
        if client.platform_configured() and existing.get("chatwoot_user_id"):
            result["sso_url"] = await client.sso_link(int(existing["chatwoot_user_id"]))
        return result
    if await store.get_property_by_username(username):
        raise G01Error("That username is already in use.", 409)

    client = ChatwootClient(get_settings())
    _require_platform(client)
    settings = get_settings()
    nonce = uuid4().hex if reject_existing_user else None
    user = await client.create_platform_user(name, email, password, signup_nonce=nonce)
    if not isinstance(user, dict):
        raise G01Error("g01 did not return the new sign-in.", 502)
    try:
        user_id = int(user["id"])
    except (KeyError, TypeError, ValueError):
        raise G01Error("g01 did not return the new sign-in.", 502) from None
    if nonce and not _platform_user_was_created(user, nonce):
        raise G01Error("That email already has a sign-in.", 409)
    await client.add_account_user(user_id, role="agent")
    opened = await client.open_agent_conversation(
        inbox_name=f"Jane — {name}"[:80],
        greeting="I'm Jane, the homestead analyst and coordinator. This thread stays open.",
        contact_name=name,
        contact_email=email,
        user_ids=[user_id, settings.jane_user_id],
    )
    if not isinstance(opened, dict) or any(opened.get(key) is None for key in ("inbox_id", "contact_id", "conversation_id")):
        raise G01Error("g01 did not open the homestead thread.", 502)
    intro = (
        f"I'm Jane, the homestead analyst and coordinator. This is your open homestead thread for {locality['name']} (ZIP {zip_code}). "
        "Tell me what the place needs. The thread stays open."
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
            "lat": lat,
            "lng": lng,
            "email": email,
            "display_name": name,
            "username": username,
        }
    )
    await _sync_homesteader_metadata(client, prop, locality)
    result = _public_homesteader(prop, existing=False)
    result["sso_url"] = await client.sso_link(user_id)
    return result


async def resolve_homesteader(store, token: str) -> dict:
    raw = (token or "").strip()
    if not raw:
        raise G01Error("name the homesteader by email, g01 user id, or property id", 422)
    if "@" in raw:
        found = await store.get_property_by_username(raw) if raw.startswith("@") else await store.get_property_by_email(_email(raw))
    elif raw.isdigit():
        found = await store.get_property_by_user(int(raw))
    else:
        found = await store.get_property_by_username(raw)
        if found is None:
            try:
                UUID(raw)
            except ValueError:
                found = None
            else:
                found = await store.get_property(raw)
    if found is None:
        raise G01Error("no homesteader matches that email, user id, or property id", 404)
    if not found.get("chatwoot_user_id"):
        raise G01Error(f"{found.get('display_name') or found.get('email') or 'that homesteader'} has no g01 sign-in yet", 422)
    return found


async def open_peer_conversation(store, left: str, right: str, topic: str | None = None) -> dict:
    """Open a private inbox both homesteaders can use after they sign in."""
    peer_a = await resolve_homesteader(store, left)
    peer_b = await resolve_homesteader(store, right)
    if peer_a["id"] == peer_b["id"]:
        raise G01Error("choose two different homesteaders", 422)
    pair = tuple(sorted((str(peer_a["id"]), str(peer_b["id"]))))
    lock = _PEER_LOCKS.setdefault(pair, asyncio.Lock())
    async with lock:
        return await _open_peer_conversation(store, peer_a, peer_b, topic)


async def _open_peer_conversation(store, peer_a: dict, peer_b: dict, topic: str | None = None) -> dict:
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
    await _sync_peer_metadata(client, row, peer_a, peer_b)
    await _say(store, client, opened["conversation_id"], intro)
    for speaker, other in ((peer_a, name_b), (peer_b, name_a)):
        if speaker.get("primary_conversation_id"):
            await _say(
                store,
                client,
                int(speaker["primary_conversation_id"]),
                f"I opened a conversation with {other}. In g01 it is the inbox \"{inbox_name}\".",
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
