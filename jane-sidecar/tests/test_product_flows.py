import asyncio
from datetime import datetime, timedelta, timezone

from langgraph.checkpoint.memory import MemorySaver

from app.chatwoot_client import ChatwootClient
from app.jobs import mature_demand_polls, open_ready_collaborations, scan_neighbor_synergies
from app.llm import llm_override
from app.matchmaking import approve_match
from app.payments import apply_stripe_event
from app.runtime import current_checkpointer
from app.seed import DEMO_CONTACT_ID, DEMO_CONVERSATION_ID, DEMO_PROPERTY_ID, DEMO_USER_ID
from tests.ledger_turn import ledger_reply, run_ledger_turn

CONTACT = DEMO_CONTACT_ID
CONVERSATION = DEMO_CONVERSATION_ID


def _message(content, message_id, sender_id=DEMO_USER_ID, sender_type="user", conversation_id=CONVERSATION, contact_id=CONTACT, attributes=None):
    return {
        "event": "message_created",
        "id": message_id,
        "content": content,
        "message_type": "outgoing",
        "private": False,
        "content_attributes": attributes or {},
        "sender": {"id": sender_id, "type": sender_type},
        "conversation": {
            "id": conversation_id,
            "account_id": 1,
            "meta": {"sender": {"id": contact_id, "type": "contact"}},
        },
        "account": {"id": 1},
    }


def test_scores_are_answered_in_the_thread(client, store):
    hidden = client.get("/ui/hud")
    assert hidden.status_code == 404
    response = ledger_reply(store, _message("What are my scores?", 1))
    assert response.status_code == 200
    reply = response.json()["reply"]
    for label in ("Automated 25.00", "Aesthetic 50.00", "Material is false", "Energetic is 10.00", "Contained is false"):
        assert label in reply


def test_aesthetic_and_labor_are_told_to_jane(client, store):
    told = ledger_reply(store, _message("I rate the beauty 82.5. We spend 10 hours a week.", 2))
    assert "Automated 75.00" in told.json()["reply"]
    assert "Aesthetic 82.50" in told.json()["reply"]
    response = ledger_reply(store, _message("What are my scores?", 3))
    reply = response.json()["reply"]
    assert "Automated 75.00" in reply
    assert "Aesthetic 82.50" in reply
    assert "Material is false" in reply
    assert store.properties[0]["northstar_automated_pct"] == 75
    assert store.properties[0]["northstar_aesthetic_pct"] == 82.5

    rejected = ledger_reply(store, _message("I rate the beauty 140.", 4))
    assert rejected.status_code == 200
    assert store.properties[0]["northstar_aesthetic_pct"] == 82.5


def test_asking_jane_ranks_the_maker_ahead_of_logistics(client, store):
    response = ledger_reply(store, _message("Where can I get a grow light?", 5))
    reply = response.json()["reply"]
    assert "Tier 1" in reply
    assert reply.index("Calcasieu Glass & Lamp") < reply.index("Chenier Logistics")
    assert "Walmart" not in reply
    assert "amazon" not in reply.casefold()
    assert store.sponsors[0]["referrals_last_14d"] == 1
    assert client.get(f"/api/properties/{DEMO_PROPERTY_ID}/sponsors").status_code == 404


def test_chat_turn_ranks_without_retailers_and_ignores_jane(client, store):
    token = llm_override.set(lambda model, system, user: {"reply": "Buy it at https://www.amazon.com/dp/example today."})
    try:
        response = ledger_reply(store, _message("I need a grow light for aquaponics", 10))
    finally:
        llm_override.reset(token)
    assert response.status_code == 200
    reply = response.json()["reply"]
    assert "amazon.com" not in reply.lower()
    assert "Tier 1" in reply
    assert "1.00" in reply
    assert reply.index("Calcasieu Glass & Lamp") < reply.index("Chenier Logistics")
    assert "Walmart" not in reply
    assert "aquaponics" in store.properties[0]["known_facts_ledger"]["active_goals"]
    assert store.sponsors[0]["referrals_last_14d"] == 1

    echo = client.post(
        "/webhooks/chatwoot",
        json=_message("Buy it at https://www.amazon.com/dp/example", 11, sender_id=1, attributes={"g01_author": "jane"}),
    )
    assert echo.json()["ignored"] == "jane"
    assert len([row for row in store.outbox if row["conversation_id"] == CONVERSATION]) == 1

    duplicate = ledger_reply(store, _message("I need a grow light for aquaponics", 10))
    assert duplicate.json()["duplicate"] is True


