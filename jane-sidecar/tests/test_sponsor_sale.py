"""Signing a local company up as a sponsor must finish even when the application is messy."""

from app.turn import run_turn
from tests.test_product_flows import _message


async def _say(store, content: str, message_id: int) -> dict:
    return await run_turn(store, _message(content, message_id))


def _dirty_application() -> dict:
    return {
        "listing_kind": "company",
        "company_name": "Lamp Shop",
        "founding_city": "Lake Charles",
        "founding_state": "LA",
        "sourcing_tier": "banana",
        "service_tags": "lamps",
        "capabilities_summary": "Makes lamps",
        "is_franchise_or_chain": "no",
        "billing_email": "pay@example.com",
        "lat": "nope",
        "lng": None,
    }


async def test_a_broken_draft_does_not_stop_the_sale(store):
    store.properties[0]["sponsor_draft"] = ["company_name", "Lamp Shop"]

    opened = await _say(store, "I want to become a sponsor.", 930)

    assert opened["ok"] is True
    assert opened.get("error") != "turn failed"
    assert "could not finish" not in opened["reply"]
    assert isinstance(store.properties[0]["sponsor_draft"], dict)


async def test_a_messy_company_application_still_files(store):
    store.properties[0]["sponsor_draft"] = _dirty_application()

    filed = await _say(store, "Please file the sponsorship.", 931)

    assert filed["ok"] is True
    assert "could not finish" not in filed["reply"]
    assert "I filed Lamp Shop as an inactive sponsor." in filed["reply"]
    created = [row for row in store.sponsors if row["company_name"] == "Lamp Shop"]
    assert len(created) == 1
    assert created[0]["is_franchise_or_chain"] is False
    assert created[0]["service_tags"] == ["lamps"]
    assert created[0]["is_active_sponsor"] is False
    assert store.properties[0]["sponsor_draft"] is None


async def test_a_sale_without_a_locality_keeps_the_application(store):
    store.properties[0]["locality_id"] = "dddddddd-dddd-dddd-dddd-dddddddddddd"
    store.properties[0]["sponsor_draft"] = _dirty_application()

    filed = await _say(store, "Please file the sponsorship.", 932)

    assert filed["ok"] is True
    assert "could not finish" not in filed["reply"]
    assert "which locality" in filed["reply"]
    assert store.properties[0]["sponsor_draft"]["company_name"] == "Lamp Shop"
    assert all(row["company_name"] != "Lamp Shop" for row in store.sponsors)


async def test_a_payment_page_failure_still_leaves_the_listing(store, monkeypatch):
    async def boom(*_args, **_kwargs):
        raise RuntimeError("stripe down")

    monkeypatch.setattr("app.sponsor_chat.create_sponsor_checkout", boom)
    store.properties[0]["sponsor_draft"] = _dirty_application()

    filed = await _say(store, "Please file the sponsorship.", 933)

    assert filed["ok"] is True
    assert "could not finish" not in filed["reply"]
    assert "payment page did not open" in filed["reply"]
    assert any(row["company_name"] == "Lamp Shop" for row in store.sponsors)


async def test_a_blank_checkout_does_not_crash_the_sale(store, monkeypatch):
    async def blank(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.sponsor_chat.create_sponsor_checkout", blank)
    store.properties[0]["sponsor_draft"] = _dirty_application()

    filed = await _say(store, "Please file the sponsorship.", 934)

    assert filed["ok"] is True
    assert "could not finish" not in filed["reply"]
    assert "did not return a payment link" in filed["reply"]
    assert any(row["company_name"] == "Lamp Shop" for row in store.sponsors)
