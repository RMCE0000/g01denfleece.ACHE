from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.constitution import JANE_CONSTITUTION, JANE_SYSTEM_PROMPT
from app.heuristic import detect_service_tag
from app.northstar import NorthStar, automated_pct_from_hours
from app.sanitize import sanitize_reply
from app.sourcing import rank_sponsor_rows, recommendation_score, sponsor_matches_tag, sponsor_rejection_reason

ROOT = Path(__file__).resolve().parents[2]
SQL = (ROOT / "sql" / "001_init_g01_schema.sql").read_text(encoding="utf-8")


def test_automated_is_labor_reduction_not_a_free_number():
    assert automated_pct_from_hours(40) == 0
    assert automated_pct_from_hours(0) == 100
    assert automated_pct_from_hours(10) == 75
    assert automated_pct_from_hours(30) == 25
    assert automated_pct_from_hours(80) == 0
    with pytest.raises(ValueError):
        automated_pct_from_hours(-1)


def test_north_star_keeps_five_types():
    star = NorthStar(
        automated=25,
        aesthetic=50,
        material=False,
        energetic=140,
        energetic_profitable=True,
        contained=False,
    )
    assert isinstance(star.material, bool)
    assert isinstance(star.contained, bool)
    assert isinstance(star.energetic_profitable, bool)
    assert isinstance(star.automated, float)
    assert isinstance(star.aesthetic, float)
    assert isinstance(star.energetic, float)
    with pytest.raises(ValidationError):
        NorthStar(
            automated=101,
            aesthetic=50,
            material=False,
            energetic=10,
            energetic_profitable=False,
            contained=False,
        )


def test_recommendation_score_matches_the_published_weights():
    score = recommendation_score(
        sourcing_tier="local_service_or_stock",
        distance_miles=10,
        max_radius_miles=25,
        referrals_last_14d=3,
        homesteader_rating=4.5,
        promo_boost_weight=1.5,
    )
    assert score == Decimal("0.7770")
    assert recommendation_score(
        sourcing_tier="local_logistics_proxy",
        distance_miles=0,
        max_radius_miles=25,
        referrals_last_14d=0,
        homesteader_rating=5,
        promo_boost_weight=1,
    ) == Decimal("0.5000")


def test_arbitrary_goods_and_services_are_detected_and_matched():
    profile = {
        "service_tags": ["tomato", "3d_printing"],
        "capabilities_summary": "Grows produce and prints custom widgets.",
    }

    assert detect_service_tag("Where can I get tomatoes?") == "tomatoes"
    assert detect_service_tag("I need 3D printed widgets locally.") == "3d_printed_widgets"
    assert sponsor_matches_tag(profile, "tomatoes")
    assert sponsor_matches_tag(profile, "3d_printed_widgets")
    assert not sponsor_matches_tag(profile, "pressure_washing")


def test_fair_rotation_and_franchise_filter():
    locality = {"id": "loc", "primary_city": "Lake Charles", "state_code": "LA", "max_radius_miles": 25}
    prop = {"locality_id": "loc", "lat": 0.0, "lng": 0.0}
    sponsors = [
        {
            "id": "b",
            "locality_id": "loc",
            "company_name": "Busy Maker",
            "founding_city": "Lake Charles",
            "founding_state": "LA",
            "is_franchise_or_chain": False,
            "is_active_sponsor": True,
            "sourcing_tier": "local_manufacturer",
            "service_tags": ["grow_lights"],
            "capabilities_summary": "makes lamps",
            "lat": 0.0,
            "lng": 0.0,
            "referrals_last_14d": 20,
            "homesteader_rating": 5,
            "promo_boost_weight": 1,
        },
        {
            "id": "a",
            "locality_id": "loc",
            "company_name": "Quiet Maker",
            "founding_city": "Lake Charles",
            "founding_state": "LA",
            "is_franchise_or_chain": False,
            "is_active_sponsor": True,
            "sourcing_tier": "local_manufacturer",
            "service_tags": ["grow_lights"],
            "capabilities_summary": "makes lamps",
            "lat": 0.0,
            "lng": 0.0,
            "referrals_last_14d": 0,
            "homesteader_rating": 5,
            "promo_boost_weight": 1,
        },
        {
            "id": "w",
            "locality_id": "loc",
            "company_name": "Walmart",
            "founding_city": "Rogers",
            "founding_state": "AR",
            "is_franchise_or_chain": True,
            "is_active_sponsor": True,
            "sourcing_tier": "local_service_or_stock",
            "service_tags": ["grow_lights"],
            "capabilities_summary": "chain",
            "lat": 0.0,
            "lng": 0.0,
            "referrals_last_14d": 0,
            "homesteader_rating": 5,
            "promo_boost_weight": 3,
        },
    ]
    ranked = rank_sponsor_rows(property_row=prop, locality=locality, sponsors=sponsors, service_tag="grow_lights")
    assert [row["company_name"] for row in ranked] == ["Quiet Maker", "Busy Maker"]
    assert sponsor_rejection_reason(
        company_name="Walmart",
        is_franchise_or_chain=True,
        locality_city="Rogers",
        locality_state="AR",
        founding_city="Rogers",
        founding_state="AR",
    ) is None


