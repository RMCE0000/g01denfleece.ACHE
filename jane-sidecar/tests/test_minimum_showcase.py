"""The live webhook is the minimum showcase: constitution, history, and a local model."""

from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from app.config import get_settings
from app.constitution import JANE_CONSTITUTION
from app.local_model import UNREACHABLE, chat_messages, model_override
from app.main import create_app
from app.seed import DEMO_CONVERSATION_ID, DEMO_PROPERTY_ID, DEMO_USER_ID
from app.showcase import render_history
from app.worker import celery_app

ROOT = Path(__file__).resolve().parents[2]
CONVERSATION = DEMO_CONVERSATION_ID


def _message(content, message_id, **extra):
    sender = {"id": extra.get("sender_id", DEMO_USER_ID), "type": extra.get("sender_type", "user"), "name": extra.get("name")}
    return {
        "event": "message_created",
        "id": message_id,
        "content": content,
        "message_type": "outgoing",
        "private": False,
        "content_attributes": extra.get("attributes") or {},
        "sender": sender,
        "conversation": {
            "id": extra.get("conversation_id", CONVERSATION),
            "account_id": 1,
            "meta": {"sender": {"id": extra.get("contact_id", 101), "type": "contact"}},
        },
        "account": {"id": 1},
    }


def test_a_copied_speaker_label_is_not_posted():
    from app.showcase import reply_as_jane

    lines = [{"speaker": "Ada", "role": "homesteader", "content": "The cistern is empty."}]
    assert reply_as_jane("Ada: Make it on the homestead.\nMake it on the homestead.", lines) == "Make it on the homestead."
    assert reply_as_jane("I'm sorry, but I don't know how to answer.", lines) == (
        "I do not know enough from this history yet. "
        "What containers, materials, or tools do you already have on the homestead that could help?"
    )


def test_local_model_receives_real_chat_roles():
    lines = [
        {"speaker": "Jane", "role": "jane", "content": "Tell me what the place needs."},
        {"speaker": "Ada", "role": "homesteader", "content": "The cistern is empty."},
    ]
    assert chat_messages("constitution", render_history(lines), lines) == [
        {"role": "system", "content": "constitution"},
        {"role": "assistant", "content": "Jane: Tell me what the place needs."},
        {"role": "user", "content": "Ada: The cistern is empty."},
    ]


def test_prompt_is_the_constitution_and_the_history(client, store):
    seen = {"prompts": []}

    def fake(system, user):
        seen["system"] = system
        seen["prompts"].append(user)
        return "Make the cistern on the homestead."

    before = store.properties[0]["northstar_automated_pct"]
    token = model_override.set(fake)
    try:
        first = client.post("/webhooks/chatwoot", json=_message("The cistern is empty.", 1, name="Ada"))
        second = client.post("/webhooks/chatwoot", json=_message("Where do I get a liner?", 2, name="Ada"))
    finally:
        model_override.reset(token)
    assert first.status_code == 200
    assert first.json()["reply"] == "Make the cistern on the homestead."
    assert seen["system"] == JANE_CONSTITUTION
    assert seen["prompts"][0] == "Ada: The cistern is empty."
    assert "tier_weight" not in seen["system"]
    assert "known_facts_ledger" not in seen["system"]
    assert second.json()["reply"] == "Make the cistern on the homestead."
    assert seen["prompts"][1] == "\n".join(
        [
            "Ada: The cistern is empty.",
            "Jane: Make the cistern on the homestead.",
            "Ada: Where do I get a liner?",
        ]
    )
    assert store.properties[0]["northstar_automated_pct"] == before
    assert store.properties[0]["id"] == DEMO_PROPERTY_ID

    token = model_override.set(lambda _system, _user: "Buy it at https://www.amazon.com/dp/example today.")
    try:
        retail = client.post("/webhooks/chatwoot", json=_message("A liner, please.", 4, name="Ada"))
    finally:
        model_override.reset(token)
    assert "amazon" not in retail.json()["reply"].casefold()

    duplicate = client.post("/webhooks/chatwoot", json=_message("The cistern is empty.", 1, name="Ada"))
    assert duplicate.json()["duplicate"] is True
    assert len([row for row in store.transcript if row["message_id"] == "1"]) == 1


