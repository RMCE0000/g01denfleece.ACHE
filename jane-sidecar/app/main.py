"""FastAPI entrypoint. Homesteaders use the Chatwoot thread. This process is webhooks and admin only."""

import asyncio
import logging
import secrets
from contextlib import asynccontextmanager
from contextlib import suppress
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.community import bridge_actor, community_state, start_connection
from app.config import get_settings
from app.errors import G01Error
from app.homesteaders import open_peer_conversation, provision_homesteader, register_homesteader, sync_workspace_metadata
from app.jobs import collaboration_scheduler, demand_poll_scheduler
from app.matchmaking import matchmaking_scheduler
from app.payments import apply_stripe_event
from app.polling import poll_scheduler
from app.runtime import current_checkpointer, open_checkpointer, open_store, set_store
from app.stripe_service import construct_event
from app.showcase import list_conversations
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
    username: str | None = Field(default=None, min_length=3, max_length=32)
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


class CommunityConnectionIn(BaseModel):
    username: str = Field(min_length=3, max_length=33)
    topic: str | None = Field(default=None, max_length=255)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    override = getattr(app.state, "store_override", None)
    store = override if override is not None else await open_store(settings)
    app.state.store = store
    set_store(store)
    lease = None
    poll_task = None
    demand_poll_task = None
    match_task = None
    collaboration_task = None
    if settings.database_url and override is None:
        lease = await open_checkpointer(settings.database_url)
        current_checkpointer.set(lease.saver)
        from app.chatwoot_client import ChatwootClient

        client = ChatwootClient(settings)
        try:
            await client.ensure_webhook()
        except Exception:
            log.exception("Chatwoot webhook registration did not finish; the sidecar will keep serving")
        try:
            await sync_workspace_metadata(store)
        except Exception:
            log.exception("Chatwoot workspace metadata synchronization did not finish")
        if settings.seed_homesteaders and settings.chatwoot_api_token and settings.chatwoot_platform_token:
            from app.homestead_seed import seed_signed_in_homesteaders

            try:
                await seed_signed_in_homesteaders(store)
            except Exception:
                log.exception("signed-in homesteader seed did not finish")
    if override is None:
        poll_task = asyncio.create_task(poll_scheduler(store, settings), name="jane-poll-scheduler")
        demand_poll_task = asyncio.create_task(
            demand_poll_scheduler(store, settings),
            name="jane-demand-poll-scheduler",
        )
        if settings.automatic_matchmaking_enabled:
            match_task = asyncio.create_task(matchmaking_scheduler(store, settings), name="jane-match-scheduler")
        collaboration_task = asyncio.create_task(
            collaboration_scheduler(store, settings),
            name="jane-collaboration-scheduler",
        )
    try:
        yield
    finally:
        if poll_task is not None:
            poll_task.cancel()
            with suppress(asyncio.CancelledError):
                await poll_task
        if demand_poll_task is not None:
            demand_poll_task.cancel()
            with suppress(asyncio.CancelledError):
                await demand_poll_task
        if match_task is not None:
            match_task.cancel()
            with suppress(asyncio.CancelledError):
                await match_task
        if collaboration_task is not None:
            collaboration_task.cancel()
            with suppress(asyncio.CancelledError):
                await collaboration_task
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
        return {
            "ok": True,
            "store": store_name,
            "service": "jane-sidecar",
            "showcase": "minimum",
            "llm": "gemini",
            "gemini_configured": bool(app.state.settings.gemini_api_key),
            "gemini_chat_model": app.state.settings.gemini_chat_model,
            "gemini_deliberation_model": app.state.settings.gemini_deliberation_model,
            "audio_transcription_enabled": app.state.settings.audio_transcription_enabled,
        }

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

    @app.get("/api/admin/conversations")
    async def list_admin_conversations(request: Request):
        _admin(request)
        return await list_conversations(app.state.store)

    @app.post("/api/admin/conversations")
    async def create_peer_conversation(body: PeerIn, request: Request):
        _admin(request)
        return await open_peer_conversation(app.state.store, body.left, body.right, body.topic)

    @app.get("/api/internal/community")
    async def community_members(request: Request):
        actor = await bridge_actor(app.state.store, request, get_settings().bridge_secret)
        return await community_state(app.state.store, actor)

    @app.post("/api/internal/community/connections")
    async def community_connection(body: CommunityConnectionIn, request: Request, response: Response):
        actor = await bridge_actor(app.state.store, request, get_settings().bridge_secret)
        opened = await start_connection(app.state.store, actor, body.username, body.topic)
        response.status_code = 200 if opened["existing"] else 201
        return opened

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
