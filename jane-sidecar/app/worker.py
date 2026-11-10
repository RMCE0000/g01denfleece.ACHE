"""Celery worker. The minimum showcase leaves the beat schedule empty."""

import asyncio
import logging

from celery import Celery
from celery.schedules import crontab

from app.config import get_settings
from app.jobs import mature_demand_polls, open_ready_collaborations, recount_referral_windows, scan_neighbor_synergies
from app.runtime import open_checkpointer, open_store, set_store, current_checkpointer

log = logging.getLogger(__name__)
settings = get_settings()
celery_app = Celery("g01", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.timezone = "UTC"
celery_app.conf.beat_schedule = (
    {
        "mature-demand-polls": {"task": "app.worker.mature_demand_polls", "schedule": 300.0},
        "scan-neighbor-synergies": {"task": "app.worker.scan_neighbor_synergies", "schedule": 900.0},
        "recount-referral-windows": {"task": "app.worker.recount_referral_windows", "schedule": crontab(minute=15)},
        "open-ready-collaborations": {"task": "app.worker.open_ready_collaborations", "schedule": 300.0},
    }
    if settings.background_jobs
    else {}
)


def _run(job):
    async def _inner():
        store = await open_store(get_settings())
        lease = None
        try:
            set_store(store)
            if get_settings().database_url:
                lease = await open_checkpointer(get_settings().database_url)
                current_checkpointer.set(lease.saver)
            await job(store)
        finally:
            if lease is not None:
                await lease.close()
            await store.close()

    asyncio.run(_inner())


@celery_app.task(name="app.worker.mature_demand_polls")
def mature_demand_polls_task():
    _run(mature_demand_polls)


@celery_app.task(name="app.worker.scan_neighbor_synergies")
def scan_neighbor_synergies_task():
    _run(scan_neighbor_synergies)


@celery_app.task(name="app.worker.recount_referral_windows")
def recount_referral_windows_task():
    _run(recount_referral_windows)


@celery_app.task(name="app.worker.open_ready_collaborations")
def open_ready_collaborations_task():
    _run(open_ready_collaborations)
