"""Minimum showcase. A prompt is the constitution plus the message history."""

import logging

from app.chatwoot_client import ChatwootClient
from app.config import get_settings
from app.constitution import JANE_CONSTITUTION
from app.delivery import deliver
from app.homesteaders import conversation_url
from app.local_model import complete_text
from app.sanitize import sanitize_reply

log = logging.getLogger(__name__)

_HISTORY_LIMIT = 40
_BLOCKED = "I won't name a national store. Make it on the homestead, or find it in your own locality."
_GROUNDED_QUESTION = (
    "I do not know enough from this history yet. "
    "What containers, materials, or tools do you already have on the homestead that could help?"
)
_GENERIC_NON_ANSWERS = {
    "i don't know how to answer",
    "i don't know how to answer.",
    "i do not know how to answer",
    "i do not know how to answer.",
    "i'm sorry, but i don't know how to answer",
    "i'm sorry, but i don't know how to answer.",
}


def _collapse_repeats(text: str) -> str:
    kept: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and kept and stripped == kept[-1].strip():
            continue
        kept.append(line.rstrip())
    return "\n".join(kept).strip()


def reply_as_jane(text: str, lines: list[dict]) -> str:
    """Drop a copied speaker label and a line the model repeated back to itself."""
    cleaned = str(text or "").strip()
    for line in lines:
        speaker = str(line.get("speaker") or "").strip()
        prefix = f"{speaker}:"
        if speaker and cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip()
            break
    cleaned = _collapse_repeats(cleaned)
    if cleaned.casefold() in _GENERIC_NON_ANSWERS:
        return _GROUNDED_QUESTION
    return cleaned


def render_history(lines: list[dict]) -> str:
    parts: list[str] = []
    for line in lines:
        content = str(line.get("content") or "").strip()
        if not content:
            continue
        speaker = str(line.get("speaker") or "").strip()
        if not speaker:
            speaker = "Jane" if line.get("role") == "jane" else "Homesteader"
        parts.append(f"{speaker}: {content}")
    return "\n".join(parts)


def _incoming_line(message: dict) -> dict:
    return {
        "conversation_id": int(message["conversation_id"]),
        "message_id": str(message.get("message_id") or ""),
        "role": "homesteader",
        "speaker": message.get("speaker") or "Homesteader",
        "content": message.get("content") or "",
    }


def _same_message(line: dict, message: dict) -> bool:
    left = str(line.get("message_id") or "")
    right = str(message.get("message_id") or "")
    return bool(left and right and left == right)


async def remote_history(conversation_id: int) -> list[dict]:
    client = ChatwootClient(get_settings())
    if not client.configured():
        return []
    try:
        return await client.list_messages(int(conversation_id))
    except Exception:
        log.exception("Chatwoot did not return messages for conversation %s", conversation_id)
        return []


async def history_for(store, message: dict) -> list[dict]:
    conversation_id = int(message["conversation_id"])
    lines = await remote_history(conversation_id)
    if not lines:
        lines = await store.list_transcript(conversation_id)
    if not any(_same_message(line, message) for line in lines):
        lines = [*lines, _incoming_line(message)]
    return lines[-_HISTORY_LIMIT:]


async def answer(store, message: dict) -> str:
    """Prompt Jane with the constitution and the history, then post her reply."""
    lines = await history_for(store, message)
    reply = reply_as_jane(await complete_text(JANE_CONSTITUTION, render_history(lines), lines), lines)
    cleaned = sanitize_reply(reply).strip() or _BLOCKED
    await store.append_transcript(
        conversation_id=int(message["conversation_id"]),
        message_id=str(message.get("message_id") or "") or None,
        role="homesteader",
        speaker=message.get("speaker") or "Homesteader",
        content=str(message.get("content") or ""),
    )
    await deliver(store, int(message["conversation_id"]), cleaned)
    return cleaned


def _person(prop: dict) -> dict:
    return {
        "name": prop.get("display_name"),
        "email": prop.get("email"),
        "property_id": prop.get("id"),
        "chatwoot_user_id": prop.get("chatwoot_user_id"),
    }


def _public_messages(lines: list[dict]) -> list[dict]:
    visible = []
    for line in lines[-_HISTORY_LIMIT:]:
        content = str(line.get("content") or "").strip()
        if not content:
            continue
        visible.append(
            {
                "speaker": line.get("speaker") or ("Jane" if line.get("role") == "jane" else "Homesteader"),
                "role": line.get("role"),
                "content": content,
            }
        )
    return visible


async def list_conversations(store) -> dict:
    """Every thread Jane knows, so a connection can be opened between two of them."""
    properties = await store.list_properties()
    peers = await store.list_peer_conversations()
    by_property = {str(prop["id"]): prop for prop in properties}
    found: dict[int, dict] = {}
    for prop in properties:
        conversation_id = prop.get("primary_conversation_id")
        if conversation_id is None:
            continue
        found[int(conversation_id)] = {
            "conversation_id": int(conversation_id),
            "kind": "jane",
            "inbox_id": prop.get("chatwoot_inbox_id"),
            "topic": None,
            "people": [_person(prop)],
            "url": conversation_url(int(conversation_id)),
        }
    for peer in peers:
        conversation_id = int(peer["chatwoot_conversation_id"])
        people = []
        for key in ("property_a_id", "property_b_id"):
            prop = by_property.get(str(peer.get(key)))
            if prop:
                people.append(_person(prop))
        found[conversation_id] = {
            "conversation_id": conversation_id,
            "kind": "connection",
            "inbox_id": peer.get("chatwoot_inbox_id"),
            "topic": peer.get("topic"),
            "people": people,
            "url": conversation_url(conversation_id),
        }
    for conversation_id in await store.transcript_conversation_ids():
        found.setdefault(
            int(conversation_id),
            {
                "conversation_id": int(conversation_id),
                "kind": "chat",
                "inbox_id": None,
                "topic": None,
                "people": [],
                "url": conversation_url(int(conversation_id)),
            },
        )
    conversations = []
    for row in sorted(found.values(), key=lambda item: item["conversation_id"]):
        messages = await remote_history(row["conversation_id"])
        if not messages:
            messages = await store.list_transcript(row["conversation_id"])
        row["messages"] = _public_messages(messages)
        conversations.append(row)
    return {
        "showcase": "minimum",
        "conversations": conversations,
    }
