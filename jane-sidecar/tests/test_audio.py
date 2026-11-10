import asyncio

import pytest

from app.audio import _attachment_url, add_audio_transcript
from app.chatwoot_client import ChatwootClient
from app.config import Settings
from app.seed import DEMO_CONVERSATION_ID, DEMO_USER_ID


def _settings() -> Settings:
    return Settings(
        chatwoot_base_url="http://rails:3000",
        chatwoot_public_url="https://g01denfleece.com",
    )


def _attachment(transcribed_text: str = "") -> dict:
    return {
        "id": 71,
        "file_type": "audio",
        "content_type": "audio/wav",
        "data_url": "https://g01denfleece.com/rails/active_storage/blobs/redirect/signed/voice.wav",
        "transcribed_text": transcribed_text,
    }


def _message_payload(*, message_id: int, conversation_id: int = DEMO_CONVERSATION_ID) -> dict:
    return {
        "event": "message_created",
        "id": message_id,
        "content": None,
        "message_type": "outgoing",
        "private": False,
        "content_attributes": {},
        "attachments": [_attachment()],
        "sender": {"id": DEMO_USER_ID, "type": "user", "name": "Robert"},
        "conversation": {
            "id": conversation_id,
            "account_id": 1,
            "meta": {"sender": {"id": 101, "type": "contact"}},
        },
        "account": {"id": 1},
    }


def test_audio_url_is_confined_to_chatwoot_and_uses_the_proxy_route():
    assert _attachment_url(_attachment(), _settings()) == (
        "http://rails:3000/rails/active_storage/blobs/proxy/signed/voice.wav"
    )
    hostile = {**_attachment(), "data_url": "https://example.net/rails/active_storage/blobs/redirect/x"}
    with pytest.raises(ValueError, match="host is not g01"):
        _attachment_url(hostile, _settings())


@pytest.mark.asyncio
async def test_existing_chatwoot_transcript_is_used_without_downloading(monkeypatch):
    async def should_not_download(*_args):
        raise AssertionError("already-transcribed audio should not be downloaded")

    monkeypatch.setattr("app.audio._download_audio", should_not_download)
    message = {"content": "", "content_attributes": {}, "attachments": [_attachment("The well is low.")]}

    assert await add_audio_transcript(message) == "The well is low."
    assert message["content_attributes"]["g01_audio_transcript"] is True


def test_jane_transcribes_an_audio_webhook_before_answering(client, store, monkeypatch):
    async def fake_download(*_args):
        return b"wave-data", "audio/wav"

    async def fake_transcribe(data, mime_type):
        assert data == b"wave-data"
        assert mime_type == "audio/wav"
        return "The cistern needs a new valve."

    monkeypatch.setattr("app.audio._download_audio", fake_download)
    monkeypatch.setattr("app.audio.transcribe_audio", fake_transcribe)

    response = client.post("/webhooks/chatwoot", json=_message_payload(message_id=701))

    assert response.status_code == 200
    assert response.json()["ok"] is True
    remembered = [row for row in store.transcript if row.get("message_id") == "701"]
    assert remembered and remembered[0]["content"] == "The cistern needs a new valve."


def test_peer_audio_is_transcribed_but_does_not_summon_jane(client, store, monkeypatch):
    async def fake_download(*_args):
        return b"wave-data", "audio/wav"

    async def fake_transcribe(*_args):
        return "The tomatoes are ready for pickup."

    asyncio.run(
        store.remember_peer_conversation(
            900,
            store.properties[0]["id"],
            store.properties[1]["id"],
            91,
            "produce",
        )
    )
    monkeypatch.setattr("app.audio._download_audio", fake_download)
    monkeypatch.setattr("app.audio.transcribe_audio", fake_transcribe)

    response = client.post("/webhooks/chatwoot", json=_message_payload(message_id=702, conversation_id=900))

    assert response.json()["ignored"] == "peer"
    assert response.json()["audio"] == "transcribed"
    remembered = [row for row in store.transcript if row.get("message_id") == "702"]
    assert remembered and remembered[0]["content"] == "The tomatoes are ready for pickup."


@pytest.mark.asyncio
async def test_chatwoot_history_uses_its_audio_transcription(monkeypatch):
    async def fake_request(*_args, **_kwargs):
        return {
            "payload": [
                {
                    "id": 703,
                    "content": None,
                    "message_type": 1,
                    "private": False,
                    "sender": {"id": 8, "type": "user", "name": "Ada"},
                    "attachments": [_attachment("We need more seed trays.")],
                }
            ]
        }

    client = ChatwootClient(_settings())
    monkeypatch.setattr(client, "_request", fake_request)

    lines = await client.list_messages(900)

    assert lines[0]["content"] == "We need more seed trays."
