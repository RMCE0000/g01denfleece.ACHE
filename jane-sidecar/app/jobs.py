"""Scheduled work shared by Celery and tests."""

import asyncio
import logging

from app.config import Settings, get_settings
from app.collaboration import refresh_match_gate
from app.graphs.demand_poll_graph import build_demand_poll_graph
from app.graphs.matchmaking_graph import discover_neighbor_synergies
from app.runtime import set_store

log = logging.getLogger(__name__)


async def mature_demand_polls(store) -> list[str]:
    set_store(store)
    graph = build_demand_poll_graph()
    reports = []
    for poll in await store.mature_polls():
        result = await graph.ainvoke(
            {"poll_id": poll["id"]},
            config={"configurable": {"thread_id": f"demand-poll:{poll['id']}"}},
        )
        if result.get("report"):
            reports.append(result["report"])
    return reports


async def demand_poll_scheduler(store, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    while True:
        try:
            await mature_demand_polls(store)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("demand poll cycle failed")
        await asyncio.sleep(settings.demand_poll_scheduler_interval_seconds)


async def scan_neighbor_synergies(store) -> list[str]:
    return await discover_neighbor_synergies(store)


async def recount_referral_windows(store) -> None:
    await store.recount_referrals()


async def open_ready_collaborations(store) -> list[int]:
    set_store(store)
    opened = []
    for match in await store.ready_matches_without_thread():
        await refresh_match_gate(store, match["id"])
        current = await store.get_match(match["id"])
        if current and current.get("shared_chatwoot_conversation_id"):
            opened.append(int(current["shared_chatwoot_conversation_id"]))
    return opened


async def collaboration_scheduler(store, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    while True:
        try:
            await open_ready_collaborations(store)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("collaboration retry cycle failed")
        await asyncio.sleep(settings.collaboration_scheduler_interval_seconds)
