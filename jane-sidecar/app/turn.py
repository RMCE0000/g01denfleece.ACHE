"""Chatwoot message_created intake. Jane's own posts are ignored so the webhook cannot loop."""

import re

from app.config import get_settings
from app.graphs.sync_peer_graph import build_sync_peer_graph
from app.runtime import set_store


def extract_message(payload: dict) -> dict:
    conversation = payload.get("conversation") or {}
    sender = payload.get("sender") or {}
    meta_sender = ((conversation.get("meta") or {}).get("sender") or {}) if isinstance(conversation, dict) else {}
    sender_type = str(sender.get("type") or "")
    contact_id = sender.get("id") if sender_type.lower() == "contact" else meta_sender.get("id")
    user_id = sender.get("id") if sender_type.lower() == "user" else None
    return {
        "event": payload.get("event"),
        "message_id": payload.get("id"),
        "content": payload.get("content") or "",
        "message_type": payload.get("message_type"),
        "private": bool(payload.get("private")),
        "sender_type": sender.get("type"),
        "sender_id": sender.get("id"),
        "account_id": (payload.get("account") or {}).get("id") or conversation.get("account_id"),
        "conversation_id": conversation.get("id") if isinstance(conversation, dict) else None,
        "contact_id": contact_id,
        "user_id": user_id,
        "content_attributes": payload.get("content_attributes") or {},
    }


_MENTIONS_JANE = re.compile(r"\bjane\b", re.I)


def ignore_reason(message: dict) -> str | None:
    if message.get("event") != "message_created":
        return "event"
    if message.get("private"):
        return "private"
    if message.get("message_type") in (2, "activity", "template"):
        return "activity"
    attributes = message.get("content_attributes") or {}
    if attributes.get("g01_author") == "jane":
        return "jane"
    sender_type = str(message.get("sender_type") or "")
    if sender_type.lower() in ("agent_bot", "agentbot"):
        return "jane"
    settings = get_settings()
    if sender_type.lower() == "user" and message.get("sender_id") is not None and int(message["sender_id"]) == int(settings.jane_user_id):
        return "jane"
    if not str(message.get("content") or "").strip():
        return "empty"
    return None


async def run_turn(store, payload: dict) -> dict:
    set_store(store)
    message = extract_message(payload)
    reason = ignore_reason(message)
    if reason:
        return {"ok": True, "ignored": reason}
    conversation_id = message.get("conversation_id")
    if conversation_id is not None and await store.is_peer_conversation(int(conversation_id)):
        if not _MENTIONS_JANE.search(message.get("content") or ""):
            return {"ok": True, "ignored": "peer"}
    event_id = f"cw:{message.get('message_id')}:{message.get('conversation_id')}"
    message["event_id"] = event_id
    if not await store.mark_event(event_id):
        return {"ok": True, "duplicate": True}
    try:
        graph = build_sync_peer_graph()
        result = await graph.ainvoke({"message": message})
    except Exception:
        await store.unmark_event(event_id)
        raise
    return {"ok": True, "reply": result.get("reply", "")}
