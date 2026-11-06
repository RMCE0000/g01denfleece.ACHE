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


def _field(obj, key: str):
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


async def create_sponsor_checkout(
    sponsor_id: str,
    promo: dict | None,
    customer_email: str | None = None,
    customer_id: str | None = None,
    subscription_id: str | None = None,
) -> dict:
    """Ask Stripe to email a sponsorship invoice.

    A Checkout Session does not email its link. customer_email on that session
    only prefills the page. Stripe emails the customer when an invoice is sent.
    """
    settings = get_settings()
    if not stripe_ready():
        raise G01Error("Stripe is not configured for sponsorship checkout", 503)
    email = (customer_email or "").strip().casefold()
    if not email:
        raise G01Error("Stripe needs an email address before it can send the payment link.", 422)
    stripe = _client()

    def _send() -> dict:
        metadata = {"sponsor_id": sponsor_id, "g01_kind": "sponsor"}
        customer = customer_id
        if customer:
            stripe.Customer.modify(customer, email=email)
        else:
            created = stripe.Customer.create(email=email, metadata=metadata)
            customer = _field(created, "id")
        subscription = subscription_id
        if subscription:
            current = stripe.Subscription.retrieve(subscription, expand=["latest_invoice"])
        else:
            kwargs = {
                "customer": customer,
                "items": [{"price": settings.stripe_sponsor_price_id}],
                "collection_method": "send_invoice",
                "days_until_due": 7,
                "metadata": metadata,
                "expand": ["latest_invoice"],
            }
            if promo and promo.get("stripe_coupon_id"):
                kwargs["discounts"] = [{"coupon": promo["stripe_coupon_id"]}]
            current = stripe.Subscription.create(**kwargs)
            subscription = _field(current, "id")
        invoice = _field(current, "latest_invoice")
        invoice_id = invoice if isinstance(invoice, str) else _field(invoice, "id")
        if invoice_id:
            stripe.Invoice.modify(invoice_id, metadata=metadata)
            if _field(invoice, "status") == "draft":
                invoice = stripe.Invoice.finalize_invoice(invoice_id)
            invoice = stripe.Invoice.send_invoice(invoice_id)
        url = _field(invoice, "hosted_invoice_url")
        if not url or not invoice_id:
            raise G01Error("Stripe did not return a payment link to email.", 502)
        return {
            "id": invoice_id,
            "url": str(url),
            "customer_id": customer,
            "subscription_id": subscription,
            "stripe_emailed": True,
        }

    try:
        return await asyncio.to_thread(_send)
    except G01Error:
        raise
    except Exception as exc:
        log.exception("Stripe did not email a sponsorship invoice for %s", sponsor_id)
        reason = str(exc).strip().splitlines()[0][:240]
        raise G01Error(f"Stripe did not email the payment link to {email}. {reason}".strip(), 502) from exc


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
