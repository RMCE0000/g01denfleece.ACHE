"""FastAPI entrypoint: Chatwoot webhooks, the North Star HUD, and sponsor registration."""

import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from app.config import get_settings
from app.errors import G01Error
from app.northstar import view_from_property
from app.onboarding import signup_homesteader
from app.payments import apply_stripe_event
from app.runtime import current_checkpointer, open_checkpointer, open_store, set_store
from app.sourcing import SPONSOR_TIERS
from app.stripe_service import construct_event, create_identity_session, create_sponsor_checkout
from app.turn import run_turn

log = logging.getLogger("g01")
_UI = Path(__file__).resolve().parent / "ui"


def _peer(prop: dict, contact_id: int, conversation_id: int) -> None:
    if int(prop["chatwoot_contact_id"]) != int(contact_id) or int(prop["primary_conversation_id"]) != int(conversation_id):
        raise G01Error("this homestead thread does not match", 403)


def _admin(request: Request) -> None:
    expected = get_settings().admin_token
    supplied = request.headers.get("x-g01-admin-token", "")
    if not expected or not secrets.compare_digest(supplied, expected):
        raise G01Error("admin token required", 401)


class AestheticIn(BaseModel):
    aesthetic: float = Field(ge=0, le=100)
    contact_id: int
    conversation_id: int


class LaborIn(BaseModel):
    outside_aid_hours_per_week: float = Field(ge=0, le=168)
    contact_id: int
    conversation_id: int


class PromoIn(BaseModel):
    code: str = Field(min_length=3, max_length=64)
    stripe_coupon_id: str
    discount_percent: int = Field(ge=1, le=100)
    recommendation_boost: float = Field(default=1, ge=0.5, le=3)
    restricted_locality_id: str | None = None
    max_uses: int = Field(default=100, ge=1)


class SponsorIn(BaseModel):
    property_id: str
    contact_id: int
    conversation_id: int
    company_name: str = Field(min_length=2, max_length=255)
    founding_city: str
    founding_state: str
    is_franchise_or_chain: bool = False
    sourcing_tier: str
    service_tags: list[str] = Field(min_length=1)
    capabilities_summary: str = Field(min_length=8)
    lat: float
    lng: float
    promo_code: str | None = None


class SignupIn(BaseModel):
    name: str
    email: str
    password: str
    zip_code: str
    street_address: str | None = None
    lat: float | None = None
    lng: float | None = None


def _tags(raw: list[str]) -> list[str]:
    import re

    tags = []
    for item in raw:
        tag = re.sub(r"[^a-z0-9_]+", "_", item.strip().lower().replace("-", "_")).strip("_")
        if not re.fullmatch(r"[a-z0-9_]{2,40}", tag):
            raise G01Error(f"service tag {item!r} is not usable", 422)
        tags.append(tag)
    return tags


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    override = getattr(app.state, "store_override", None)
    store = override if override is not None else await open_store(settings)
    app.state.store = store
    set_store(store)
    lease = None
    if settings.database_url and override is None:
        lease = await open_checkpointer(settings.database_url)
        current_checkpointer.set(lease.saver)
        from app.chatwoot_client import ChatwootClient

        client = ChatwootClient(settings)
        try:
            await client.ensure_webhook()
            await client.ensure_dashboard_app()
        except Exception:
            log.exception("Chatwoot bootstrap did not finish; the sidecar will keep serving")
    try:
        yield
    finally:
        if lease is not None:
            current_checkpointer.set(None)
            await lease.close()
        await store.close()


