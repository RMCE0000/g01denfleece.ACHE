"""Minimum showcase. A prompt is the constitution plus the message history."""

import json
import logging

from app.chatwoot_client import ChatwootClient
from app.config import get_settings
from app.constitution import JANE_CONSTITUTION
from app.delivery import deliver
from app.effects import commit_decision
from app.gemini_flow import complete_text
from app.homesteaders import conversation_url
from app.heuristic import heuristic_decision
from app.northstar import view_from_property
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


def _grounded_system(prop: dict | None, locality: dict | None) -> str:
    if prop is None:
        return JANE_CONSTITUTION
    record = {
        "homesteader": prop.get("display_name"),
        "locality": locality.get("name") if locality else None,
        "known_facts": prop.get("known_facts_ledger") or {},
        "north_star": view_from_property(prop).get("northstar"),
    }
    return (
        JANE_CONSTITUTION
        + "\nCURRENT VERIFIED HOMESTEAD RECORD\n"
        + json.dumps(record, ensure_ascii=True, separators=(",", ":"), default=str)
        + "\nUse this record instead of asking again for facts already present. "
        "Answer the latest request directly before asking at most one useful follow-up question."
    )


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


def _merge_remote_and_local_history(remote: list[dict], local: list[dict]) -> list[dict]:
    """Keep local-only transcripts, including audio, beside Chatwoot history."""
    if not remote:
        return local
    merged = list(remote)
    known = {str(line.get("message_id") or "") for line in remote}
    for line in local:
        message_id = str(line.get("message_id") or "")
        if message_id and message_id not in known:
            merged.append(line)
            known.add(message_id)

    def message_order(line: dict) -> tuple[int, int]:
        value = str(line.get("message_id") or "")
        return (0, int(value)) if value.isdigit() else (1, 0)

    return sorted(merged, key=message_order)


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
    remote = await remote_history(conversation_id)
    local = await store.list_transcript(conversation_id)
    lines = _merge_remote_and_local_history(remote, local)
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


async def answer_with_effects(store, message: dict) -> str:
    """Keep the history-aware Gemini reply while applying grounded product workflows."""
    lines = await history_for(store, message)
    prop = await store.get_property_by_conversation(int(message["conversation_id"]))
    if prop is None and message.get("contact_id") is not None:
        prop = await store.get_property_by_contact(int(message["contact_id"]))
    if prop is None and message.get("user_id") is not None:
        prop = await store.get_property_by_user(int(message["user_id"]))
    locality = await store.get_locality(prop["locality_id"]) if prop else None
    reply = reply_as_jane(
        await complete_text(_grounded_system(prop, locality), render_history(lines), lines),
        lines,
    )
    cleaned = sanitize_reply(reply).strip() or _BLOCKED
    decision = heuristic_decision(
        {
            "message": message,
            "property": prop,
            "locality": locality,
            "invites": await store.open_invites_for_property(prop["id"]) if prop else [],
            "matches": await store.matches_for_property(prop["id"]) if prop else [],
        }
    )
    effect_keys = (
        "ledger_patch", "outside_aid_hours_per_week", "aesthetic_pct",
        "material_independent", "material_surplus_profitable", "energetic_pct",
        "energetic_profitable", "contained_zero_waste", "service_tag",
        "start_poll", "vote_poll_id", "match_id", "sponsor_active",
        "cancel_sponsor", "report_scores", "request_kyc", "street_address",
        "property_lat", "property_lng",
    )
    has_grounded_effect = any(decision.get(key) for key in effect_keys)
    if not has_grounded_effect:
        decision["reply"] = cleaned
    await store.append_transcript(
        conversation_id=int(message["conversation_id"]),
        message_id=str(message.get("message_id") or "") or None,
        role="homesteader",
        speaker=message.get("speaker") or "Homesteader",
        content=str(message.get("content") or ""),
    )
    return await commit_decision(store, message, decision, prop, locality)


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
        remote = await remote_history(row["conversation_id"])
        local = await store.list_transcript(row["conversation_id"])
        messages = _merge_remote_and_local_history(remote, local)
        row["messages"] = _public_messages(messages)
        conversations.append(row)
    return {
        "showcase": "minimum",
        "conversations": conversations,
    }
