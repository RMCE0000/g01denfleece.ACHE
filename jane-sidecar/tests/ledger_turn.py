"""The ledger graph, kept off the live webhook. The minimum showcase does not call it."""

import asyncio

from app.graphs.sync_peer_graph import build_sync_peer_graph
from app.runtime import set_store
from app.turn import extract_message, ignore_reason


async def run_ledger_turn(store, payload: dict) -> dict:
    set_store(store)
    message = extract_message(payload)
    reason = ignore_reason(message)
    if reason:
        return {"ok": True, "ignored": reason}
    event_id = f"cw:{message.get('message_id')}:{message.get('conversation_id')}"
    message["event_id"] = event_id
    if not await store.mark_event(event_id):
        return {"ok": True, "duplicate": True}
    try:
        result = await build_sync_peer_graph().ainvoke({"message": message})
    except Exception:
        await store.unmark_event(event_id)
        raise
    return {"ok": True, "reply": result.get("reply", "")}


class _Response:
    def __init__(self, payload: dict):
        self.status_code = 200
        self._payload = payload

    def json(self):
        return self._payload


def ledger_reply(store, payload: dict) -> _Response:
    return _Response(asyncio.run(run_ledger_turn(store, payload)))
