"""Closing a sponsor must finish even when the record is incomplete or repeated."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.config import get_settings
from app.errors import G01Error
from app.operator import OperatorBackend
from app.payments import apply_stripe_event
from app.seed import DEMO_PROPERTY_ID, LAMP_SPONSOR_ID
from app.turn import run_turn
from tests.test_product_flows import _message


def _lamp(store) -> dict:
    return next(row for row in store.sponsors if row["id"] == LAMP_SPONSOR_ID)


async def _say(store, content: str, message_id: int) -> dict:
    return await run_turn(store, _message(content, message_id))


async def test_closing_an_application_clears_the_draft_and_can_be_repeated(store):
    store.properties[0]["sponsor_draft"] = {"company_name": "Lake Works", "open": True}
    before = len(store.sponsors)

    first = await _say(store, "close my sponsorship", 910)
    second = await _say(store, "cancel the sponsor", 911)

    assert first["ok"] is True
    assert "cleared the sponsorship application" in first["reply"]
    assert "could not finish" not in first["reply"]
    assert store.properties[0]["sponsor_draft"] is None
    assert len(store.sponsors) == before
    assert second["ok"] is True
    assert "isn't an open sponsorship" in second["reply"]


async def test_closing_survives_a_draft_that_is_not_an_object(store):
    store.properties[0]["sponsor_draft"] = ["company_name", "Lake Works"]

    closed = await _say(store, "cancel my sponsor", 912)

    assert closed["ok"] is True
    assert closed.get("error") != "turn failed"
    assert "cleared the sponsorship application" in closed["reply"]
    assert store.properties[0]["sponsor_draft"] is None

    store.properties[0]["sponsor_draft"] = "not a form"
    again = await _say(store, "end the sponsorship", 913)
    assert again["ok"] is True
    assert store.properties[0]["sponsor_draft"] is None


async def test_closing_an_active_listing_turns_it_off_and_a_second_close_is_quiet(store):
    lamp = _lamp(store)
    lamp["property_id"] = DEMO_PROPERTY_ID
    lamp["is_active_sponsor"] = True
    store.properties[0]["sponsor_draft"] = {"company_name": "Half finished"}

    closed = await _say(store, "close the sponsorship", 914)
    repeated = await _say(store, "drop my listing", 915)

    assert closed["ok"] is True
    assert "Calcasieu Glass & Lamp" in closed["reply"]
    assert "will not be recommended" in closed["reply"]
    assert lamp["is_active_sponsor"] is False
    assert store.properties[0]["sponsor_draft"] is None
    assert repeated["ok"] is True
    assert "isn't an open sponsorship" in repeated["reply"]
    assert lamp["is_active_sponsor"] is False


async def test_a_pending_poll_does_not_swallow_the_close(store):
    now = datetime.now(timezone.utc)
    poll, created = await store.create_community_poll(
        {
            "poll_key": "daily:70601:close-test",
            "poll_kind": "daily",
            "requester_property_id": None,
            "question": "Are you planning to keep a flock for eggs?",
            "opens_at": now,
            "closes_at": now + timedelta(days=1),
        }
    )
    assert created
    await store.add_community_poll_recipients(poll["id"], [store.properties[0]])
    store.properties[0]["sponsor_draft"] = {"company_name": "Lake Works"}

    closed = await _say(store, "stop my sponsorship", 916)

    assert closed["ok"] is True
    assert closed.get("poll") is not True
    assert "cleared the sponsorship application" in closed["reply"]
    assert store.properties[0]["sponsor_draft"] is None
    still_open = await store.pending_community_polls(store.properties[0]["id"])
    assert [row["id"] for row in still_open] == [poll["id"]]


async def test_operator_can_disable_a_broken_sponsor_without_rewriting_it(store):
    backend = OperatorBackend(store, get_settings())
    sponsor = _lamp(store)
    sponsor["service_tags"] = None
    sponsor["lat"] = None
    sponsor["lng"] = None
    sponsor["company_name"] = None
    sponsor["founding_city"] = None
    sponsor["capabilities_summary"] = None
    sponsor["is_active_sponsor"] = True

    disabled = await backend.execute(["sponsor-disable", sponsor["id"]], allow_write=True)
    again = await backend.execute(["sponsor-disable", sponsor["id"]], allow_write=True)

    assert disabled.value["is_active_sponsor"] is False
    assert again.value["is_active_sponsor"] is False
    assert sponsor["service_tags"] is None
    assert sponsor["lat"] is None
    assert sponsor["company_name"] is None

    with pytest.raises(G01Error) as missing:
        await backend.execute(["sponsor-disable", "not-a-uuid"], allow_write=True)
    assert missing.value.status_code == 404
    with pytest.raises(G01Error) as unknown:
        await backend.execute(
            ["sponsor-disable", "dddddddd-dddd-dddd-dddd-dddddddddddd"],
            allow_write=True,
        )
    assert unknown.value.status_code == 404


def test_stripe_can_end_a_subscription_when_the_event_is_messy(store):
    assert asyncio.run(apply_stripe_event(store, None)) == {"ok": True, "ignored": "malformed"}
    assert asyncio.run(
        apply_stripe_event(
            store,
            {"id": "evt_data", "type": "customer.subscription.deleted", "data": "nope"},
        )
    ) == {"ok": True, "ignored": "missing_subscription"}
    assert asyncio.run(
        apply_stripe_event(
            store,
            {
                "id": "evt_object",
                "type": "customer.subscription.deleted",
                "data": {"object": ["nope"]},
            },
        )
    ) == {"ok": True, "ignored": "missing_subscription"}
    assert asyncio.run(
        apply_stripe_event(
            store,
            {
                "id": "evt_id",
                "type": "customer.subscription.deleted",
                "data": {"object": {"id": 12, "status": "canceled"}},
            },
        )
    ) == {"ok": True, "ignored": "missing_subscription"}

    unknown = asyncio.run(
        apply_stripe_event(
            store,
            {
                "id": "evt_unknown",
                "type": "customer.subscription.deleted",
                "data": {"object": {"id": "sub_missing", "status": "canceled"}},
            },
        )
    )
    assert unknown == {"ok": True, "ignored": "unknown_subscription"}

    lamp = _lamp(store)
    lamp["property_id"] = DEMO_PROPERTY_ID
    lamp["stripe_subscription_id"] = "sub_close"
    lamp["is_active_sponsor"] = True
    store.properties[0]["primary_conversation_id"] = "not-a-number"
    messy = asyncio.run(
        apply_stripe_event(
            store,
            {
                "id": "evt_messy",
                "type": "customer.subscription.deleted",
                "data": {"object": {"id": "sub_close", "status": "canceled"}},
            },
        )
    )
    assert messy["ok"] is True
    assert messy["active"] is False
    assert lamp["is_active_sponsor"] is False

    store.properties[0]["primary_conversation_id"] = 501
    lamp["is_active_sponsor"] = True
    noted = asyncio.run(
        apply_stripe_event(
            store,
            {
                "id": "evt_noted",
                "type": "customer.subscription.updated",
                "data": {"object": {"id": "sub_close", "status": "canceled"}},
            },
        )
    )
    assert noted["active"] is False
    assert any("I closed Calcasieu Glass & Lamp" in row["content"] for row in store.outbox)
    replay = asyncio.run(
        apply_stripe_event(
            store,
            {
                "id": "evt_noted",
                "type": "customer.subscription.updated",
                "data": {"object": {"id": "sub_close", "status": "canceled"}},
            },
        )
    )
    assert replay == {"ok": True, "duplicate": True}
