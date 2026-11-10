from copy import deepcopy
import asyncio
from datetime import datetime, timedelta, timezone

from app.config import get_settings
from app.graphs.matchmaking_graph import _overlap, discover_neighbor_synergies
from app.polling import (
    DEFAULT_POLL_MODE_QUESTION,
    close_due_community_polls,
    compile_community_poll,
    create_requested_poll,
    ensure_daily_poll,
)
from app.seed import (
    DEMO_CONVERSATION_ID,
    DEMO_USER_ID,
    ROGERS_CONVERSATION_ID,
    ROGERS_PROPERTY_ID,
    ROGERS_USER_ID,
)


def _message(content: str, message_id: int, *, user_id: int, conversation_id: int):
    return {
        "event": "message_created",
        "id": message_id,
        "content": content,
        "message_type": "outgoing",
        "private": False,
        "content_attributes": {},
        "sender": {"id": user_id, "type": "user", "name": f"User {user_id}"},
        "conversation": {"id": conversation_id, "account_id": 1, "meta": {"sender": {}}},
        "account": {"id": 1},
    }


async def test_daily_poll_is_once_per_local_day_and_adds_only_new_users(store):
    settings = get_settings()
    now = datetime(2026, 11, 3, 15, tzinfo=timezone.utc)
    first = await ensure_daily_poll(store, settings, now=now)
    second = await ensure_daily_poll(store, settings, now=now + timedelta(hours=1))

    assert first["created"] is True
    assert first["recipients_added"] == 2
    assert second["created"] is False
    assert second["recipients_added"] == 0
    assert len(store.community_polls) == 1
    assert len(store.outbox) == 2

    newcomer = deepcopy(store.properties[0])
    newcomer.update(
        {
            "id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb3",
            "chatwoot_user_id": 203,
            "chatwoot_contact_id": 103,
            "primary_conversation_id": 503,
            "username": "new-homestead",
        }
    )
    store.properties.append(newcomer)
    third = await ensure_daily_poll(store, settings, now=now + timedelta(hours=2))
    assert third["recipients_added"] == 1
    assert len(store.outbox) == 3
    assert store.outbox[-1]["conversation_id"] == 503


def test_poll_mode_broadcasts_and_the_next_private_reply_is_an_answer(client, store):
    started = client.post(
        "/webhooks/chatwoot",
        json=_message(
            "poll mode: What should we build together?",
            700,
            user_id=DEMO_USER_ID,
            conversation_id=DEMO_CONVERSATION_ID,
        ),
    )
    assert started.status_code == 200
    assert started.json()["poll"] is True
    assert started.json()["reply"] == "I asked the other homesteads: What should we build together?"
    assert "poll mode" not in started.json()["reply"].casefold()
    assert {row["conversation_id"] for row in store.outbox} == {
        DEMO_CONVERSATION_ID,
        ROGERS_CONVERSATION_ID,
    }

    answered = client.post(
        "/webhooks/chatwoot",
        json=_message(
            "A shared seed library and tool shed.",
            701,
            user_id=ROGERS_USER_ID,
            conversation_id=ROGERS_CONVERSATION_ID,
        ),
    )
    assert answered.json()["poll"] is True
    assert answered.json()["reply"] == "Noted."
    assert store.community_poll_answers[0]["property_id"] == ROGERS_PROPERTY_ID
    assert store.community_poll_answers[0]["answer"] == "A shared seed library and tool shed."


def test_an_ordinary_question_is_posted_to_the_other_homesteads(client, store):
    import json

    from app.constitution import JANE_CONSTITUTION
    from app.gemini_flow import gemini_override

    def think(_model, messages, complexity):
        assert complexity == "standard"
        system = messages[0].content
        latest = messages[-1].content
        if "does anybody want a dog" in latest.casefold():
            return json.dumps(
                {
                    "reply": "I'll ask whether anyone wants to bring a dog onto their homestead.",
                    "tools": [
                        {
                            "name": "ask_community",
                            "arguments": {"question": "Would you bring a dog onto your homestead?"},
                        }
                    ],
                }
            )
        assert "No community question is waiting." in system
        return "I don't have one for you today."

    token = gemini_override.set(think)
    try:
        status = client.post(
            "/webhooks/chatwoot",
            json=_message(
                "Do you have any polls for me?",
                710,
                user_id=DEMO_USER_ID,
                conversation_id=DEMO_CONVERSATION_ID,
            ),
        )
        asked = client.post(
            "/webhooks/chatwoot",
            json=_message(
                "Yeah... does anybody want a dog? I have 5 up for adoption.",
                711,
                user_id=DEMO_USER_ID,
                conversation_id=DEMO_CONVERSATION_ID,
            ),
        )
    finally:
        gemini_override.reset(token)

    assert status.json().get("poll") is None
    assert status.json()["reply"] == "I don't have one for you today."
    assert "poll mode" not in status.json()["reply"].casefold()
    assert "poll mode" not in JANE_CONSTITUTION
    assert asked.json()["reply"] == "I'll ask whether anyone wants to bring a dog onto their homestead."
    assert "poll mode" not in asked.json()["reply"].casefold()
    assert store.community_polls[-1]["question"] == "Would you bring a dog onto your homestead?"
    assert "does anybody want a dog" not in store.community_polls[-1]["question"].casefold()
    assert len(store.community_polls) == 1


