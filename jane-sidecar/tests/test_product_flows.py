import asyncio
from datetime import datetime, timedelta, timezone

from app.chatwoot_client import ChatwootClient
from app.jobs import mature_demand_polls, open_ready_collaborations, scan_neighbor_synergies
from app.llm import llm_override
from app.seed import DEMO_CONTACT_ID, DEMO_CONVERSATION_ID, DEMO_PROPERTY_ID, DEMO_USER_ID

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


def test_hud_context_keeps_five_dimensions(client):
    response = client.get(f"/api/hud/context?contact_id={CONTACT}&conversation_id={CONVERSATION}")
    assert response.status_code == 200
    body = response.json()
    star = body["northstar"]
    assert set(star) == {"automated", "aesthetic", "material", "energetic", "energetic_profitable", "contained"}
    assert star["automated"] == 25
    assert star["material"] is False
    assert star["contained"] is False
    assert star["energetic_profitable"] is False
    assert isinstance(star["energetic"], (int, float))
    page = client.get("/ui/hud?demo=1")
    assert page.status_code == 200
    for label in ("Automated", "Aesthetic", "Material", "Energetic", "Contained"):
        assert label in page.text


def test_aesthetic_slider_and_labor_hours(client):
    aesthetic = client.patch(
        f"/api/properties/{DEMO_PROPERTY_ID}/aesthetic",
        json={"aesthetic": 82.5, "contact_id": CONTACT, "conversation_id": CONVERSATION},
    )
    assert aesthetic.status_code == 200
    assert aesthetic.json()["northstar"]["aesthetic"] == 82.5
    assert aesthetic.json()["northstar"]["automated"] == 25
    assert aesthetic.json()["northstar"]["material"] is False

    labor = client.patch(
        f"/api/properties/{DEMO_PROPERTY_ID}/labor-hours",
        json={"outside_aid_hours_per_week": 10, "contact_id": CONTACT, "conversation_id": CONVERSATION},
    )
    assert labor.status_code == 200
    star = labor.json()["northstar"]
    assert star["automated"] == 75
    assert star["aesthetic"] == 82.5
    assert labor.json()["supporting"]["outside_aid_hours_per_week"] == 10

    rejected = client.patch(
        f"/api/properties/{DEMO_PROPERTY_ID}/aesthetic",
        json={"aesthetic": 140, "contact_id": CONTACT, "conversation_id": CONVERSATION},
    )
    assert rejected.status_code == 422


def test_local_rank_preview_prefers_the_maker_and_hides_walmart(client, store):
    response = client.get(
        f"/api/properties/{DEMO_PROPERTY_ID}/sponsors?service_tag=grow_lights&contact_id={CONTACT}&conversation_id={CONVERSATION}"
    )
    assert response.status_code == 200
    names = [row["company_name"] for row in response.json()["sponsors"]]
    assert names[0] == "Calcasieu Glass & Lamp"
    assert "Chenier Logistics" in names
    assert "Walmart" not in names
    assert response.json()["tier_1"]["tier_weight"] == 1
    assert store.sponsors[0]["referrals_last_14d"] == 0


def test_chat_turn_ranks_without_retailers_and_ignores_jane(client, store):
    token = llm_override.set(lambda model, system, user: {"reply": "Buy it at https://www.amazon.com/dp/example today."})
    try:
        response = client.post("/webhooks/chatwoot", json=_message("I need a grow light for aquaponics", 10))
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

    duplicate = client.post("/webhooks/chatwoot", json=_message("I need a grow light for aquaponics", 10))
    assert duplicate.json()["duplicate"] is True


def test_scores_follow_what_the_user_said(client, store):
    stated = client.post(
        "/webhooks/chatwoot",
        json=_message(
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
        client.post("/webhooks/chatwoot", json=_message("The hens are loud.", 13))
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
        from app.turn import run_turn

        asyncio.run(run_turn(fresh, _message("hello there", 14)))
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
                "locality_id": store.properties[0]["locality_id"],
                "zip_code": "70605",
                "lat": 30.23,
                "lng": -93.22,
            }
        )
    )
    response = client.post("/webhooks/chatwoot", json=_message("Is there a market for eggs around here?", 20))
    assert response.status_code == 200
    assert "24 hours" in response.json()["reply"]
    assert len(store.polls) == 1
    poll = store.polls[0]
    assert poll["mature_at"] - datetime.now(timezone.utc) > timedelta(hours=23)
    assert "70601" not in store.outbox[-1]["content"]
    neighbor = client.post(
        "/webhooks/chatwoot",
        json=_message("2 dozen at $5", 21, sender_id=301, conversation_id=601, contact_id=301),
    )
    assert neighbor.status_code == 200
    assert store.votes[0]["weekly_units_demanded"] == 2
    assert store.votes[0]["willing_price_per_unit_usd"] == 5
    assert created["id"] == store.votes[0]["neighbor_property_id"]

    early = asyncio.run(mature_demand_polls(store))
    assert early == []
    poll["mature_at"] = datetime.now(timezone.utc) - timedelta(minutes=1)
    reports = asyncio.run(mature_demand_polls(store))
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
    assert any(match_id in row["content"] for row in store.outbox)

    from app.turn import run_turn

    asyncio.run(run_turn(store, _message(f"YES {match_id}", 30)))
    asyncio.run(run_turn(store, _message(f"YES {match_id}", 31, sender_id=302, conversation_id=602, contact_id=302)))
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


def test_sponsor_registry_blocks_chains_and_waits_for_stripe(client):
    blocked = client.post(
        "/api/sponsors",
        json={
            "property_id": DEMO_PROPERTY_ID,
            "contact_id": CONTACT,
            "conversation_id": CONVERSATION,
            "company_name": "Walmart",
            "founding_city": "Lake Charles",
            "founding_state": "LA",
            "is_franchise_or_chain": True,
            "sourcing_tier": "local_service_or_stock",
            "service_tags": ["general_goods"],
            "capabilities_summary": "A national checkout counter.",
            "lat": 30.2,
            "lng": -93.2,
        },
    )
    assert blocked.status_code == 422
    assert "Rogers" in blocked.json()["detail"]

    waiting = client.post(
        "/api/sponsors",
        json={
            "property_id": DEMO_PROPERTY_ID,
            "contact_id": CONTACT,
            "conversation_id": CONVERSATION,
            "company_name": "Prioux Pumps",
            "founding_city": "Lake Charles",
            "founding_state": "LA",
            "is_franchise_or_chain": False,
            "sourcing_tier": "local_manufacturer",
            "service_tags": ["rain_catch"],
            "capabilities_summary": "Machines cistern pumps on Enterprise Boulevard.",
            "lat": 30.22,
            "lng": -93.21,
        },
    )
    assert waiting.status_code == 503

    rogers = client.get(
        "/api/properties/bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb2/sponsors?service_tag=general_goods&contact_id=102&conversation_id=502"
    )
    assert rogers.status_code == 200
    assert [row["company_name"] for row in rogers.json()["sponsors"]] == ["Walmart"]


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
        signup = gated.post(
            "/api/signup",
            json={"name": "Ada Yard", "email": "ada@example.com", "password": "pasture-1", "zip_code": "70601"},
        )
        assert signup.status_code == 503
        outside = gated.post(
            "/api/signup",
            json={"name": "Ada Yard", "email": "ada@example.com", "password": "pasture-1", "zip_code": "10001"},
        )
        assert outside.status_code == 503 or outside.status_code == 422