def test_retailer_sentences_are_removed_whole():
    cleaned = sanitize_reply("Buy it at https://www.amazon.com/dp/example today.\nTier 1 stays.")
    assert "amazon" not in cleaned.casefold()
    assert "Buy it" not in cleaned
    assert "Tier 1 stays." in cleaned
    assert "Walmart" in sanitize_reply("1. Walmart — local_service_or_stock", allow_walmart_name=True)
    assert "Walmart" not in sanitize_reply("1. Walmart — local_service_or_stock")
    refusal = sanitize_reply("Walmart may only appear in Rogers, Arkansas. I did not file the listing.")
    assert "Rogers" in refusal
    assert "did not file" in refusal


def test_showcase_constitution_is_short_and_local():
    assert JANE_CONSTITUTION.startswith("You are Jane")
    for phrase in (
        "Automated",
        "Aesthetic",
        "Material",
        "Energetic",
        "Contained",
        "Make it on the homestead",
        "Amazon, Home Depot, Lowe's, Walmart",
        "Rogers, Arkansas",
        "said your name",
        "only here in this chat",
    ):
        assert phrase in JANE_CONSTITUTION
    assert "JSON object" not in JANE_CONSTITUTION
    assert "known_facts_ledger" not in JANE_CONSTITUTION
    assert "tier_weight" not in JANE_CONSTITUTION


def test_constitution_and_sql_keep_the_rules():
    for phrase in (
        "AUTOMATED",
        "AESTHETIC",
        "MATERIAL",
        "ENERGETIC",
        "CONTAINED",
        "NEVER recommend ordering from Amazon, Home Depot, Lowe's, Walmart",
        "tier_weight = 1.00",
        "tier_weight = 0.85",
        "tier_weight = 0.70",
        "tier_weight = 0.50",
        "collect the sponsorship answers in this Chatwoot thread",
        "Rogers, Arkansas",
        "0.45",
        "0.25",
        "0.20",
        "0.10",
    ):
        assert phrase in JANE_SYSTEM_PROMPT
    for phrase in (
        "northstar_automated_pct",
        "northstar_aesthetic_pct",
        "northstar_material_independent",
        "northstar_energetic_pct",
        "northstar_energetic_profitable",
        "northstar_contained_zero_waste",
        "WHEN 'homestead_fabrication' THEN 1.00",
        "WHEN 'local_manufacturer' THEN 0.85",
        "WHEN 'local_service_or_stock' THEN 0.70",
        "WHEN 'local_logistics_proxy' THEN 0.50",
        "0.45 + 0.25 * dist_score + 0.20 * rotation_score + 0.10 * rating_score",
        "3958.7613",
        "Walmart may only appear in Rogers, Arkansas",
        "Calcasieu Glass & Lamp",
        "Chenier Logistics",
        "vector(768)",
    ):
        assert phrase in SQL
    assert "seed.lng, FALSE" in SQL
    assert "SET is_active_sponsor = FALSE" in SQL
    assert "amazon.com" not in SQL.lower()
