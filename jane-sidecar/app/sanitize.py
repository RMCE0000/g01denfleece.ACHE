"""Strip retailer links and banned-store recommendations from anything Jane posts."""

import re

from app.constitution import BANNED_URL_HOSTS

_URL = re.compile(r"https?://[^\s)>\]]+", re.I)


def _host_banned(url: str) -> bool:
    lowered = url.casefold()
    return any(host in lowered for host in BANNED_URL_HOSTS)


def _line_is_banned(line: str, allow_walmart_name: bool) -> bool:
    if any(_host_banned(match.group(0)) for match in _URL.finditer(line)):
        return True
    if re.search(r"\b(amazon|home\s*depot|lowe'?s)\b", line, re.I):
        return True
    if re.search(r"\bwal-?mart\b", line, re.I) and not allow_walmart_name:
        return True
    return False


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
