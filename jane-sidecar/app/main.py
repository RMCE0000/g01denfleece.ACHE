"""FastAPI entrypoint. Homesteaders use the Chatwoot thread. This process is webhooks and admin only."""

import logging
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.config import get_settings
from app.errors import G01Error
from app.homesteaders import open_peer_conversation, provision_homesteader, register_homesteader
from app.payments import apply_stripe_event
from app.runtime import current_checkpointer, open_checkpointer, open_store, set_store
from app.stripe_service import construct_event
from app.turn import run_turn

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("g01")


def _admin(request: Request) -> None:
    expected = get_settings().admin_token
    supplied = request.headers.get("x-g01-admin-token", "")
    if not expected or not secrets.compare_digest(supplied, expected):
        raise G01Error("admin token required", 401)


class HomesteaderIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    zip_code: str = Field(min_length=5, max_length=12)


class PeerIn(BaseModel):
    left: str = Field(min_length=1, max_length=255)
    right: str = Field(min_length=1, max_length=255)
    topic: str | None = Field(default=None, max_length=255)


class PromoIn(BaseModel):
    code: str = Field(min_length=3, max_length=64)
    stripe_coupon_id: str
    discount_percent: int = Field(ge=1, le=100)
    recommendation_boost: float = Field(default=1, ge=0.5, le=3)
    restricted_locality_id: str | None = None
    max_uses: int = Field(default=100, ge=1)


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
        except Exception:
            log.exception("Chatwoot webhook registration did not finish; the sidecar will keep serving")
        if settings.seed_homesteaders and settings.chatwoot_api_token and settings.chatwoot_platform_token:
            from app.homestead_seed import seed_signed_in_homesteaders

            try:
                await seed_signed_in_homesteaders(store)
            except Exception:
                log.exception("signed-in homesteader seed did not finish")
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

    @app.post("/api/admin/promo-codes")
    async def create_promo(body: PromoIn, request: Request):
        _admin(request)
        return await app.state.store.create_promo(body.model_dump())

    @app.post("/api/signup")
    async def signup(body: HomesteaderIn):
        return await register_homesteader(app.state.store, body.model_dump())

    @app.post("/api/admin/homesteaders")
    async def create_homesteader(body: HomesteaderIn, request: Request):
        _admin(request)
        return await provision_homesteader(app.state.store, body.model_dump())

    @app.post("/api/admin/conversations")
    async def create_peer_conversation(body: PeerIn, request: Request):
        _admin(request)
        return await open_peer_conversation(app.state.store, body.left, body.right, body.topic)

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
