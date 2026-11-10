"""Jane's private-thread daily and on-demand community polls."""

from __future__ import annotations

import asyncio
import logging
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.config import Settings, get_settings
from app.delivery import deliver
from app.economy import choose_conversation_question, choose_daily_question

log = logging.getLogger(__name__)

DEFAULT_POLL_MODE_QUESTION = "What action or project should this community organize next?"
_POLL_MODE = re.compile(r"^\s*poll\s+mode(?:\s*:\s*(.*))?\s*$", re.I | re.S)
_WORDS = re.compile(r"[a-z][a-z0-9'-]{2,}", re.I)
_STOP_WORDS = {
    "and", "are", "but", "can", "could", "for", "from", "have", "into", "just",
    "need", "our", "should", "that", "the", "their", "them", "then", "this",
    "want", "with", "would", "your",
}


def _now(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    return current.replace(tzinfo=timezone.utc) if current.tzinfo is None else current


def _local_day(now: datetime, settings: Settings):
    return now.astimezone(ZoneInfo(settings.poll_timezone)).date()


_POLL_STATUS = re.compile(
    r"\b(?:do you have|got any|any polls?|polls? for me|what polls?)\b",
    re.I,
)
_COMMUNITY_ASK = re.compile(
    r"\b(?:does|do|would)\s+(?:anybody|anyone|any of you)\b"
    r"|\bwho\s+(?:wants|needs)\b"
    r"|\bwill\s+(?:anybody|anyone)\b"
    r"|\bask\s+(?:the\s+)?(?:community|neighbors|other homesteads|homesteads)\b"
    r"|\b(?:take|run|start)\s+a\s+poll\b"
    r"|\bpoll\s+the\b",
    re.I,
)
def wants_community(text: str) -> bool:
    """True when they are asking the other homesteads something. The harness writes the question."""
    cleaned = " ".join((text or "").split())
    return bool(cleaned and _COMMUNITY_ASK.search(cleaned))


def _poll_prompt(question: str) -> str:
    return f"{question}\nYou can answer here."


def _asked_confirmation(question: str) -> str:
    return f"I asked the other homesteads: {question}"


async def _deliver_added(store, poll: dict, recipients: list[dict]) -> None:
    prompt = _poll_prompt(poll["question"])
    requester = poll.get("requester_property_id")
    for recipient in recipients:
        if requester and recipient.get("property_id") == requester:
            continue
        conversation_id = recipient.get("conversation_id")
        if conversation_id is not None:
            await deliver(store, int(conversation_id), prompt)


async def _add_current_homesteaders(store, poll: dict, properties: list[dict] | None = None) -> list[dict]:
    if properties is None:
        properties = [
            prop
            for prop in await store.list_properties()
            if prop.get("primary_conversation_id") is not None
        ]
    added = await store.add_community_poll_recipients(poll["id"], properties)
    if poll.get("status") == "open":
        await _deliver_added(store, poll, added)
    return added


async def ensure_daily_poll(
    store,
    settings: Settings | None = None,
    *,
    now: datetime | None = None,
) -> dict:
    settings = settings or get_settings()
    current = _now(now)
    local = current.astimezone(ZoneInfo(settings.poll_timezone))
    day = local.date()
    next_midnight = datetime.combine(
        day + timedelta(days=1),
        datetime.min.time(),
        tzinfo=local.tzinfo,
    ).astimezone(timezone.utc)
    properties = [
        prop
        for prop in await store.list_properties()
        if prop.get("primary_conversation_id") is not None and prop.get("zip_code")
    ]
    by_zip: dict[str, list[dict]] = {}
    for prop in properties:
        by_zip.setdefault(str(prop["zip_code"]), []).append(prop)
    polls = []
    created_any = False
    added_total = 0
    for zip_code, group in sorted(by_zip.items()):
        lines = await store.homesteader_transcripts(
            [int(prop["primary_conversation_id"]) for prop in group]
        )
        question = choose_daily_question(zip_code, day, group, lines)
        poll, created = await store.create_community_poll(
            {
                "poll_key": f"daily:{zip_code}:{day.isoformat()}",
                "poll_kind": "daily",
                "question": question,
                "opens_at": current,
                "closes_at": next_midnight,
            }
        )
        added = await _add_current_homesteaders(store, poll, group)
        for recipient in added:
            prop = next(row for row in group if row["id"] == recipient["property_id"])
            await store.save_economy_note(
                {
                    "property_id": prop["id"],
                    "zip_code": zip_code,
                    "poll_id": poll["id"],
                    "source": "daily",
                    "question": poll["question"],
                    "answer": None,
                }
            )
        polls.append(poll)
        created_any = created_any or created
        added_total += len(added)
    return {
        "poll": polls[0] if polls else None,
        "polls": polls,
        "created": created_any,
        "recipients_added": added_total,
    }


async def create_requested_poll(
    store,
    requester: dict,
    question: str,
    settings: Settings | None = None,
    *,
    now: datetime | None = None,
) -> dict:
    settings = settings or get_settings()
    current = _now(now)
    cleaned = " ".join(str(question or "").split()).strip()
    if not cleaned:
        cleaned = DEFAULT_POLL_MODE_QUESTION
    if len(cleaned) > 500:
        cleaned = cleaned[:500].rstrip()
    poll, _ = await store.create_community_poll(
        {
            "poll_key": f"requested:{requester['id']}:{uuid4()}",
            "poll_kind": "requested",
            "requester_property_id": requester["id"],
            "question": cleaned,
            "opens_at": current,
            "closes_at": current + timedelta(hours=settings.community_poll_hours),
        }
    )
    added = await _add_current_homesteaders(store, poll)
    return {"poll": poll, "recipients_added": len(added)}


async def create_operator_poll(
    store,
    question: str,
    settings: Settings | None = None,
    *,
    now: datetime | None = None,
) -> dict:
    settings = settings or get_settings()
    current = _now(now)
    cleaned = " ".join(str(question or "").split()).strip()
    if not cleaned:
        raise ValueError("poll question cannot be empty")
    poll, _ = await store.create_community_poll(
        {
            "poll_key": f"operator:{uuid4()}",
            "poll_kind": "operator",
            "question": cleaned[:500].rstrip(),
            "opens_at": current,
            "closes_at": current + timedelta(hours=settings.community_poll_hours),
        }
    )
    added = await _add_current_homesteaders(store, poll)
    return {"poll": poll, "recipients_added": len(added)}


def _analysis(poll: dict, recipients: list[dict], answers: list[dict]) -> dict:
    counts: Counter[str] = Counter()
    for row in answers:
        counts.update(
            word.casefold()
            for word in _WORDS.findall(row.get("answer") or "")
            if word.casefold() not in _STOP_WORDS
        )
    themes = [{"theme": word, "mentions": count} for word, count in counts.most_common(8)]
    raw_answers = [
        {
            "property_id": row["property_id"],
            "username": row.get("username"),
            "display_name": row.get("display_name"),
            "answer": row["answer"],
            "answered_at": (
                row["created_at"].isoformat()
                if isinstance(row.get("created_at"), datetime)
                else row.get("created_at")
            ),
        }
        for row in answers
    ]
    recipient_count = len(recipients)
    response_count = len(answers)
    return {
        "poll_id": poll["id"],
        "question": poll["question"],
        "recipient_count": recipient_count,
        "response_count": response_count,
        "response_rate_pct": round(response_count * 100 / recipient_count, 1) if recipient_count else 0.0,
        "themes": themes,
        "action_candidates": raw_answers[:10],
        "answers": raw_answers,
    }


def _report(analysis: dict) -> str:
    themes = ", ".join(
        f"{row['theme']} ({row['mentions']})" for row in analysis["themes"]
    ) or "none yet"
    lines = [
        f"Question: {analysis['question']}",
        (
            f"Responses: {analysis['response_count']}/{analysis['recipient_count']} "
            f"({analysis['response_rate_pct']}%)"
        ),
        f"Recurring terms: {themes}",
        "Answers:",
    ]
    if not analysis["answers"]:
        lines.append("- No answers.")
    for row in analysis["answers"]:
        name = row.get("username") or row.get("display_name") or row["property_id"]
        lines.append(f"- {name}: {row['answer']}")
    return "\n".join(lines)


async def compile_community_poll(store, poll_or_id: dict | str) -> dict:
    poll = poll_or_id if isinstance(poll_or_id, dict) else await store.get_community_poll(poll_or_id)
    if poll is None:
        raise ValueError("poll not found")
    recipients = await store.community_poll_recipients_for(poll["id"])
    answers = await store.community_poll_answers_for(poll["id"])
    analysis = _analysis(poll, recipients, answers)
    return {"poll": poll, "report": _report(analysis), "analysis": analysis}


async def close_due_community_polls(store) -> list[dict]:
    closed = []
    for poll in await store.due_community_polls():
        compiled = await compile_community_poll(store, poll)
        row = await store.close_community_poll(poll["id"], compiled["report"], compiled["analysis"])
        if row is not None:
            closed.append(row)
    return closed


async def handle_private_poll_message(store, message: dict) -> str | None:
    """Handle poll commands/answers; return None when ordinary Jane should answer."""
    conversation_id = int(message["conversation_id"])
    prop = await store.get_property_by_conversation(conversation_id)
    if prop is None:
        return None
    content = str(message.get("content") or "").strip()
    command = _POLL_MODE.fullmatch(content)
    if command:
        await store.append_transcript(
            conversation_id=conversation_id,
            message_id=str(message.get("message_id") or "") or None,
            role="homesteader",
            speaker=message.get("speaker") or "Homesteader",
            content=content,
        )
        question = command.group(1) or DEFAULT_POLL_MODE_QUESTION
        result = await create_requested_poll(store, prop, question)
        if result["recipients_added"]:
            reply = _asked_confirmation(result["poll"]["question"])
        else:
            reply = "I could not find any private threads to ask."
        await deliver(store, conversation_id, reply)
        return reply

    # A community ask and a "any polls?" question are ordinary turns. The harness
    # writes the question and the reply. Do not treat either as a poll answer.
    if wants_community(content) or _POLL_STATUS.search(content):
        return None

    pending = await store.pending_community_polls(prop["id"])
    if not pending:
        return None
    explicit_answer = re.match(r"^poll(?:\s+answer)?\s*:\s*(.+)$", content, re.I | re.S)
    answer_content = explicit_answer.group(1).strip() if explicit_answer else content
    # Sponsor applications are multi-turn forms. Keep their unlabeled next
    # answer in that workflow; POLL: remains available to answer the poll.
    if prop.get("sponsor_draft") and explicit_answer is None:
        return None
    # A daily question should not swallow an explicit product workflow. Users
    # can also address Jane by name to leave the poll pending and ask anything.
    if re.match(r"^jane[\s,:-]", content, re.I) or re.search(
        r"\b(verify my identity|identity verification|start kyc|what are my scores|north star|"
        r"become a sponsor|register as a sponsor|cancel (the |my )?sponsor|"
        r"where can i (get|buy|find|source)|poll mode)\b",
        content,
        re.I,
    ) or re.match(r"^demand\s+[0-9a-f-]{36}\s*:", content, re.I):
        return None
    # The most recently delivered question is the one visible at the bottom of
    # the private thread, so the next reply belongs to that poll.
    poll = pending[-1]
    await store.append_transcript(
        conversation_id=conversation_id,
        message_id=str(message.get("message_id") or "") or None,
        role="homesteader",
        speaker=message.get("speaker") or "Homesteader",
        content=content,
    )
    answer = await store.answer_community_poll(poll["id"], prop["id"], answer_content)
    if answer is None:
        return None
    source = poll["poll_kind"] if poll["poll_kind"] in {"daily", "conversation"} else "community"
    await store.save_economy_note(
        {
            "property_id": prop["id"],
            "zip_code": prop.get("zip_code") or "",
            "poll_id": poll["id"],
            "source": source,
            "question": poll["question"],
            "answer": answer_content,
        }
    )
    from app.harness import speak

    remaining = await store.pending_community_polls(prop["id"])
    reply = await speak(
        store,
        message,
        prop=prop,
        note=(
            "You recorded this homesteader's answer to the community question. "
            "Acknowledge that in your own words. Do not invent anyone else's answer."
        ),
        allow_community=False,
    )
    if remaining:
        reply = f"{reply}\n\nThe next question is: {remaining[0]['question']}"
    await deliver(store, conversation_id, reply)
    return reply


async def offer_conversation_question(
    store,
    prop: dict | None,
    settings: Settings | None = None,
    *,
    now: datetime | None = None,
) -> str | None:
    """Ask one more profile question when Jane is already in the thread.

    The daily question stays one per ZIP per day. This is the extra question
    for a live conversation, chosen from what other homesteaders in the ZIP
    have already said, or from the topic list when they have not overlapped.
    """
    if not prop or not prop.get("zip_code") or prop.get("primary_conversation_id") is None:
        return None
    if prop.get("sponsor_draft"):
        return None
    if await store.pending_community_polls(prop["id"]):
        return None
    settings = settings or get_settings()
    current = _now(now)
    day = _local_day(current, settings)
    key = f"conversation:{prop['id']}:{day.isoformat()}"
    if await store.get_community_poll_by_key(key):
        return None
    zip_code = str(prop["zip_code"])
    group = [
        row
        for row in await store.list_properties()
        if str(row.get("zip_code") or "") == zip_code and row.get("primary_conversation_id") is not None
    ]
    lines = await store.homesteader_transcripts(
        [int(row["primary_conversation_id"]) for row in group]
    )
    notes = await store.economy_notes_for_property(prop["id"])
    asked = {row["question"] for row in notes}
    daily = await store.get_community_poll_by_key(f"daily:{zip_code}:{day.isoformat()}")
    if daily:
        asked.add(daily["question"])
    question = choose_conversation_question(prop, day, group, lines, asked)
    poll, _created = await store.create_community_poll(
        {
            "poll_key": key,
            "poll_kind": "conversation",
            "requester_property_id": prop["id"],
            "question": question,
            "opens_at": current,
            "closes_at": current + timedelta(hours=settings.community_poll_hours),
        }
    )
    await store.save_economy_note(
        {
            "property_id": prop["id"],
            "zip_code": zip_code,
            "poll_id": poll["id"],
            "source": "conversation",
            "question": question,
            "answer": None,
        }
    )
    return question


async def remember_conversation_answer(store, prop: dict | None, content: str) -> None:
    """Keep a profile answer without taking the thread away from Jane.

    A question mark, or a request she already knows how to route, stays a
    normal turn. A plain reply to the question she just asked is recorded.
    """
    if not prop:
        return
    text = " ".join(str(content or "").split())
    if not text or "?" in text or wants_community(text) or _POLL_STATUS.search(text):
        return
    if re.match(r"^jane[\s,:-]", text, re.I) or re.search(
        r"\b(verify my identity|identity verification|start kyc|what are my scores|north star|"
        r"become a sponsor|register as a sponsor|sponsorship|payment|"
        r"where can i (get|buy|find|source)|poll mode)\b",
        text,
        re.I,
    ):
        return
    notes = await store.economy_notes_for_property(prop["id"])
    waiting = [row for row in notes if row.get("source") == "conversation" and not row.get("answer")]
    if not waiting:
        return
    note = waiting[-1]
    await store.save_economy_note({**note, "answer": text})


async def run_poll_cycle(store, settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    daily = None
    if settings.daily_poll_enabled:
        daily = await ensure_daily_poll(store, settings)
    closed = await close_due_community_polls(store)
    return {"daily": daily, "closed": len(closed)}


async def poll_scheduler(store, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    while True:
        try:
            await run_poll_cycle(store, settings)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Jane poll cycle failed")
        await asyncio.sleep(settings.poll_scheduler_interval_seconds)
