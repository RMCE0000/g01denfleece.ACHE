"""The live webhook is Jane's constitution, history, and routed Gemini flow."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import get_settings
from app.constitution import JANE_CONSTITUTION
from app.gemini_flow import UNREACHABLE, chat_messages, complete_text, gemini_override, task_complexity
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


def test_a_thought_label_is_not_posted():
    from app.showcase import reply_as_jane

    assert reply_as_jane("Jane_thoughtI do not have a tool to resend the payment link.", []) == (
        "I do not have a tool to resend the payment link."
    )
    assert "jane_thought" not in reply_as_jane("Jane: Jane_thoughtThe cistern can be repaired.", [{"speaker": "Jane"}]).casefold()


def test_a_copied_speaker_label_is_not_posted():
    from app.showcase import reply_as_jane

    lines = [{"speaker": "Ada", "role": "homesteader", "content": "The cistern is empty."}]
    assert reply_as_jane("Ada: Make it on the homestead.\nMake it on the homestead.", lines) == "Make it on the homestead."
    assert reply_as_jane("I'm sorry, but I don't know how to answer.", lines) == (
        "I do not know enough from this history yet. "
        "What containers, materials, or tools do you already have on the homestead that could help?"
    )


def test_gemini_receives_real_chat_roles():
    lines = [
        {"speaker": "Jane", "role": "jane", "content": "Tell me what the place needs."},
        {"speaker": "Ada", "role": "homesteader", "content": "The cistern is empty."},
    ]
    messages = chat_messages("constitution", render_history(lines), lines)
    assert [(message.type, message.content) for message in messages] == [
        ("system", "constitution"),
        ("ai", "Jane: Tell me what the place needs."),
        ("human", "Ada: The cistern is empty."),
    ]


def test_task_complexity_routes_planning_to_pro():
    assert task_complexity("Where do I get a liner?") == "standard"
    assert task_complexity("Compare three water systems and design a phased implementation plan.") == "complex"
    source = (Path(__file__).resolve().parents[1] / "app" / "gemini_flow.py").read_text(encoding="utf-8")
    assert 'thinking_level="low"' in source
    assert 'thinking_level="high"' in source
    assert "include_thoughts=False" in source


async def test_langchain_flow_selects_the_model_for_task_complexity():
    seen = []
    token = gemini_override.set(
        lambda model, _messages, complexity: seen.append((model, complexity)) or "routed"
    )
    try:
        assert await complete_text("constitution", "Hello Jane.") == "routed"
        assert await complete_text(
            "constitution",
            "Compare three water systems and design a phased implementation plan.",
        ) == "routed"
    finally:
        gemini_override.reset(token)
    assert seen == [
        ("gemini-3.5-flash", "standard"),
        ("gemini-3.1-pro-preview", "complex"),
    ]


def test_prompt_includes_the_constitution_grounded_record_and_history(client, store):
    seen = {"prompts": []}

    def fake(model, messages, complexity):
        seen["system"] = messages[0].content
        seen["models"] = [*seen.get("models", []), model]
        seen["complexities"] = [*seen.get("complexities", []), complexity]
        seen["prompts"].append("\n".join(str(message.content) for message in messages[1:]))
        return "Make the cistern on the homestead."

    before = store.properties[0]["northstar_automated_pct"]
    token = gemini_override.set(fake)
    try:
        first = client.post("/webhooks/chatwoot", json=_message("The cistern is empty.", 1, name="Ada"))
        second = client.post("/webhooks/chatwoot", json=_message("Where do I get a liner?", 2, name="Ada"))
    finally:
        gemini_override.reset(token)
    assert first.status_code == 200
    assert first.json()["reply"] == "Make the cistern on the homestead."
    assert seen["system"].startswith(JANE_CONSTITUTION)
    assert "CURRENT VERIFIED HOMESTEAD RECORD" in seen["system"]
    assert '"homesteader":null' in seen["system"]
    assert '"locality":"Lake Charles & Calcasieu Suburbs"' in seen["system"]
    assert '"known_facts":' in seen["system"]
    assert "facts already present" in seen["system"]
    assert "private internal context" in seen["system"]
    assert "valid recommendations even if chat history never named them" in seen["system"]
    assert "does not mean refusing to plan" in seen["system"]
    assert seen["models"] == ["gemini-3.5-flash", "gemini-3.5-flash"]
    assert seen["complexities"] == ["standard", "standard"]
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

    token = gemini_override.set(
        lambda _model, _messages, _complexity: "Buy it at https://www.amazon.com/dp/example today."
    )
    try:
        retail = client.post("/webhooks/chatwoot", json=_message("A liner, please.", 4, name="Ada"))
    finally:
        gemini_override.reset(token)
    assert "amazon" not in retail.json()["reply"].casefold()

    duplicate = client.post("/webhooks/chatwoot", json=_message("The cistern is empty.", 1, name="Ada"))
    assert duplicate.json()["duplicate"] is True
    assert len([row for row in store.transcript if row["message_id"] == "1"]) == 1


def test_recording_a_normal_fact_does_not_expose_internal_scores(client, store):
    token = gemini_override.set(
        lambda _model, _messages, _complexity: (
            "I recorded that you have about two acres and no equipment. "
            "What would you most like to build or grow first?"
        )
    )
    try:
        response = client.post(
            "/webhooks/chatwoot",
            json=_message("I currently have no equipment, and my property is about 2 acres.", 790, name="Ada"),
        )
    finally:
        gemini_override.reset(token)

    assert response.status_code == 200
    reply = response.json()["reply"]
    assert reply.startswith("I recorded that you have about two acres")
    for internal in ("Automated", "Aesthetic", "Material is", "Energetic", "Contained"):
        assert internal not in reply
    assert store.properties[0]["known_facts_ledger"]["acreage"] == "2"


def test_live_private_chat_applies_scores_and_grounded_sponsor_ranking(client, store):
    token = gemini_override.set(
        lambda _model, _messages, _complexity: "I will use your recorded information."
    )
    try:
        response = client.post(
            "/webhooks/chatwoot",
            json=_message(
                "I work 10 hours a week. Where can I get grow lights?",
                801,
                name="Ada",
            ),
        )
    finally:
        gemini_override.reset(token)

    assert response.status_code == 200
    assert "Calcasieu Glass & Lamp" in response.json()["reply"]
    assert store.properties[0]["outside_aid_hours_per_week"] == 10
    assert store.properties[0]["northstar_automated_pct"] == 75
    assert store.sponsors[0]["referrals_last_14d"] == 1


def test_live_private_chat_files_a_homestead_sponsor_profile(client, store):
    application = "\n".join(
        [
            "Register as a sponsor.",
            "Company: Ada Tomatoes",
            "Founding city: Lake Charles",
            "Founding state: LA",
            "Tier: local_manufacturer",
            "Tags: tomato, produce",
            "Summary: Grows tomatoes for nearby homesteads.",
            "Franchise: no",
            "Email: ada@example.com",
        ]
    )
    response = client.post(
        "/webhooks/chatwoot",
        json=_message(application, 802, name="Ada"),
    )

    assert response.status_code == 200
    assert "inactive sponsor" in response.json()["reply"]
    filed = next(row for row in store.sponsors if row["company_name"] == "Ada Tomatoes")
    assert filed["property_id"] == DEMO_PROPERTY_ID
    assert filed["is_active_sponsor"] is False


def test_a_connection_stays_quiet_until_someone_says_jane(client, store):
    calls = []
    token = gemini_override.set(
        lambda _model, messages, _complexity: calls.append(messages[-1].content) or "The homestead can make that."
    )
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
        gemini_override.reset(token)
    assert quiet.json()["ignored"] == "peer"
    assert named.json()["reply"] == "The homestead can make that."
    assert len(calls) == 1
    assert "Jane, the cistern is full." in calls[0]
    assert any(row["content"] == "The cistern is full." for row in store.transcript)


def test_an_approved_match_confirmation_is_handled_without_the_chat_model(client, store):
    import asyncio

    from app.matchmaking import approve_match

    match = asyncio.run(
        store.create_match(
            {
                "locality_id": store.properties[0]["locality_id"],
                "peer_a_property_id": store.properties[0]["id"],
                "peer_b_property_id": store.properties[1]["id"],
                "proposed_project_title": "shared seed library",
                "jane_synergy_rationale": "Both recorded a shared seed library.",
            }
        )
    )
    assert store.outbox == []
    asyncio.run(approve_match(store, match["id"], "Operator verified the recorded goals."))
    calls = []
    token = gemini_override.set(
        lambda _model, messages, _complexity: calls.append(messages[-1].content) or "model reply"
    )
    try:
        response = client.post(
            "/webhooks/chatwoot",
            json=_message(f"YES {match['id']}", 12, name="Ada"),
        )
    finally:
        gemini_override.reset(token)
    assert response.json()["match"] is True
    assert "other homestead still has to accept" in response.json()["reply"]
    assert calls == []
    assert store.matches[0]["peer_a_status"] == "accepted"


def test_a_missing_gemini_key_is_said_out_loud(client):
    token = gemini_override.set(None)
    try:
        response = client.post("/webhooks/chatwoot", json=_message("Hello Jane.", 20, name="Ada"))
    finally:
        gemini_override.reset(token)
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
    assert health.json()["llm"] == "gemini"
    assert health.json()["gemini_configured"] is False
    assert health.json()["gemini_chat_model"] == "gemini-3.5-flash"
    assert health.json()["audio_transcription_enabled"] is True


def test_background_jobs_stay_off_and_ollama_is_removed():
    assert celery_app.conf.beat_schedule == {}
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert 'profiles: ["background"]' in compose
    assert compose.count('profiles: ["background"]') == 2
    assert "ollama/ollama" not in compose
    assert "G01_BACKGROUND_JOBS: \"0\"" in compose
    assert "G01_GEMINI_CHAT_MODEL: gemini-3.5-flash" in compose
    assert "G01_GEMINI_DELIBERATION_MODEL: gemini-3.1-pro-preview" in compose
    assert "G01_GEMINI_EMBEDDING_MODEL: gemini-embedding-2" in compose
    assert "G01_MATCH_SIMILARITY_THRESHOLD: ${G01_MATCH_SIMILARITY_THRESHOLD:-0.82}" in compose
