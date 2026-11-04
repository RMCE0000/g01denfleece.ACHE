"""Automatic match discovery with an operator approval gate."""

from __future__ import annotations

import asyncio
import logging
import re

from app.collaboration import refresh_match_gate
from app.config import Settings, get_settings
from app.delivery import deliver
from app.errors import G01Error
from app.graphs.matchmaking_graph import discover_neighbor_synergies

log = logging.getLogger(__name__)

_MATCH_DECISION = re.compile(
    r"^\s*(yes|no)\s+([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\s*$",
    re.I,
)


def _pitch(match: dict, locality_name: str) -> str:
    return (
        f"Someone else in {locality_name} has a recorded goal that lines up with yours "
        f"({match['proposed_project_title']}). {match['jane_synergy_rationale']} "
        f"Reply YES {match['id']} to accept or NO {match['id']} to decline. "
        "An operator approved this introduction. I will open a shared thread only after "
        "both of you accept and both pass identity verification. I am not sharing either street address."
    )


async def approve_match(store, match_id: str, note: str | None = None) -> dict:
    match = await store.get_match(match_id)
    if match is None:
        raise G01Error("match not found", 404)
    if match["operator_status"] != "pending":
        raise G01Error(f"match is already {match['operator_status']}", 409)
    approved = await store.set_match_operator_status(match_id, "approved", note)
    locality = await store.get_locality(approved["locality_id"])
    place = locality["name"] if locality else "this locality"
    message = _pitch(approved, place)
    delivered_to = []
    for property_id in (approved["peer_a_property_id"], approved["peer_b_property_id"]):
        prop = await store.get_property(property_id)
        if prop and prop.get("primary_conversation_id") is not None:
            await deliver(store, int(prop["primary_conversation_id"]), message)
            delivered_to.append(property_id)
    return {"match": approved, "pitched_property_ids": delivered_to}


async def reject_match(store, match_id: str, note: str | None = None) -> dict:
    match = await store.get_match(match_id)
    if match is None:
        raise G01Error("match not found", 404)
    if match["operator_status"] != "pending":
        raise G01Error(f"match is already {match['operator_status']}", 409)
    return await store.set_match_operator_status(match_id, "rejected", note)


async def handle_private_match_message(store, message: dict) -> str | None:
    decision = _MATCH_DECISION.fullmatch(str(message.get("content") or ""))
    if decision is None:
        return None
    conversation_id = int(message["conversation_id"])
    prop = await store.get_property_by_conversation(conversation_id)
    if prop is None:
        return None
    match = await store.get_match(decision.group(2))
    await store.append_transcript(
        conversation_id=conversation_id,
        message_id=str(message.get("message_id") or "") or None,
        role="homesteader",
        speaker=message.get("speaker") or "Homesteader",
        content=str(message.get("content") or ""),
    )
    if (
        match is None
        or match.get("operator_status") != "approved"
        or prop["id"] not in (match["peer_a_property_id"], match["peer_b_property_id"])
    ):
        reply = "I can't record that match response. Use the exact YES or NO line from an operator-approved proposal."
        await deliver(store, conversation_id, reply)
        return reply
    status = "accepted" if decision.group(1).casefold() == "yes" else "declined"
    await store.set_match_status(match["id"], prop["id"], status)
    reply = await refresh_match_gate(store, match["id"], speaker_property_id=prop["id"])
    await deliver(store, conversation_id, reply)
    return reply


async def matchmaking_scheduler(store, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    while True:
        try:
            await discover_neighbor_synergies(store)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("automatic match discovery failed")
        await asyncio.sleep(settings.match_scheduler_interval_seconds)
