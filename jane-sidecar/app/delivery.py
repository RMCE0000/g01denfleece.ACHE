"""Post Jane's reply through g01 and keep a copy in the outbox."""

import logging

from app.chatwoot_client import ChatwootClient
from app.config import get_settings

log = logging.getLogger(__name__)


async def deliver(store, conversation_id: int | None, content: str) -> None:
    if not content:
        return
    delivered = False
    client = ChatwootClient(get_settings())
    if conversation_id is not None and client.configured():
        try:
            await client.post_message(int(conversation_id), content)
            delivered = True
        except Exception:
            log.exception("g01 did not accept Jane's message on conversation %s", conversation_id)
    await store.add_outbox(int(conversation_id) if conversation_id is not None else None, content, delivered)
    if conversation_id is not None:
        await store.append_transcript(
            conversation_id=int(conversation_id),
            message_id=None,
            role="jane",
            speaker="Jane",
            content=content,
        )