def test_scores_follow_what_the_user_said(client, store):
    stated = ledger_reply(
        store,
        _message(
            "We spend 10 hours a week. I rate the beauty 80. We produce 120 percent of our power and we are selling surplus energy at a net profit. We can live indefinitely off the property. The place is fully contained.",
            12,
        ),
    )
    assert stated.status_code == 200
    prop = store.properties[0]
    assert prop["northstar_automated_pct"] == 75
    assert prop["northstar_aesthetic_pct"] == 80
    assert prop["northstar_energetic_pct"] == 120
    assert prop["northstar_energetic_profitable"] is True
    assert prop["northstar_material_independent"] is True
    assert prop["northstar_contained_zero_waste"] is True

    token = llm_override.set(
        lambda model, system, user: {"reply": "You are fully independent.", "material_independent": True, "contained_zero_waste": True}
    )
    try:
        ledger_reply(store, _message("The hens are loud.", 13))
    finally:
        llm_override.reset(token)
    # The previous turn set the flags; this turn must not be what we assert.
    # Reset by a fresh property check: flags stay true from the prior true statements, not from this turn.
    # A separate property proves the gate.
    from app.memory_store import MemoryStore, seed_demo

    fresh = MemoryStore()
    seed_demo(fresh)
    token = llm_override.set(lambda model, system, user: {"reply": "Marked material true.", "material_independent": True})
    try:
        asyncio.run(run_ledger_turn(fresh, _message("hello there", 14)))
    finally:
        llm_override.reset(token)
    assert fresh.properties[0]["northstar_material_independent"] is False


def test_demand_poll_waits_twenty_four_hours(client, store):
    created = asyncio.run(
        store.create_property(
            {
                "chatwoot_account_id": 1,
                "chatwoot_user_id": 301,
                "chatwoot_contact_id": 301,
                "primary_conversation_id": 601,
                "username": "egg-neighbor",
                "locality_id": store.properties[0]["locality_id"],
                "zip_code": "70605",
                "lat": 30.23,
                "lng": -93.22,
            }
        )
    )
    response = ledger_reply(store, _message("Is there a market for eggs around here?", 20))
    assert response.status_code == 200
    assert "24 hours" in response.json()["reply"]
    assert len(store.polls) == 1
    poll = store.polls[0]
    assert poll["mature_at"] - datetime.now(timezone.utc) > timedelta(hours=23)
    assert "70601" not in store.outbox[-1]["content"]
    neighbor = ledger_reply(store, _message("2 dozen at $5", 21, sender_id=301, conversation_id=601, contact_id=301))
    assert neighbor.status_code == 200
    assert store.votes[0]["weekly_units_demanded"] == 2
    assert store.votes[0]["willing_price_per_unit_usd"] == 5
    assert created["id"] == store.votes[0]["neighbor_property_id"]

    early = asyncio.run(mature_demand_polls(store))
    assert early == []
    poll["mature_at"] = datetime.now(timezone.utc) - timedelta(minutes=1)
    checkpointer = current_checkpointer.set(MemorySaver())
    try:
        reports = asyncio.run(mature_demand_polls(store))
    finally:
        current_checkpointer.reset(checkpointer)
    assert reports and "2.00" in reports[0]
    assert "$5.00" in reports[0]
    assert store.polls[0]["status"] == "completed"


def test_collaboration_requires_two_yeses_and_kyc(store, monkeypatch):
    peer = asyncio.run(
        store.create_property(
            {
                "chatwoot_account_id": 1,
                "chatwoot_user_id": 302,
                "chatwoot_contact_id": 302,
                "primary_conversation_id": 602,
                "username": "aquaponics-peer",
                "locality_id": store.properties[0]["locality_id"],
                "zip_code": "70607",
                "lat": 30.24,
                "lng": -93.21,
                "known_facts_ledger": {**store.properties[0]["known_facts_ledger"], "active_goals": ["aquaponics"]},
            }
        )
    )
    created = asyncio.run(scan_neighbor_synergies(store))
    assert created
    match_id = created[0]
    assert store.matches[0]["shared_chatwoot_conversation_id"] is None
    assert store.matches[0]["operator_status"] == "pending"
    assert not any(match_id in row["content"] for row in store.outbox)

    approved = asyncio.run(approve_match(store, match_id, "Goals are grounded."))
    assert approved["match"]["operator_status"] == "approved"
    assert len(approved["pitched_property_ids"]) == 2
    assert any(match_id in row["content"] for row in store.outbox)

    asyncio.run(run_ledger_turn(store, _message(f"YES {match_id}", 30)))
    asyncio.run(run_ledger_turn(store, _message(f"YES {match_id}", 31, sender_id=302, conversation_id=602, contact_id=302)))
    match = asyncio.run(store.get_match(match_id))
    assert match["peer_a_status"] == "accepted"
    assert match["peer_b_status"] == "accepted"
    assert match["shared_chatwoot_conversation_id"] is None

    async def _open(_self, _peer_a, _peer_b):
        return 77

    monkeypatch.setattr(ChatwootClient, "create_shared_conversation", _open)
    asyncio.run(store.set_kyc(store.properties[0]["id"], True))
    asyncio.run(store.set_kyc(peer["id"], True))
    opened = asyncio.run(open_ready_collaborations(store))
    assert opened == [77]
    match = asyncio.run(store.get_match(match_id))
    assert match["shared_chatwoot_conversation_id"] == 77


