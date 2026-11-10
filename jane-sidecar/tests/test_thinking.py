"""Jane's thread shows a thinking signal only while she is going to answer."""

import asyncio

from app.chatwoot_client import ChatwootClient
from app.seed import DEMO_CONVERSATION_ID, DEMO_USER_ID
from app.thinking import PULSE_SECONDS, start_thinking, stop_thinking


def _message(content, message_id, **extra):
    return {
        "event": "message_created",
        "id": message_id,
        "content": content,
        "message_type": "outgoing",
        "private": False,
        "content_attributes": {},
        "sender": {"id": extra.get("sender_id", DEMO_USER_ID), "type": "user", "name": "Ada"},
        "conversation": {
            "id": extra.get("conversation_id", DEMO_CONVERSATION_ID),
            "account_id": 1,
            "meta": {"sender": {"id": 101, "type": "contact"}},
        },
        "account": {"id": 1},
    }


def test_jane_thinks_until_the_reply_is_ready(client, monkeypatch):
    calls = []

    async def set_typing(self, conversation_id, active):
        calls.append((int(conversation_id), bool(active)))

    monkeypatch.setattr(ChatwootClient, "set_typing", set_typing)
    response = client.post("/webhooks/chatwoot", json=_message("Where do I get a liner?", 701))

    assert response.status_code == 200
    assert calls[0] == (DEMO_CONVERSATION_ID, True)
    assert calls[-1] == (DEMO_CONVERSATION_ID, False)


def test_a_quiet_peer_message_does_not_show_thinking(client, store, monkeypatch):
    calls = []

    async def set_typing(self, conversation_id, active):
        calls.append((int(conversation_id), bool(active)))

    monkeypatch.setattr(ChatwootClient, "set_typing", set_typing)
    asyncio.run(
        store.remember_peer_conversation(
            900,
            store.properties[0]["id"],
            store.properties[1]["id"],
            inbox_id=9,
            topic="the well",
        )
    )
    quiet = client.post("/webhooks/chatwoot", json=_message("The cistern is full.", 702, conversation_id=900))
    assert quiet.json()["ignored"] == "peer"
    assert calls == []

    named = client.post("/webhooks/chatwoot", json=_message("Jane, the cistern is full.", 703, conversation_id=900))
    assert named.status_code == 200
    assert calls[0] == (900, True)
    assert calls[-1] == (900, False)


def test_thinking_stays_on_past_chatwoots_timeout(monkeypatch):
    import app.thinking as thinking

    calls = []

    async def set_typing(self, conversation_id, active):
        calls.append(bool(active))

    monkeypatch.setattr(ChatwootClient, "set_typing", set_typing)
    monkeypatch.setattr(thinking, "PULSE_SECONDS", 0.05)

    async def run():
        await start_thinking(42)
        await asyncio.sleep(0.12)
        await stop_thinking(42)

    asyncio.run(run())
    assert calls[0] is True
    assert calls.count(True) >= 2
    assert calls[-1] is False
    assert PULSE_SECONDS == 20
