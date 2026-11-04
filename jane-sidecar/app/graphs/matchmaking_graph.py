"""Grounded neighbor discovery. New proposals wait for operator review."""

import json
import logging
import math
import re
from typing import TypedDict

from langgraph.graph import END, START, StateGraph


class MatchState(TypedDict, total=False):
    created_match_ids: list

from app.config import get_settings
from app.constitution import JANE_SYSTEM_PROMPT
from app.llm import complete_json, embed_text, llm_override
from app.runtime import current_checkpointer, get_store, set_store

log = logging.getLogger(__name__)


def _goals(prop: dict) -> list[str]:
    return [
        str(item).strip().rstrip(".!?")
        for item in (prop.get("known_facts_ledger") or {}).get("active_goals") or []
        if str(item).strip()
    ]


_MATCH_STOP_WORDS = {
    "about", "after", "again", "could", "first", "from", "have", "help",
    "homestead", "local", "need", "project", "shared", "should", "that",
    "their", "there", "these", "thing", "this", "want", "what", "with",
    "would",
}


def _goal_terms(prop: dict) -> set[str]:
    return {
        word
        for goal in _goals(prop)
        for word in re.findall(r"[a-z][a-z0-9'-]{3,}", goal.casefold())
        if word not in _MATCH_STOP_WORDS
    }


def _overlap(left: dict, right: dict) -> list[str]:
    shared = {item.casefold() for item in _goals(left)} & {item.casefold() for item in _goals(right)}
    if shared:
        return sorted(shared)
    terms = _goal_terms(left) & _goal_terms(right)
    if len(terms) >= 2 or any(len(term) >= 8 for term in terms):
        return sorted(terms)
    return []


def _cosine(left: list[float] | None, right: list[float] | None) -> float | None:
    if not left or not right or len(left) != len(right):
        return None
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return None
    return dot / (left_norm * right_norm)


def _template(left: dict, right: dict, overlap: list[str], similarity: float | None) -> str:
    left_goals = ", ".join(_goals(left)) or "none recorded"
    right_goals = ", ".join(_goals(right)) or "none recorded"
    shared = ", ".join(overlap) if overlap else "none"
    sim = f" Embedding cosine is {similarity:.3f}." if similarity is not None else ""
    return (
        f"Recorded goals for one homestead: {left_goals}. "
        f"Recorded goals for the other: {right_goals}. "
        f"Shared goal text: {shared}.{sim} "
        "I am not adding a project they did not write down."
    )


def _grounded(prose: str, allowed: str) -> bool:
    words = set(re.findall(r"[a-z]{5,}", prose.casefold()))
    known = set(re.findall(r"[a-z]{5,}", allowed.casefold()))
    known.update({"homestead", "recorded", "goals", "shared", "locality", "embedding", "cosine", "project", "thread"})
    return bool(prose.strip()) and words <= known


async def _rationale(left: dict, right: dict, overlap: list[str], similarity: float | None) -> str:
    template = _template(left, right, overlap, similarity)
    settings = get_settings()
    if llm_override.get() is None and not settings.gemini_api_key:
        return template
    try:
        raw = await complete_json(
            settings.gemini_deliberation_model,
            JANE_SYSTEM_PROMPT + "\nReturn JSON {\"rationale\": string}. Use only the recorded goals.",
            json.dumps({"template": template}, default=str),
        )
    except Exception:
        log.exception("matchmaking deliberation failed")
        return template
    prose = raw.get("rationale") if isinstance(raw, dict) else ""
    if isinstance(prose, str) and _grounded(prose, template):
        return prose.strip()
    return template


async def scan_and_queue(state: dict) -> dict:
    store = get_store()
    settings = get_settings()
    created: list[str] = []
    properties = await store.properties_with_goals()
    for prop in properties:
        if prop.get("goals_embedding"):
            continue
        text = " ".join(_goals(prop))
        vector = await embed_text(text)
        if vector:
            await store.set_goals_embedding(prop["id"], vector)
            prop["goals_embedding"] = vector

    by_locality: dict[str, list[dict]] = {}
    for prop in properties:
        by_locality.setdefault(prop["locality_id"], []).append(prop)

    for locality_id, group in by_locality.items():
        for index, left in enumerate(group):
            for right in group[index + 1 :]:
                if await store.find_peer_between(left["id"], right["id"]):
                    continue
                overlap = _overlap(left, right)
                similarity = _cosine(left.get("goals_embedding"), right.get("goals_embedding"))
                vector_hit = similarity is not None and similarity >= settings.match_similarity_threshold
                if not overlap and not vector_hit:
                    continue
                title = " / ".join(overlap)[:255] if overlap else "shared recorded goals"
                rationale = await _rationale(left, right, overlap, similarity)
                match = await store.create_match(
                    {
                        "locality_id": locality_id,
                        "peer_a_property_id": left["id"],
                        "peer_b_property_id": right["id"],
                        "proposed_project_title": title,
                        "jane_synergy_rationale": rationale,
                    }
                )
                if not match:
                    continue
                created.append(match["id"])
    return {"created_match_ids": created}


async def discover_neighbor_synergies(store) -> list[str]:
    set_store(store)
    result = await scan_and_queue({})
    return list(result.get("created_match_ids") or [])


def build_matchmaking_graph(checkpointer=None):
    graph = StateGraph(MatchState)
    graph.add_node("scan_and_queue", scan_and_queue)
    graph.add_edge(START, "scan_and_queue")
    graph.add_edge("scan_and_queue", END)
    return graph.compile(checkpointer=checkpointer if checkpointer is not None else current_checkpointer.get())
