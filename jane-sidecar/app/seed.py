"""Fixed local fixtures for the memory store and the demo Chatwoot threads."""

from datetime import datetime, timezone

from app.northstar import DEFAULT_LEDGER, automated_pct_from_hours

LC_LOCALITY_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1"
ROGERS_LOCALITY_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa2"
DEMO_PROPERTY_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb1"
ROGERS_PROPERTY_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb2"
LAMP_SPONSOR_ID = "cccccccc-cccc-cccc-cccc-ccccccccccc1"
HAUL_SPONSOR_ID = "cccccccc-cccc-cccc-cccc-ccccccccccc2"
ROGERS_MILL_ID = "cccccccc-cccc-cccc-cccc-ccccccccccc3"
ROGERS_WALMART_ID = "cccccccc-cccc-cccc-cccc-ccccccccccc4"

DEMO_CONTACT_ID = 101
DEMO_CONVERSATION_ID = 501
DEMO_USER_ID = 201
ROGERS_CONTACT_ID = 102
ROGERS_CONVERSATION_ID = 502
ROGERS_USER_ID = 202


def demo_localities() -> list[dict]:
    return [
        {
            "id": LC_LOCALITY_ID,
            "name": "Lake Charles & Calcasieu Suburbs",
            "primary_city": "Lake Charles",
            "state_code": "LA",
            "allowed_zip_codes": ["70601", "70605", "70607", "70611", "70615", "70663", "70669"],
            "center_lat": 30.2266,
            "center_lng": -93.2174,
            "max_radius_miles": 25.0,
        },
        {
            "id": ROGERS_LOCALITY_ID,
            "name": "Rogers Metro",
            "primary_city": "Rogers",
            "state_code": "AR",
            "allowed_zip_codes": ["72756", "72758"],
            "center_lat": 36.3320,
            "center_lng": -94.1185,
            "max_radius_miles": 25.0,
        },
    ]


def _property(
    *,
    property_id: str,
    locality_id: str,
    contact_id: int,
    user_id: int,
    conversation_id: int,
    zip_code: str,
    lat: float,
    lng: float,
    goals: list[str],
) -> dict:
    hours = 30.0
    ledger = {**DEFAULT_LEDGER, "active_goals": list(goals)}
    now = datetime.now(timezone.utc)
    return {
        "id": property_id,
        "chatwoot_account_id": 1,
        "chatwoot_user_id": user_id,
        "chatwoot_contact_id": contact_id,
        "primary_conversation_id": conversation_id,
        "chatwoot_inbox_id": None,
        "email": None,
        "display_name": None,
        "locality_id": locality_id,
        "street_address": None,
        "zip_code": zip_code,
        "lat": lat,
        "lng": lng,
        "northstar_automated_pct": automated_pct_from_hours(hours),
        "outside_aid_hours_per_week": hours,
        "northstar_aesthetic_pct": 50.0,
        "northstar_material_independent": False,
        "material_surplus_profitable": False,
        "northstar_energetic_pct": 10.0,
        "northstar_energetic_profitable": False,
        "northstar_contained_zero_waste": False,
        "known_facts_ledger": ledger,
        "kyc_verified": False,
        "stripe_identity_session_id": None,
        "updated_at": now,
        "goals_embedding": None,
    }


def demo_properties() -> list[dict]:
    return [
        _property(
            property_id=DEMO_PROPERTY_ID,
            locality_id=LC_LOCALITY_ID,
            contact_id=DEMO_CONTACT_ID,
            user_id=DEMO_USER_ID,
            conversation_id=DEMO_CONVERSATION_ID,
            zip_code="70601",
            lat=30.2266,
            lng=-93.2174,
            goals=["aquaponics"],
        ),
        _property(
            property_id=ROGERS_PROPERTY_ID,
            locality_id=ROGERS_LOCALITY_ID,
            contact_id=ROGERS_CONTACT_ID,
            user_id=ROGERS_USER_ID,
            conversation_id=ROGERS_CONVERSATION_ID,
            zip_code="72756",
            lat=36.3320,
            lng=-94.1185,
            goals=["timber frame"],
        ),
    ]


def _sponsor(**kwargs) -> dict:
    base = {
        "property_id": None,
        "is_franchise_or_chain": False,
        "referrals_last_14d": 0,
        "last_referred_at": None,
        "homesteader_rating": 5.0,
        "promo_boost_weight": 1.0,
        "stripe_customer_id": None,
        "stripe_subscription_id": None,
        "applied_promo_code": None,
        "is_active_sponsor": True,
        "created_at": datetime.now(timezone.utc),
        "capabilities_embedding": None,
    }
    base.update(kwargs)
    return base


def demo_sponsors() -> list[dict]:
    return [
        _sponsor(
            id=LAMP_SPONSOR_ID,
            locality_id=LC_LOCALITY_ID,
            company_name="Calcasieu Glass & Lamp",
            founding_city="Lake Charles",
            founding_state="LA",
            sourcing_tier="local_manufacturer",
            service_tags=["grow_lights"],
            capabilities_summary="Blows and wires small greenhouse lamps in Lake Charles.",
            lat=30.2400,
            lng=-93.2200,
        ),
        _sponsor(
            id=HAUL_SPONSOR_ID,
            locality_id=LC_LOCALITY_ID,
            company_name="Chenier Logistics",
            founding_city="Lake Charles",
            founding_state="LA",
            sourcing_tier="local_logistics_proxy",
            service_tags=["grow_lights", "logistics"],
            capabilities_summary="Local procurement and delivery inside Calcasieu Parish.",
            lat=30.2266,
            lng=-93.2174,
        ),
        _sponsor(
            id=ROGERS_MILL_ID,
            locality_id=ROGERS_LOCALITY_ID,
            company_name="Rogers Oak Mill",
            founding_city="Rogers",
            founding_state="AR",
            sourcing_tier="local_manufacturer",
            service_tags=["lumber"],
            capabilities_summary="Mills oak in Rogers.",
            lat=36.3400,
            lng=-94.1200,
        ),
        _sponsor(
            id=ROGERS_WALMART_ID,
            locality_id=ROGERS_LOCALITY_ID,
            company_name="Walmart",
            founding_city="Rogers",
            founding_state="AR",
            is_franchise_or_chain=True,
            sourcing_tier="local_service_or_stock",
            service_tags=["general_goods"],
            capabilities_summary="Origin store in Rogers, Arkansas. No public checkout link is stored.",
            lat=36.3320,
            lng=-94.1185,
        ),
    ]


def demo_promos() -> list[dict]:
    return [
        {
            "code": "FOUNDER100",
            "stripe_coupon_id": "coupon_founder100",
            "discount_percent": 100,
            "recommendation_boost": 1.25,
            "restricted_locality_id": None,
            "max_uses": 100,
            "current_uses": 0,
            "active": True,
        }
    ]
