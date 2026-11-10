"""Daily questions follow the ZIP. Profiles are only what homesteaders said."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone

from app.config import get_settings
from app.economy import FEW_ZIP_HOMESTEADS, choose_daily_question, shared_terms
from app.operator import OperatorBackend
from app.poll_topics import TOPICS, topic_for
from app.polling import ensure_daily_poll, offer_conversation_question
from app.seed import DEMO_CONVERSATION_ID, DEMO_PROPERTY_ID, DEMO_USER_ID


def test_the_topic_list_has_two_hundred_distinct_questions():
    assert len(TOPICS) == 200
    assert len(set(TOPICS)) == 200
    assert all(topic.endswith("?") for topic in TOPICS)


def test_a_small_zip_keeps_one_topic_for_the_day_and_changes_the_next_day():
    day = datetime(2026, 11, 10, tzinfo=timezone.utc).date()
    first = topic_for("70601", day)
    assert topic_for("70601", day) == first
    assert choose_daily_question("70601", day, [{"id": "one"}], []) == first
    assert len({topic_for("70601", day + timedelta(days=offset)) for offset in range(30)}) > 1


def test_a_larger_zip_is_asked_about_a_word_two_homesteads_actually_used():
    properties = [
        {"id": "a", "primary_conversation_id": 1, "zip_code": "70601"},
        {"id": "b", "primary_conversation_id": 2, "zip_code": "70601"},
        {"id": "c", "primary_conversation_id": 3, "zip_code": "70601"},
    ]
    lines = [
        {"conversation_id": 1, "role": "homesteader", "content": "I have extra lumber from the barn."},
        {"conversation_id": 2, "role": "homesteader", "content": "We need lumber for the coop."},
        {"conversation_id": 3, "role": "jane", "content": "I will not invent a third mention of lumber."},
    ]
    assert len(properties) >= FEW_ZIP_HOMESTEADS
    assert shared_terms(properties, lines) == ["lumber"]
    question = choose_daily_question("70601", datetime(2026, 11, 10).date(), properties, lines)
    assert question == "More than one homestead in 70601 has mentioned lumber. Do you have lumber to share, or do you need some?"


async def test_daily_poll_is_one_question_per_zip(store):
    settings = get_settings()
    now = datetime(2026, 11, 10, 15, tzinfo=timezone.utc)
    first = await ensure_daily_poll(store, settings, now=now)
    assert len(first["polls"]) == 2
    assert all(poll["question"] in TOPICS for poll in first["polls"])
    again = await ensure_daily_poll(store, settings, now=now + timedelta(hours=2))
    assert again["created"] is False
    assert again["recipients_added"] == 0


def test_a_conversation_asks_one_more_question_and_records_the_answer(client, store):
    opened = client.post(
        "/webhooks/chatwoot",
        json={
            "event": "message_created",
            "id": 880,
            "content": "The cistern is full.",
            "message_type": "outgoing",
            "private": False,
            "sender": {"id": DEMO_USER_ID, "type": "user", "name": "Ada"},
            "conversation": {
                "id": DEMO_CONVERSATION_ID,
                "account_id": 1,
                "meta": {"sender": {"id": 101, "type": "contact"}},
            },
            "account": {"id": 1},
        },
    )
    assert opened.status_code == 200
    assert opened.json()["reply"] == "Noted."
    questions = [row["content"] for row in store.outbox if row["content"] != "Noted."]
    assert len(questions) == 1
    assert questions[0] in TOPICS
    assert store.economy_notes[0]["source"] == "conversation"
    assert store.economy_notes[0]["answer"] is None

    answered = client.post(
        "/webhooks/chatwoot",
        json={
            "event": "message_created",
            "id": 881,
            "content": "I can share lumber.",
            "message_type": "outgoing",
            "private": False,
            "sender": {"id": DEMO_USER_ID, "type": "user", "name": "Ada"},
            "conversation": {
                "id": DEMO_CONVERSATION_ID,
                "account_id": 1,
                "meta": {"sender": {"id": 101, "type": "contact"}},
            },
            "account": {"id": 1},
        },
    )
    assert answered.json().get("poll") is None
    assert answered.json()["reply"] == "Noted."
    assert store.economy_notes[0]["answer"] == "I can share lumber."
    # The day's conversation question is already asked, so the answer does not
    # earn a second one.
    assert [row["content"] for row in store.outbox if row["content"] != "Noted."] == [questions[0]]


async def test_a_live_conversation_uses_the_other_homestead_s_recorded_word(store):
    other = deepcopy(store.properties[0])
    other.update(
        {
            "id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb9",
            "chatwoot_contact_id": 109,
            "chatwoot_user_id": 209,
            "primary_conversation_id": 509,
            "username": "mill-homestead",
        }
    )
    store.properties.append(other)
    await store.append_transcript(
        conversation_id=DEMO_CONVERSATION_ID,
        message_id="lumber-1",
        role="homesteader",
        speaker="Ada",
        content="I have extra lumber.",
    )
    await store.append_transcript(
        conversation_id=509,
        message_id="lumber-2",
        role="homesteader",
        speaker="Bea",
        content="We are short on lumber.",
    )
    question = await offer_conversation_question(store, store.properties[0])
    assert "lumber" in question
    assert "70601" in question


async def test_economy_analysis_groups_a_zip_without_inventing_a_need(store):
    await ensure_daily_poll(store, get_settings(), now=datetime(2026, 11, 10, 15, tzinfo=timezone.utc))
    poll = next(row for row in store.community_polls if row["poll_key"].startswith("daily:70601:"))
    await store.save_economy_note(
        {
            "property_id": DEMO_PROPERTY_ID,
            "zip_code": "70601",
            "poll_id": poll["id"],
            "source": "daily",
            "question": poll["question"],
            "answer": "I can share lumber.",
        }
    )
    backend = OperatorBackend(store, get_settings())
    report = await backend.analyze("economy")
    assert report["summary"]["profiles"] == 1
    assert report["zips"][0]["zip_code"] == "70601"
    assert report["zips"][0]["shared_terms"] == []
