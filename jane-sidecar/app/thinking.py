"""Show Jane as thinking in the open thread until her reply is posted.

Chatwoot clears a typing signal after 30 seconds, so the signal is refreshed
until the turn finishes.
"""

import asyncio
import logging

from app.chatwoot_client import ChatwootClient
from app.config import get_settings

log = logging.getLogger(__name__)

PULSE_SECONDS = 20
_sessions: dict[int, int] = {}
_stops: dict[int, asyncio.Event] = {}
_tasks: dict[int, asyncio.Task] = {}


async def start_thinking(conversation_id: int | None) -> None:
    if conversation_id is None:
        return
    conversation_id = int(conversation_id)
    _sessions[conversation_id] = _sessions.get(conversation_id, 0) + 1
    if _sessions[conversation_id] > 1:
        return
    stop = asyncio.Event()
    _stops[conversation_id] = stop
    _tasks[conversation_id] = asyncio.create_task(_pulse(conversation_id, stop))
    await asyncio.sleep(0)


async def stop_thinking(conversation_id: int | None) -> None:
    if conversation_id is None:
        return
    conversation_id = int(conversation_id)
    count = _sessions.get(conversation_id, 0)
    if count <= 0:
        return
    if count > 1:
        _sessions[conversation_id] = count - 1
        return
    _sessions.pop(conversation_id, None)
    stop = _stops.pop(conversation_id, None)
    task = _tasks.pop(conversation_id, None)
    if stop is not None:
        stop.set()
    if task is not None:
        await task


async def _pulse(conversation_id: int, stop: asyncio.Event) -> None:
    client = ChatwootClient(get_settings())
    try:
        while not stop.is_set():
            await client.set_typing(conversation_id, True)
            if stop.is_set():
                break
            try:
                await asyncio.wait_for(stop.wait(), PULSE_SECONDS)
            except TimeoutError:
                continue
    finally:
        await client.set_typing(conversation_id, False)
