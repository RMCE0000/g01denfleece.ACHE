"""Strip retailer links and banned-store recommendations from anything Jane posts."""

import re

from app.constitution import BANNED_URL_HOSTS

_URL = re.compile(r"https?://[^\s)>\]]+", re.I)
_REFUSAL = re.compile(
    r"\b(does not list|did not file|may only appear|are excluded|is excluded|will not (list|recommend|name|link))\b",
    re.I,
)


def _host_banned(url: str) -> bool:
    lowered = url.casefold()
    return any(host in lowered for host in BANNED_URL_HOSTS)


def _line_is_banned(line: str, allow_walmart_name: bool) -> bool:
    urls = list(_URL.finditer(line))
    if any(_host_banned(match.group(0)) for match in urls):
        return True
    names_retailer = bool(re.search(r"\b(amazon|home\s*depot|lowe'?s)\b", line, re.I))
    names_walmart = bool(re.search(r"\bwal-?mart\b", line, re.I)) and not allow_walmart_name
    if not names_retailer and not names_walmart:
        return False
    # A refusal may name the banned store so the homesteader hears why it was not filed.
    # A checkout link on that same line is still dropped above.
    if _REFUSAL.search(line):
        return False
    return True


def sanitize_reply(text: str, *, allow_walmart_name: bool = False) -> str:
    """Drop any line that recommends a banned retailer or links to one.

    A Rogers registry row may name Walmart. A Walmart URL is still removed.
    """
    if not text:
        return ""
    kept: list[str] = []
    for line in text.splitlines():
        if _line_is_banned(line, allow_walmart_name):
            continue
        kept.append(line.rstrip())
    collapsed = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()
    return collapsed[:4000]