def test_plain_poll_mode_uses_the_community_action_question(client, store):
    started = client.post(
        "/webhooks/chatwoot",
        json=_message(
            "poll mode",
            702,
            user_id=DEMO_USER_ID,
            conversation_id=DEMO_CONVERSATION_ID,
        ),
    )
    assert started.json()["poll"] is True
    assert DEFAULT_POLL_MODE_QUESTION in started.json()["reply"]
    assert store.community_polls[0]["question"] == DEFAULT_POLL_MODE_QUESTION


def test_pending_poll_does_not_capture_an_explicit_jane_request(client, store):
    asyncio.run(
        create_requested_poll(
            store,
            store.properties[0],
            "What should we organize next?",
        )
    )
    response = client.post(
        "/webhooks/chatwoot",
        json=_message(
            "Jane, what are my scores?",
            703,
            user_id=DEMO_USER_ID,
            conversation_id=DEMO_CONVERSATION_ID,
        ),
    )

    assert response.status_code == 200
    assert response.json().get("poll") is None
    assert "Automated" in response.json()["reply"]
    assert store.community_poll_answers == []

    sourcing = client.post(
        "/webhooks/chatwoot",
        json=_message(
            "Where can I get a rainwater cistern?",
            704,
            user_id=DEMO_USER_ID,
            conversation_id=DEMO_CONVERSATION_ID,
        ),
    )
    assert sourcing.status_code == 200
    assert sourcing.json().get("poll") is None
    assert store.community_poll_answers == []


def test_pending_poll_does_not_interrupt_a_sponsor_application(client, store):
    asyncio.run(
        create_requested_poll(
            store,
            store.properties[0],
            "What should we organize next?",
        )
    )
    store.properties[0]["sponsor_draft"] = {"company_name": "Lake Works"}
    response = client.post(
        "/webhooks/chatwoot",
        json=_message(
            "Lake Charles",
            705,
            user_id=DEMO_USER_ID,
            conversation_id=DEMO_CONVERSATION_ID,
        ),
    )

    assert response.status_code == 200
    assert response.json().get("poll") is None
    assert store.community_poll_answers == []
    assert store.properties[0]["sponsor_draft"] is not None


async def test_compilation_and_atomic_close_are_grounded_in_recorded_answers(store):
    now = datetime(2026, 11, 3, 15, tzinfo=timezone.utc)
    result = await create_requested_poll(
        store,
        store.properties[0],
        "What project should come first?",
        now=now,
    )
    poll = result["poll"]
    await store.answer_community_poll(
        poll["id"],
        store.properties[0]["id"],
        "Build a shared seed library.",
    )
    await store.answer_community_poll(
        poll["id"],
        store.properties[1]["id"],
        "A shared seed exchange and tool library.",
    )
    compiled = await compile_community_poll(store, poll)
    assert compiled["analysis"]["response_count"] == 2
    assert compiled["analysis"]["recipient_count"] == 2
    assert compiled["analysis"]["response_rate_pct"] == 100.0
    assert any(row["theme"] == "shared" and row["mentions"] == 2 for row in compiled["analysis"]["themes"])
    assert "lake-homestead: Build a shared seed library." in compiled["report"]

    for row in store.community_polls:
        if row["id"] == poll["id"]:
            row["closes_at"] = now - timedelta(seconds=1)
    first_close = await close_due_community_polls(store)
    second_close = await close_due_community_polls(store)
    assert len(first_close) == 1
    assert second_close == []
    assert store.community_polls[0]["compiled_analysis"]["response_count"] == 2


async def test_poll_answers_feed_automatic_match_discovery_without_contacting_users(store):
    store.properties[1]["locality_id"] = store.properties[0]["locality_id"]
    result = await create_requested_poll(
        store,
        store.properties[0],
        "What should neighbors build together?",
    )
    poll_id = result["poll"]["id"]
    await store.answer_community_poll(
        poll_id,
        store.properties[0]["id"],
        "Build a shared cedar tool shed.",
    )
    await store.answer_community_poll(
        poll_id,
        store.properties[1]["id"],
        "A shared cedar shed would help.",
    )
    outbox_before = len(store.outbox)
    created = await discover_neighbor_synergies(store)
    assert len(created) == 1
    assert store.matches[0]["operator_status"] == "pending"
    assert "cedar" in store.matches[0]["proposed_project_title"]
    assert len(store.outbox) == outbox_before


def test_match_overlap_ignores_generic_cooperation_words():
    generic_left = {"known_facts_ledger": {"active_goals": ["Shared neighborhood help"]}}
    generic_right = {"known_facts_ledger": {"active_goals": ["Help with a shared project"]}}
    rain_left = {"known_facts_ledger": {"active_goals": ["Run a rain barrel pump workshop"]}}
    rain_right = {"known_facts_ledger": {"active_goals": ["Organize a rain barrel workshop"]}}

    assert _overlap(generic_left, generic_right) == []
    assert _overlap(rain_left, rain_right) == ["barrel", "rain", "workshop"]
