"""Audio attachment intake for Chatwoot messages."""

from __future__ import annotations

import logging
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.config import Settings, get_settings
from app.gemini_flow import transcribe_audio

log = logging.getLogger(__name__)

_ACTIVE_STORAGE_PREFIX = "/rails/active_storage/"
_MAX_AUDIO_ATTACHMENTS = 3
_MAX_TRANSCRIPT_CHARS = 20_000


def is_audio_attachment(attachment: dict) -> bool:
    file_type = str(attachment.get("file_type") or "").lower()
    content_type = str(attachment.get("content_type") or "").lower()
    return file_type == "audio" or content_type.startswith("audio/")


def audio_attachments(message: dict) -> list[dict]:
    attachments = message.get("attachments") or []
    if not isinstance(attachments, list):
        return []
    return [item for item in attachments if isinstance(item, dict) and is_audio_attachment(item)]


def has_audio_attachment(message: dict) -> bool:
    return bool(audio_attachments(message))


def _existing_transcript(attachment: dict) -> str:
    text = attachment.get("transcribed_text")
    if not text and isinstance(attachment.get("meta"), dict):
        text = attachment["meta"].get("transcribed_text")
    return str(text or "").strip()


def _attachment_url(attachment: dict, settings: Settings) -> str:
    raw = str(attachment.get("data_url") or attachment.get("download_url") or "").strip()
    if not raw:
        raise ValueError("audio attachment URL is missing")
    parsed = urlsplit(raw)
    internal = urlsplit(settings.chatwoot_base_url)
    public = urlsplit(settings.chatwoot_public_url)
    if parsed.scheme or parsed.netloc:
        if parsed.scheme not in ("http", "https"):
            raise ValueError("audio attachment URL scheme is not allowed")
        allowed_hosts = {host for host in (internal.hostname, public.hostname) if host}
        if parsed.hostname not in allowed_hosts:
            raise ValueError("audio attachment URL host is not Chatwoot")
        path, query = parsed.path, parsed.query
    else:
        path, query = parsed.path, parsed.query
    if not path.startswith(_ACTIVE_STORAGE_PREFIX):
        raise ValueError("audio attachment URL is not Active Storage")
    path = path.replace("/blobs/redirect/", "/blobs/proxy/", 1)
    return urlunsplit((internal.scheme, internal.netloc, path, query, ""))


async def _download_audio(attachment: dict, settings: Settings) -> tuple[bytes, str]:
    url = _attachment_url(attachment, settings)
    limit = max(1, int(settings.audio_transcription_max_bytes))
    headers = {"Accept": "audio/*,application/octet-stream", "X-Forwarded-Proto": "https"}
    chunks: list[bytes] = []
    size = 0
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        async with client.stream("GET", url, headers=headers) as response:
            response.raise_for_status()
            length = response.headers.get("content-length")
            if length and int(length) > limit:
                raise ValueError("audio attachment exceeds the transcription limit")
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > limit:
                    raise ValueError("audio attachment exceeds the transcription limit")
                chunks.append(chunk)
            response_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    attachment_type = str(attachment.get("content_type") or "").split(";", 1)[0].strip().lower()
    mime_type = response_type if response_type.startswith("audio/") else attachment_type
    if not mime_type.startswith("audio/"):
        raise ValueError("attachment did not return audio content")
    return b"".join(chunks), mime_type


async def add_audio_transcript(message: dict) -> str:
    """Append transcripts to message content and return the combined text."""
    attachments = audio_attachments(message)[:_MAX_AUDIO_ATTACHMENTS]
    if not attachments:
        return str(message.get("content") or "").strip()
    settings = get_settings()
    transcripts: list[str] = []
    for attachment in attachments:
        transcript = _existing_transcript(attachment)
        if not transcript and settings.audio_transcription_enabled:
            try:
                data, mime_type = await _download_audio(attachment, settings)
                transcript = await transcribe_audio(data, mime_type)
            except (httpx.HTTPError, ValueError):
                log.exception("Jane could not read an audio attachment")
        if transcript:
            transcripts.append(transcript[:_MAX_TRANSCRIPT_CHARS])
    existing = str(message.get("content") or "").strip()
    if transcripts:
        audio_text = "\n".join(transcripts)
        message["content"] = f"{existing}\n\n[Audio transcript] {audio_text}".strip() if existing else audio_text
        attributes = dict(message.get("content_attributes") or {})
        attributes["g01_audio_transcript"] = True
        attributes["g01_audio_attachment_count"] = len(transcripts)
        message["content_attributes"] = attributes
    return str(message.get("content") or "").strip()