def test_a_connection_stays_quiet_until_someone_says_jane(client, store):
    calls = []
    token = model_override.set(lambda _system, user: calls.append(user) or "The homestead can make that.")
    try:
        import asyncio

        asyncio.run(
            store.remember_peer_conversation(
                900,
                store.properties[0]["id"],
                store.properties[1]["id"],
                inbox_id=9,
                topic="the well",
            )
        )
        quiet = client.post(
            "/webhooks/chatwoot",
            json=_message("The cistern is full.", 10, name="Ada", conversation_id=900),
        )
        named = client.post(
            "/webhooks/chatwoot",
            json=_message("Jane, the cistern is full.", 11, name="Ada", conversation_id=900),
        )
    finally:
        model_override.reset(token)
    assert quiet.json()["ignored"] == "peer"
    assert named.json()["reply"] == "The homestead can make that."
    assert len(calls) == 1
    assert "Jane, the cistern is full." in calls[0]
    assert any(row["content"] == "The cistern is full." for row in store.transcript)


def test_a_missing_local_model_is_said_out_loud(client, monkeypatch):
    class Down:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, *args, **kwargs):
            raise httpx.ConnectError("down")

    monkeypatch.setattr("app.local_model.httpx.AsyncClient", Down)
    token = model_override.set(None)
    try:
        response = client.post("/webhooks/chatwoot", json=_message("Hello Jane.", 20, name="Ada"))
    finally:
        model_override.reset(token)
    assert response.status_code == 200
    assert response.json()["reply"] == UNREACHABLE


def test_the_backend_lists_every_conversation(store, monkeypatch):
    monkeypatch.setenv("G01_ADMIN_TOKEN", "secret-admin")
    get_settings.cache_clear()
    store.properties[0]["email"] = "ada.yard@example.com"
    store.properties[0]["display_name"] = "Ada Yard"
    store.properties[1]["email"] = "bea.chenier@example.com"
    store.properties[1]["display_name"] = "Bea Chenier"
    with TestClient(create_app(store)) as gated:
        denied = gated.get("/api/admin/conversations")
        assert denied.status_code == 401
        gated.post("/webhooks/chatwoot", json=_message("The cistern is empty.", 30, name="Ada Yard"))
        import asyncio

        asyncio.run(
            store.remember_peer_conversation(
                900,
                store.properties[0]["id"],
                store.properties[1]["id"],
                inbox_id=9,
                topic="the well",
            )
        )
        gated.post(
            "/webhooks/chatwoot",
            json=_message("We should share the well.", 31, name="Ada Yard", conversation_id=900),
        )
        listed = gated.get("/api/admin/conversations", headers={"x-g01-admin-token": "secret-admin"})
        health = gated.get("/health")
    assert listed.status_code == 200
    body = listed.json()
    assert body["showcase"] == "minimum"
    by_id = {row["conversation_id"]: row for row in body["conversations"]}
    jane = by_id[CONVERSATION]
    assert jane["kind"] == "jane"
    assert jane["people"][0]["email"] == "ada.yard@example.com"
    assert any(line["content"] == "The cistern is empty." for line in jane["messages"])
    assert any(line["role"] == "jane" for line in jane["messages"])
    connection = by_id[900]
    assert connection["kind"] == "connection"
    assert connection["topic"] == "the well"
    assert {person["email"] for person in connection["people"]} == {"ada.yard@example.com", "bea.chenier@example.com"}
    assert any(line["content"] == "We should share the well." for line in connection["messages"])
    assert all(line["role"] != "jane" for line in connection["messages"])
    assert health.json()["showcase"] == "minimum"


def test_background_jobs_stay_off():
    assert celery_app.conf.beat_schedule == {}
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert 'profiles: ["background"]' in compose
    assert compose.count('profiles: ["background"]') == 2
    assert "ollama/ollama@sha256:" in compose
    assert "G01_BACKGROUND_JOBS: \"0\"" in compose
    assert "qwen2.5:1.5b" in compose
    assert "qwen2.5:0.5b" not in compose
