"""Real-time LangGraph turn. Gemini Flash may draft prose; scores come from the user's words."""

import json
import logging
from datetime import datetime
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph


class SyncState(TypedDict, total=False):
    message: dict[str, Any]
    property: dict | None
    locality: dict | None
    invites: list
    matches: list
    decision: dict
    reply: str

from app.config import get_settings
from app.constitution import JANE_JSON_INSTRUCTION, JANE_SYSTEM_PROMPT
from app.effects import commit_decision
from app.heuristic import heuristic_decision
from app.llm import complete_json, llm_override
from app.runtime import current_checkpointer, get_store

log = logging.getLogger(__name__)


def _json_ready(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    return value


async def _load_property(store, message: dict):
    if message.get("conversation_id"):
        found = await store.get_property_by_conversation(int(message["conversation_id"]))
        if found:
            return found
    if message.get("contact_id"):
        found = await store.get_property_by_contact(int(message["contact_id"]))
        if found:
            return found
    if message.get("user_id"):
        return await store.get_property_by_user(int(message["user_id"]))
    return None


async def load_context(state: dict) -> dict:
    store = get_store()
    message = state["message"]
    prop = await _load_property(store, message)
    locality = await store.get_locality(prop["locality_id"]) if prop else None
    invites = await store.open_invites_for_property(prop["id"]) if prop else []
    matches = await store.matches_for_property(prop["id"]) if prop else []
    return {
        "property": _json_ready(prop),
        "locality": _json_ready(locality),
        "invites": _json_ready(invites),
        "matches": _json_ready(matches),
    }


async def deliberate(state: dict) -> dict:
    decision = heuristic_decision(state)
    settings = get_settings()
    if llm_override.get() is None and not settings.gemini_api_key:
        return {"decision": decision}
    context = {
        "homesteader_message": (state.get("message") or {}).get("content"),
        "property": state.get("property"),
        "locality": state.get("locality"),
        "open_poll_invites": state.get("invites"),
        "open_matches": state.get("matches"),
        "grounded_actions": decision,
    }
    try:
        raw = await complete_json(
            settings.gemini_chat_model,
            JANE_SYSTEM_PROMPT + "\n" + JANE_JSON_INSTRUCTION,
            json.dumps(context, default=str),
        )
    except Exception:
        log.exception("gemini-2.5-flash turn failed; posting the grounded reply")
        return {"decision": decision}
    if isinstance(raw, dict) and isinstance(raw.get("reply"), str) and raw["reply"].strip():
        decision["reply"] = raw["reply"].strip()
    if isinstance(raw, dict) and isinstance(raw.get("ledger_patch"), dict):
        patch = dict(decision.get("ledger_patch") or {})
        for key, value in raw["ledger_patch"].items():
            if key not in patch:
                patch[key] = value
        decision["ledger_patch"] = patch
    return {"decision": decision}


async def commit(state: dict) -> dict:
    store = get_store()
    snapshot = state.get("property")
    prop = await store.get_property(snapshot["id"]) if snapshot else None
    locality = state.get("locality")
    if prop and locality is None:
        locality = await store.get_locality(prop["locality_id"])
    reply = await commit_decision(store, state["message"], state.get("decision") or {}, prop, locality)
    return {"reply": reply}


def build_sync_peer_graph(checkpointer=None):
    graph = StateGraph(SyncState)
    graph.add_node("load_context", load_context)
    graph.add_node("deliberate", deliberate)
    graph.add_node("commit", commit)
    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "deliberate")
    graph.add_edge("deliberate", "commit")
    graph.add_edge("commit", END)
    return graph.compile(checkpointer=checkpointer if checkpointer is not None else current_checkpointer.get())
