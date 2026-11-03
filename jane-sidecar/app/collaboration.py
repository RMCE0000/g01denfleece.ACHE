"""Double opt-in plus Stripe Identity before any shared Chatwoot thread."""

import logging

from app.chatwoot_client import ChatwootClient
from app.config import get_settings
from app.delivery import deliver
from app.errors import G01Error
from app.stripe_service import create_identity_session

log = logging.getLogger(__name__)


async def _identity_sentence(store, prop: dict) -> str:
    try:
        session = await create_identity_session(prop["id"])
    except G01Error:
        return "Stripe Identity is not configured, so I cannot verify you and I will not open a shared thread."
    await store.set_identity_session(prop["id"], session["id"])
    return f"Verify with Stripe Identity: {session['url']}"


async def refresh_match_gate(store, match_id: str, speaker_property_id: str | None = None) -> str:
    match = await store.get_match(match_id)
    if not match:
        return "I don't have that collaboration on the record."
    if match.get("shared_chatwoot_conversation_id"):
        return f"The shared thread is already open as Chatwoot conversation {match['shared_chatwoot_conversation_id']}."
    if match["peer_a_status"] == "declined" or match["peer_b_status"] == "declined":
        return "That collaboration is declined. I will not open a shared thread."
    if match["peer_a_status"] != "accepted" or match["peer_b_status"] != "accepted":
        return "I have your answer. The other homestead still has to accept before identity verification can open a thread."

    peer_a = await store.get_property(match["peer_a_property_id"])
    peer_b = await store.get_property(match["peer_b_property_id"])
    unverified = [peer for peer in (peer_a, peer_b) if not peer["kyc_verified"]]
    if unverified:
        sentences = []
        for peer in unverified:
            sentence = "Both of you accepted. " + await _identity_sentence(store, peer)
            sentences.append(sentence)
            if peer["id"] != speaker_property_id and peer.get("primary_conversation_id"):
                await deliver(store, peer["primary_conversation_id"], sentence)
        return sentences[0]

    if not peer_a.get("chatwoot_user_id") or not peer_b.get("chatwoot_user_id"):
        return (
            "Both of you accepted and both are verified. "
            "Each of you needs a Chatwoot sign-in before I can open a thread you can both use."
        )

    client = ChatwootClient(get_settings())
    try:
        conversation_id = await client.create_shared_conversation(peer_a, peer_b)
    except G01Error:
        log.exception("shared conversation create failed")
        conversation_id = None
    if conversation_id is None:
        return (
            "Both of you accepted and both are verified. Chatwoot did not open a thread, "
            "so I did not invent a shared conversation."
        )
    await store.set_shared_conversation(match_id, conversation_id)
    await store.remember_peer_conversation(
        conversation_id,
        peer_a["id"],
        peer_b["id"],
        topic=match.get("proposed_project_title"),
    )
    notice = (
        f"You're both verified and you both accepted. I opened Chatwoot conversation {conversation_id}. "
        "Jane is a peer in it, and it stays open."
    )
    await deliver(store, conversation_id, notice)
    for peer in (peer_a, peer_b):
        if peer["id"] != speaker_property_id and peer.get("primary_conversation_id"):
            await deliver(store, peer["primary_conversation_id"], notice)
    return notice


async def refresh_matches_for_property(store, property_id: str) -> None:
    for match in await store.matches_for_property(property_id):
        await refresh_match_gate(store, match["id"], speaker_property_id=None)
