"""Apply signed Stripe events. KYC becomes true only on a verified Identity session."""

import logging
from uuid import UUID

from app.collaboration import refresh_matches_for_property
from app.errors import G01Error

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
        session_id = data.get("id")
        sponsor = await store.sponsor_by_checkout(session_id)
        if sponsor is None:
            sponsor_id = (data.get("metadata") or {}).get("sponsor_id") or data.get("client_reference_id")
            if sponsor_id:
                try:
                    sponsor_id = str(UUID(str(sponsor_id)))
                except (TypeError, ValueError):
                    sponsor_id = None
                sponsor = await store.get_sponsor(sponsor_id) if sponsor_id else None
                if sponsor is not None and session_id:
                    await store.attach_checkout(session_id, sponsor["id"])
        if not sponsor:
            log.warning("checkout session %s has no sponsor", data.get("id"))
            raise G01Error("checkout sponsor mapping is not ready", 503)
        await store.activate_sponsor_checkout(
            sponsor["id"],
            data.get("customer"),
            data.get("subscription"),
        )
        return {"ok": True, "sponsor_id": sponsor["id"], "active": True}

    if kind in ("customer.subscription.updated", "customer.subscription.deleted"):
        subscription_id = data.get("id")
        if not subscription_id:
            return {"ok": True, "ignored": "missing_subscription"}
        active = kind != "customer.subscription.deleted" and data.get("status") in ("active", "trialing")
        sponsor = await store.set_sponsor_subscription_active(subscription_id, active)
        if sponsor is None:
            return {"ok": True, "ignored": "unknown_subscription"}
        return {"ok": True, "sponsor_id": sponsor["id"], "active": active}

    if kind in ("invoice.payment_failed", "invoice.paid", "invoice.payment_succeeded"):
        subscription_id = data.get("subscription")
        if not subscription_id:
            subscription_id = (((data.get("parent") or {}).get("subscription_details") or {}).get("subscription"))
        if not subscription_id:
            return {"ok": True, "ignored": "missing_subscription"}
        active = kind != "invoice.payment_failed"
        sponsor = await store.set_sponsor_subscription_active(subscription_id, active)
        if sponsor is None:
            return {"ok": True, "ignored": "unknown_subscription"}
        return {"ok": True, "sponsor_id": sponsor["id"], "active": active}

    if kind == "identity.verification_session.verified":
        prop = None
        if data.get("id"):
            prop = await store.property_by_identity_session(data["id"])
        if prop is None:
            property_id = (data.get("metadata") or {}).get("property_id")
            if property_id:
                try:
                    property_id = str(UUID(str(property_id)))
                except (TypeError, ValueError):
                    property_id = None
                prop = await store.get_property(property_id) if property_id else None
        if prop is None:
            raise G01Error("identity property mapping is not ready", 503)
        await store.set_kyc(prop["id"], True, data.get("id"))
        await refresh_matches_for_property(store, prop["id"])
        return {"ok": True, "property_id": prop["id"], "kyc_verified": True}

    return {"ok": True, "ignored": kind or "unknown"}
