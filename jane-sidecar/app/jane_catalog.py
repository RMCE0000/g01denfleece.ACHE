"""What Jane may offer, and the knowledge she may treat as her own.

The operator files both, the way a sponsor is filed. A draft product is not
an offer. A knowledge entry reaches a turn only when the message is about
that entry's topic. Jane does not invent a product, a premium, or a term.
"""

from __future__ import annotations

import re

from app.errors import G01Error

_WORD = re.compile(r"[a-z0-9]+")
_SKIP = {
    "about",
    "from",
    "have",
    "home",
    "homestead",
    "insurance",
    "jane",
    "need",
    "that",
    "their",
    "them",
    "this",
    "what",
    "with",
    "would",
    "your",
}
_BODY_LIMIT = 700
_KNOWLEDGE_LIMIT = 3
_SUMMARY_LIMIT = 4


def _words(text: str) -> set[str]:
    return {word for word in _WORD.findall((text or "").casefold()) if len(word) >= 4 and word not in _SKIP}


def _topic_hit(topics: list, text: str) -> bool:
    lowered = (text or "").casefold()
    wanted = _words(text)
    for topic in topics or []:
        phrase = str(topic).strip().casefold().replace("_", " ")
        if not phrase:
            continue
        if re.search(rf"\b{re.escape(phrase)}\b", lowered):
            return True
        topic_words = _words(phrase)
        if topic_words and topic_words <= wanted:
            return True
    return False


def select_knowledge(entries: list[dict], text: str, *, limit: int = _KNOWLEDGE_LIMIT) -> list[dict]:
    """The few filed entries whose topics the message actually touches."""
    chosen = [entry for entry in entries if _topic_hit(entry.get("topics") or [], text)]
    return chosen[:limit]


def _clip(text: str, limit: int) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def render_catalog(products: list[dict], knowledge: list[dict], text: str) -> str:
    """The turn note. Drafts never appear. Unmatched knowledge never appears."""
    offered = [row for row in products if str(row.get("status") or "") == "offered"]
    lines = [
        "JANE'S INSURANCE",
        "Insurance is the guiding principle above the seven aims. Those aims stay private; do not recite them.",
        "You may speak briefly, in a poetic register, when they are talking about insurance, risk, or why a homestead is a guarantee that their domain is not at the whim of quarrels beyond the home. Then return to the next useful step. Do not open an ordinary repair with that speech.",
        "Offer only a product listed below. Do not invent a product, a premium, a limit, a deductible, a carrier, or a binding. Filing is not a sale and not a bound policy.",
        "A local insurance producer may still be an active g01 sponsor. Name that sponsor only when this turn names them. Your product is not their company, and their company is not your product.",
    ]
    if not offered:
        lines.append("Products Jane may offer: none. Say so if they ask what you can insure. Do not name a product.")
    else:
        lines.append("Products Jane may offer:")
        message_words = _words(text)
        summaries = 0
        for product in offered:
            name = str(product.get("name") or "").strip()
            covers = str(product.get("covers") or "").strip()
            lines.append(f"- {name}: covers {covers}.")
            haystack = _words(f"{name} {covers}")
            if summaries < _SUMMARY_LIMIT and haystack & message_words:
                summary = _clip(product.get("summary") or "", 400)
                if summary:
                    lines.append(f"  You may say: {summary}")
                    summaries += 1
    filed = select_knowledge(knowledge, text)
    if not filed:
        lines.append(
            "Filed knowledge for this message: none. You may speak about the principle. "
            "You may not state a coverage term, a price, or a condition as fact."
        )
    else:
        lines.append("Filed knowledge for this message, and no other expertise:")
        for entry in filed:
            title = str(entry.get("title") or "").strip()
            lines.append(f"- {title}: {_clip(entry.get('body') or '', _BODY_LIMIT)}")
    return "\n".join(lines)


def require_text(value: str, label: str, limit: int) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        raise G01Error(f"{label} is required", 422)
    if len(text) > limit:
        raise G01Error(f"{label} must be {limit} characters or fewer", 422)
    return text


def clean_topics(topics) -> list[str]:
    if isinstance(topics, str):
        topics = topics.split(",")
    cleaned = []
    for topic in topics or []:
        text = " ".join(str(topic).replace("_", " ").split()).strip()
        if text and text.casefold() not in {row.casefold() for row in cleaned}:
            cleaned.append(text)
    return cleaned


async def catalog_note(store, text: str) -> str:
    products = await store.list_jane_products("offered")
    knowledge = await store.list_jane_knowledge()
    return render_catalog(products, knowledge, text)
