"""Stripe Checkout for sponsors and Stripe Identity for the collaboration gate."""

import asyncio
import logging

from app.config import get_settings
from app.errors import G01Error

log = logging.getLogger(__name__)


def _client():
    import stripe

    settings = get_settings()
    stripe.api_key = settings.stripe_secret_key
    return stripe


def stripe_ready() -> bool:
    settings = get_settings()
    return bool(settings.stripe_secret_key and settings.stripe_sponsor_price_id)


async def create_sponsor_checkout(sponsor_id: str, promo: dict | None, customer_email: str | None = None) -> dict:
    settings = get_settings()
    if not stripe_ready():
        raise G01Error("Stripe is not configured for sponsorship checkout", 503)
    stripe = _client()
    kwargs = {
        "mode": "subscription",
        "line_items": [{"price": settings.stripe_sponsor_price_id, "quantity": 1}],
        "success_url": settings.stripe_success_url,
        "cancel_url": settings.stripe_cancel_url,
        "client_reference_id": sponsor_id,
        "metadata": {"sponsor_id": sponsor_id, "g01_kind": "sponsor"},
    }
    if customer_email:
        kwargs["customer_email"] = customer_email
    if promo:
        kwargs["discounts"] = [{"coupon": promo["stripe_coupon_id"]}]

    session = await asyncio.to_thread(lambda: stripe.checkout.Session.create(**kwargs))
    return {"id": session["id"], "url": session["url"]}


async def retrieve_checkout_url(session_id: str) -> str | None:
    """Return a still-open Checkout URL. An expired or missing session has no URL."""
    if not stripe_ready() or not session_id:
        return None
    stripe = _client()
    try:
        session = await asyncio.to_thread(lambda: stripe.checkout.Session.retrieve(session_id))
    except Exception:
        log.warning("could not retrieve Stripe checkout %s", session_id)
        return None
    status = session.get("status") if isinstance(session, dict) else getattr(session, "status", None)
    url = session.get("url") if isinstance(session, dict) else getattr(session, "url", None)
    if status == "expired" or not url:
        return None
    return str(url)


async def create_identity_session(property_id: str) -> dict:
    settings = get_settings()
    if not settings.stripe_secret_key:
        raise G01Error("Stripe Identity is not configured", 503)
    stripe = _client()
    session = await asyncio.to_thread(
        lambda: stripe.identity.VerificationSession.create(
            type="document",
            metadata={"property_id": property_id, "g01_kind": "kyc"},
            return_url=settings.chatwoot_public_url.rstrip("/") + "/",
        )
    )
    return {"id": session["id"], "url": session["url"]}


def construct_event(payload: bytes, signature: str | None):
    settings = get_settings()
    if not settings.stripe_webhook_secret:
        raise G01Error("Stripe webhook secret is not configured", 503)
    if not signature:
        raise G01Error("missing Stripe signature", 400)
    stripe = _client()
    try:
        return stripe.Webhook.construct_event(payload, signature, settings.stripe_webhook_secret)
    except Exception as exc:
        raise G01Error("invalid Stripe signature", 400) from exc
