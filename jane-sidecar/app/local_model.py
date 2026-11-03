"""Small local model for the minimum showcase. Ollama, no cloud key."""

import logging
from contextvars import ContextVar

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)

model_override: ContextVar = ContextVar("g01_model_override", default=None)

UNREACHABLE = "I could not reach the local model."


async def complete_text(system: str, user: str) -> str:
    """Send the constitution as the system text and the history as the user text."""
    override = model_override.get()
    if override is not None:
        result = override(system, user)
        if hasattr(result, "__await__"):
            result = await result
        text = str(result or "").strip()
        return text or UNREACHABLE
    settings = get_settings()
    url = settings.ollama_base_url.rstrip("/") + "/api/chat"
    body = {
        "model": settings.ollama_model,
        "stream": False,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "options": {"temperature": 0.2, "num_predict": 180},
    }
    try:
        timeout = httpx.Timeout(120.0, connect=3.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=body)
        response.raise_for_status()
        payload = response.json()
    except Exception:
        log.exception("local model did not answer")
        return UNREACHABLE
    message = payload.get("message") if isinstance(payload, dict) else None
    text = str(message.get("content") or "").strip() if isinstance(message, dict) else ""
    return text or UNREACHABLE
