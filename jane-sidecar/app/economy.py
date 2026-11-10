"""Profiles Jane builds so a ZIP can economize together.

A daily question and a question asked during a conversation are recorded with
the homesteader's own answer. Nothing here is inferred by a model. A shared
subject is a concrete word that at least two homesteaders in the same ZIP
actually used.
"""

from __future__ import annotations

import re
from datetime import date

from app.poll_topics import TOPIC_PHRASES, topic_for

FEW_ZIP_HOMESTEADS = 3

_WORD = re.compile(r"[a-z][a-z'-]{3,}")
_SKIP = {
    "afternoon",
    "between",
    "black",
    "bulk",
    "buying",
    "could",
    "days",
    "extra",
    "hand",
    "help",
    "library",
    "list",
    "more",
    "need",
    "neighbor",
    "neighbors",
    "order",
    "share",
    "shared",
    "live",
    "small",
    "some",
    "space",
    "spare",
    "that",
    "their",
    "them",
    "this",
    "time",
    "together",
    "used",
    "with",
    "work",
    "would",
    "your",
}


def economy_terms() -> set[str]:
    terms = set()
    for phrase in TOPIC_PHRASES:
        for word in _WORD.findall(phrase.casefold().replace("-", " ")):
            if word not in _SKIP:
                terms.add(word)
    return terms


def _tokens(text: str) -> set[str]:
    allowed = economy_terms()
    return {word for word in _WORD.findall((text or "").casefold().replace("-", " ")) if word in allowed}


def shared_terms(properties: list[dict], lines: list[dict]) -> list[str]:
    """Economy words used by at least two different homesteaders."""
    by_conversation = {
        int(prop["primary_conversation_id"]): prop["id"]
        for prop in properties
        if prop.get("primary_conversation_id") is not None
    }
    spoken: dict[str, set[str]] = {}
    for line in lines:
        if line.get("role") != "homesteader":
            continue
        property_id = by_conversation.get(int(line["conversation_id"]))
        if not property_id:
            continue
        spoken.setdefault(property_id, set()).update(_tokens(line.get("content") or ""))
    counts: dict[str, int] = {}
    for words in spoken.values():
        for word in words:
            counts[word] = counts.get(word, 0) + 1
    shared = [word for word, count in counts.items() if count >= 2]
    return sorted(shared, key=lambda word: (-counts[word], word))


def cooperation_question(zip_code: str, term: str) -> str:
    return (
        f"More than one homestead in {zip_code} has mentioned {term}. "
        f"Do you have {term} to share, or do you need some?"
    )


def choose_daily_question(zip_code: str, day: date, properties: list[dict], lines: list[dict]) -> str:
    """The one question for this ZIP today.

    A small ZIP, or a ZIP whose recorded talk does not yet overlap, gets a
    topic from the fixed list. A larger ZIP with a shared word is asked about
    that word, because that is the opening for cooperating.
    """
    shared = shared_terms(properties, lines)
    if len(properties) >= FEW_ZIP_HOMESTEADS and shared:
        return cooperation_question(zip_code, shared[0])
    return topic_for(zip_code, day)


def choose_conversation_question(
    prop: dict,
    day: date,
    properties: list[dict],
    lines: list[dict],
    already_asked: set[str],
) -> str:
    """One more question while Jane is already talking with this homesteader."""
    zip_code = str(prop.get("zip_code") or "")
    for term in shared_terms(properties, lines):
        question = cooperation_question(zip_code, term)
        if question not in already_asked:
            return question
    for offset in range(len(TOPIC_PHRASES)):
        question = topic_for(zip_code, day, salt=f"{prop.get('id')}:{offset}")
        if question not in already_asked:
            return question
    return topic_for(zip_code, day, salt=str(prop.get("id") or ""))


def shared_terms_in_answers(people: dict[str, dict]) -> list[str]:
    """Words that show up in recorded answers from two profiles in one ZIP."""
    spoken: dict[str, set[str]] = {}
    for property_id, profile in people.items():
        words: set[str] = set()
        for row in profile.get("answers") or []:
            words.update(_tokens(row.get("answer") or ""))
        if words:
            spoken[property_id] = words
    counts: dict[str, int] = {}
    for words in spoken.values():
        for word in words:
            counts[word] = counts.get(word, 0) + 1
    shared = [word for word, count in counts.items() if count >= 2]
    return sorted(shared, key=lambda word: (-counts[word], word))
