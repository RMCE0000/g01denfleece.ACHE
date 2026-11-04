"""T+24h demand synthesis. Gemini Pro may phrase the report; it may not add numbers."""

import json
import logging
import re
from typing import TypedDict

from langgraph.graph import END, START, StateGraph


class PollState(TypedDict, total=False):
    poll_id: str
    report: str

from app.config import get_settings
from app.constitution import JANE_SYSTEM_PROMPT
from app.delivery import deliver
from app.llm import complete_json, llm_override
from app.runtime import current_checkpointer, get_store
from app.sanitize import sanitize_reply

log = logging.getLogger(__name__)


def factual_report(poll: dict, votes: list[dict]) -> str:
    topic = poll["topic_slug"].replace("_", " ")
    if not votes:
        return (
            f"The 24 hours are up for {topic}. No neighbors answered. "
            "I will not invent a demand figure."
        )
    units = sum(float(vote["weekly_units_demanded"] or 0) for vote in votes)
    prices = [float(vote["willing_price_per_unit_usd"] or 0) for vote in votes if float(vote["willing_price_per_unit_usd"] or 0) > 0]
    if prices:
        average = sum(prices) / len(prices)
        price_sentence = f"Among the prices they named, the average is ${average:.2f}."
    else:
        price_sentence = "Nobody named a price."
    return (
        f"The 24 hours are up for {topic}. {len(votes)} neighbor(s) answered. "
        f"The weekly units they stated add up to {units:.2f}. {price_sentence} "
        "This is only what they wrote, not a forecast."
    )


async def _phrase(poll: dict, votes: list[dict], template: str) -> str:
    settings = get_settings()
    if llm_override.get() is None and not settings.gemini_api_key:
        return template
    try:
        raw = await complete_json(
            settings.gemini_deliberation_model,
            JANE_SYSTEM_PROMPT + "\nReturn JSON {\"report\": string}. Use only numbers present in the factual report.",
            json.dumps({"factual_report": template, "votes": votes, "poll": {"topic_slug": poll["topic_slug"]}}, default=str),
        )
    except Exception:
        log.exception("demand synthesis model failed")
        return template
    prose = ""
    if isinstance(raw, dict):
        prose = raw.get("report") or raw.get("reply") or ""
    allowed = set(re.findall(r"\d+(?:\.\d+)?", template))
    used = set(re.findall(r"\d+(?:\.\d+)?", prose))
    if not prose or used - allowed:
        return template
    return sanitize_reply(prose) or template


async def synthesize(state: dict) -> dict:
    store = get_store()
    poll = await store.get_poll(state["poll_id"])
    if not poll or poll["status"] != "polling":
        return {"report": ""}
    votes = await store.votes_for_poll(poll["id"])
    template = factual_report(poll, votes)
    report = await _phrase(poll, votes, template)
    completed = await store.complete_poll(poll["id"], report)
    if completed is None:
        return {"report": ""}
    requester = await store.get_property(poll["requester_property_id"])
    if requester and requester.get("primary_conversation_id"):
        await deliver(store, requester["primary_conversation_id"], report)
    return {"report": report}


def build_demand_poll_graph(checkpointer=None):
    graph = StateGraph(PollState)
    graph.add_node("synthesize", synthesize)
    graph.add_edge(START, "synthesize")
    graph.add_edge("synthesize", END)
    return graph.compile(checkpointer=checkpointer if checkpointer is not None else current_checkpointer.get())
