"""Apply signed Stripe events. KYC becomes true only on a verified Identity session."""

import logging

from app.collaboration import refresh_matches_for_property

log = logging.getLogger(__name__)


async def apply_stripe_event(store, event: dict) -> dict:
    event_id = str(event.get("id") or "").strip()
    dedupe_id = f"stripe:{event_id}" if event_id else ""
    if dedupe_id and not await store.mark_event(dedupe_id):
        return {"ok": True, "duplicate": True}
    try:
        return await _apply_stripe_event(store, event)
    except Exception:
        if dedupe_id:
            await store.unmark_event(dedupe_id)
        raise


async def _apply_stripe_event(store, event: dict) -> dict:
    kind = event.get("type")
    data = (event.get("data") or {}).get("object") or {}
    if kind == "checkout.session.completed":
        payment_status = data.get("payment_status")
        if payment_status not in ("paid", "no_payment_required"):
            return {"ok": True, "ignored": "unpaid"}
        sponsor = await store.sponsor_by_checkout(data.get("id"))
        if not sponsor:
            log.warning("checkout session %s has no sponsor", data.get("id"))
            return {"ok": True, "ignored": "unknown_session"}
        boost = None
        if sponsor.get("applied_promo_code"):
            try:
                promo = await store.consume_promo(sponsor["applied_promo_code"])
                boost = float(promo["recommendation_boost"])
            except Exception:
                log.exception("promo %s could not be consumed", sponsor.get("applied_promo_code"))
        await store.activate_sponsor(
            sponsor["id"],
            data.get("customer"),
            data.get("subscription"),
            boost,
        )
        return {"ok": True, "sponsor_id": sponsor["id"], "active": True}

    if kind == "identity.verification_session.verified":
        prop = None
        if data.get("id"):
            prop = await store.property_by_identity_session(data["id"])
        if prop is None:
            property_id = (data.get("metadata") or {}).get("property_id")
            if property_id:
                prop = await store.get_property(property_id)
        if prop is None:
            return {"ok": True, "ignored": "unknown_property"}
        await store.set_kyc(prop["id"], True, data.get("id"))
        await refresh_matches_for_property(store, prop["id"])
        return {"ok": True, "property_id": prop["id"], "kyc_verified": True}

    return {"ok": True, "ignored": kind or "unknown"}