def create_app(store=None) -> FastAPI:
    app = FastAPI(title="g01 Jane Sidecar", version="0.1.0", lifespan=lifespan)
    app.state.store_override = store

    @app.exception_handler(G01Error)
    async def _g01_error(_request: Request, exc: G01Error):
        return JSONResponse({"detail": exc.message}, status_code=exc.status_code)

    @app.get("/health")
    async def health():
        store_name = type(app.state.store).__name__ if getattr(app.state, "store", None) else "unopened"
        return {"ok": True, "store": store_name, "service": "jane-sidecar"}

    @app.get("/ui/hud", response_class=HTMLResponse)
    async def hud_page():
        return HTMLResponse((_UI / "hud.html").read_text(encoding="utf-8"))

    @app.get("/ui/signup", response_class=HTMLResponse)
    async def signup_page():
        return HTMLResponse((_UI / "signup.html").read_text(encoding="utf-8"))

    @app.get("/api/localities")
    async def localities():
        return {"localities": await app.state.store.list_localities()}

    @app.get("/api/hud/context")
    async def hud_context(contact_id: int, conversation_id: int):
        prop = await app.state.store.get_property_by_contact(contact_id)
        if not prop:
            raise G01Error("no homestead for that contact", 404)
        _peer(prop, contact_id, conversation_id)
        locality = await app.state.store.get_locality(prop["locality_id"])
        return {
            "property_id": prop["id"],
            "locality": locality,
            "kyc_verified": bool(prop["kyc_verified"]),
            "zip_code": prop["zip_code"],
            **view_from_property(prop),
        }

    @app.get("/api/properties/by-contact/{contact_id}/northstar")
    async def northstar_by_contact(contact_id: int, conversation_id: int):
        prop = await app.state.store.get_property_by_contact(contact_id)
        if not prop:
            raise G01Error("property not found", 404)
        _peer(prop, contact_id, conversation_id)
        return view_from_property(prop)

    @app.get("/api/properties/{property_id}/northstar")
    async def northstar(property_id: str, contact_id: int, conversation_id: int):
        prop = await app.state.store.get_property(property_id)
        if not prop:
            raise G01Error("property not found", 404)
        _peer(prop, contact_id, conversation_id)
        return view_from_property(prop)

    @app.patch("/api/properties/{property_id}/aesthetic")
    async def patch_aesthetic(property_id: str, body: AestheticIn):
        prop = await app.state.store.get_property(property_id)
        if not prop:
            raise G01Error("property not found", 404)
        _peer(prop, body.contact_id, body.conversation_id)
        updated = await app.state.store.update_aesthetic(property_id, body.aesthetic)
        return view_from_property(updated)

    @app.patch("/api/properties/{property_id}/labor-hours")
    async def patch_labor(property_id: str, body: LaborIn):
        prop = await app.state.store.get_property(property_id)
        if not prop:
            raise G01Error("property not found", 404)
        _peer(prop, body.contact_id, body.conversation_id)
        updated = await app.state.store.update_labor_hours(property_id, body.outside_aid_hours_per_week)
        return view_from_property(updated)

    @app.get("/api/properties/{property_id}/sponsors")
    async def preview_sponsors(property_id: str, service_tag: str, contact_id: int, conversation_id: int):
        prop = await app.state.store.get_property(property_id)
        if not prop:
            raise G01Error("property not found", 404)
        _peer(prop, contact_id, conversation_id)
        rows = await app.state.store.rank_sponsors(property_id, service_tag, limit=5)
        return {
            "tier_1": {"name": "homestead fabrication", "tier_weight": 1.0},
            "sponsors": rows,
        }

    @app.post("/api/sponsors")
    async def create_sponsor(body: SponsorIn):
        if body.sourcing_tier not in SPONSOR_TIERS:
            raise G01Error("sourcing tier must be local_manufacturer, local_service_or_stock, or local_logistics_proxy", 422)
        prop = await app.state.store.get_property(body.property_id)
        if not prop:
            raise G01Error("property not found", 404)
        _peer(prop, body.contact_id, body.conversation_id)
        promo = None
        if body.promo_code:
            promo = await app.state.store.get_promo(body.promo_code)
            if not promo or not promo["active"] or promo["current_uses"] >= promo["max_uses"]:
                raise G01Error("promo code is not usable", 422)
            if promo.get("restricted_locality_id") and promo["restricted_locality_id"] != prop["locality_id"]:
                raise G01Error("promo code is for a different locality", 422)
        sponsor = await app.state.store.create_sponsor(
            {
                "property_id": prop["id"],
                "locality_id": prop["locality_id"],
                "company_name": body.company_name,
                "founding_city": body.founding_city,
                "founding_state": body.founding_state,
                "is_franchise_or_chain": body.is_franchise_or_chain,
                "sourcing_tier": body.sourcing_tier,
                "service_tags": _tags(body.service_tags),
                "capabilities_summary": body.capabilities_summary,
                "lat": body.lat,
                "lng": body.lng,
                "applied_promo_code": promo["code"] if promo else None,
                "is_active_sponsor": False,
            }
        )
        checkout = await create_sponsor_checkout(sponsor["id"], promo)
        await app.state.store.attach_checkout(checkout["id"], sponsor["id"])
        return {"sponsor_id": sponsor["id"], "is_active_sponsor": False, "checkout_url": checkout["url"]}

    @app.post("/api/properties/{property_id}/kyc/session")
    async def kyc_session(property_id: str, contact_id: int, conversation_id: int):
        prop = await app.state.store.get_property(property_id)
        if not prop:
            raise G01Error("property not found", 404)
        _peer(prop, contact_id, conversation_id)
        session = await create_identity_session(property_id)
        await app.state.store.set_identity_session(property_id, session["id"])
        return session

    @app.post("/api/signup")
    async def signup(body: SignupIn):
        prop = await signup_homesteader(app.state.store, body.model_dump())
        return {"property_id": prop["id"], "conversation_id": prop["primary_conversation_id"], **view_from_property(prop)}

    @app.post("/api/admin/promo-codes")
    async def create_promo(body: PromoIn, request: Request):
        _admin(request)
        promo = await app.state.store.create_promo(body.model_dump())
        return promo

    @app.post("/webhooks/chatwoot")
    async def chatwoot_webhook(request: Request):
        settings = get_settings()
        if settings.chatwoot_webhook_secret:
            supplied = request.query_params.get("token") or request.headers.get("x-g01-webhook-token", "")
            if not secrets.compare_digest(supplied, settings.chatwoot_webhook_secret):
                raise G01Error("webhook token rejected", 401)
        payload = await request.json()
        return await run_turn(app.state.store, payload)

    @app.post("/webhooks/stripe")
    async def stripe_webhook(request: Request):
        payload = await request.body()
        event = construct_event(payload, request.headers.get("stripe-signature"))
        if hasattr(event, "to_dict"):
            event = event.to_dict()
        return await apply_stripe_event(app.state.store, event)

    return app


app = create_app()