def test_sponsor_registry_is_a_conversation(client, store):
    blocked = ledger_reply(
        store,
        _message(
            "\n".join(
                [
                    "I want to register as a sponsor.",
                    "Company: Walmart",
                    "Founding city: Lake Charles",
                    "Founding state: LA",
                    "Tier: local_service_or_stock",
                    "Tags: general_goods",
                    "Summary: A national checkout counter for the parish.",
                    "Franchise: yes",
                ]
            ),
            40,
        ),
    )
    assert blocked.status_code == 200
    assert "Rogers" in blocked.json()["reply"]
    assert all(row["company_name"] != "Walmart" or row["locality_id"] != store.properties[0]["locality_id"] for row in store.sponsors)

    waiting = ledger_reply(
        store,
        _message(
            "\n".join(
                [
                    "Register as a sponsor.",
                    "Company: Prioux Pumps",
                    "Founding city: Lake Charles",
                    "Founding state: LA",
                    "Tier: local_manufacturer",
                    "Tags: rain_catch",
                    "Summary: Machines cistern pumps on Enterprise Boulevard.",
                    "Lat: 30.22",
                    "Lng: -93.21",
                    "Franchise: no",
                ]
            ),
            41,
        ),
    )
    assert waiting.status_code == 200
    assert "Stripe is not configured" in waiting.json()["reply"]
    filed = next(row for row in store.sponsors if row["company_name"] == "Prioux Pumps")
    assert filed["is_active_sponsor"] is False

    rogers = ledger_reply(
        store,
        _message(
            "Where can I get general goods?",
            42,
            sender_id=202,
            conversation_id=502,
            contact_id=102,
        ),
    )
    assert "Walmart" in rogers.json()["reply"]
    assert "ui/hud" not in rogers.json()["reply"]


def test_stripe_event_retries_are_idempotent(store):
    sponsor = store.sponsors[0]
    sponsor["is_active_sponsor"] = False
    asyncio.run(store.attach_checkout("cs_launch", sponsor["id"]))
    event = {
        "id": "evt_launch",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_launch",
                "payment_status": "paid",
                "customer": "cus_launch",
                "subscription": "sub_launch",
            }
        },
    }

    first = asyncio.run(apply_stripe_event(store, event))
    second = asyncio.run(apply_stripe_event(store, event))

    assert first["active"] is True
    assert second == {"ok": True, "duplicate": True}
    assert store.sponsors[0]["stripe_subscription_id"] == "sub_launch"


def test_zip_attaches_the_thread_and_hides_the_street(client, store):
    opened = ledger_reply(
        store,
        _message(
            "ZIP 70601. We spend 10 hours a week. My address is 12 Prien Lake Road.",
            80,
            sender_id=880,
            conversation_id=880,
            contact_id=880,
        ),
    )
    assert opened.status_code == 200
    reply = opened.json()["reply"]
    assert "Lake Charles" in reply
    assert "Automated 75.00" in reply
    assert "Prien" not in reply
    prop = next(row for row in store.properties if row["chatwoot_contact_id"] == 880)
    assert prop["zip_code"] == "70601"
    assert prop["street_address"] == "12 Prien Lake Road"
    assert prop["northstar_automated_pct"] == 75

    outside = ledger_reply(store, _message("ZIP 10001", 81, sender_id=881, conversation_id=881, contact_id=881))
    assert "outside" in outside.json()["reply"]
    assert all(row["chatwoot_contact_id"] != 881 for row in store.properties)

    pinned = ledger_reply(store, _message("The latitude is 30.2400 and the longitude is -93.2200. I have 4 acres.", 82))
    assert "30.24000" in pinned.json()["reply"]
    assert store.properties[0]["lat"] == 30.24
    assert store.properties[0]["known_facts_ledger"]["acreage"] == "4"
    far = ledger_reply(store, _message("The latitude is 0 and the longitude is 0.", 83))
    assert "outside this locality" in far.json()["reply"]
    assert store.properties[0]["lat"] == 30.24

    market = ledger_reply(store, _message("Is there a market for eggs around here? My address is 12 Prien Lake Road.", 84))
    assert market.status_code == 200
    assert "Prien" not in market.json()["reply"]
    assert all("Prien" not in row["content"] for row in store.outbox)


def test_promo_admin_and_signup_gate(store, monkeypatch):
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import create_app

    monkeypatch.setenv("G01_ADMIN_TOKEN", "secret-admin")
    get_settings.cache_clear()
    with TestClient(create_app(store)) as gated:
        denied = gated.post(
            "/api/admin/promo-codes",
            json={"code": "swla50", "stripe_coupon_id": "coupon_swla", "discount_percent": 50, "recommendation_boost": 1.1},
        )
        assert denied.status_code == 401
        created = gated.post(
            "/api/admin/promo-codes",
            headers={"x-g01-admin-token": "secret-admin"},
            json={"code": "swla50", "stripe_coupon_id": "coupon_swla", "discount_percent": 50, "recommendation_boost": 1.1},
        )
        assert created.status_code == 200
        assert created.json()["code"] == "SWLA50"
        assert gated.get("/ui/signup").status_code == 404
        signup = gated.post("/api/signup", json={"name": "Ada Yard", "email": "ada@example.com", "password": "pasture-1", "zip_code": "70601"})
        assert signup.status_code == 503
