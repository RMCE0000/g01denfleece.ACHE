"""Private username dialing behind the authenticated g01 Rails bridge."""

import secrets
from urllib.parse import urlsplit

from fastapi import Request

from app.errors import G01Error
from app.homesteaders import conversation_url, open_peer_conversation


def _header_int(request: Request, name: str) -> int:
    raw = request.headers.get(name, "")
    if not raw.isdigit():
        raise G01Error("community identity is invalid", 401)
    return int(raw)


async def bridge_actor(store, request: Request, bridge_secret: str) -> dict:
    supplied = request.headers.get("x-g01-bridge-secret", "")
    if not bridge_secret or not secrets.compare_digest(supplied, bridge_secret):
        raise G01Error("community bridge authentication required", 401)
    account_id = _header_int(request, "x-g01-account-id")
    user_id = _header_int(request, "x-g01-user-id")
    actor = await store.get_property_by_user(user_id)
    if actor is None or int(actor.get("chatwoot_account_id") or 0) != account_id:
        raise G01Error("homesteader membership required", 403)
    return actor


async def community_state(store, actor: dict) -> dict:
    localities = {str(row["id"]): row for row in await store.list_localities()}
    properties = {str(row["id"]): row for row in await store.list_properties()}
    connections = []
    for peer in await store.list_peer_conversations():
        actor_id = str(actor["id"])
        pair = {str(peer.get("property_a_id")), str(peer.get("property_b_id"))}
        if actor_id not in pair:
            continue
        other_id = next((property_id for property_id in pair if property_id != actor_id), None)
        other = properties.get(other_id or "")
        if other is None:
            continue
        locality = localities.get(str(other.get("locality_id")), {})
        conversation_id = int(peer["chatwoot_conversation_id"])
        connections.append(
            {
                "username": other.get("username"),
                "name": other.get("display_name") or "Homesteader",
                "locality": locality.get("name") or "Locality not recorded",
                "conversation_id": conversation_id,
                "conversation_path": urlsplit(conversation_url(conversation_id)).path,
                "topic": peer.get("topic"),
            }
        )
    connections.sort(key=lambda row: ((row.get("name") or "").casefold(), row.get("username") or ""))
    actor_locality = localities.get(str(actor.get("locality_id")), {})
    return {
        "self": {
            "username": actor.get("username"),
            "name": actor.get("display_name") or "Homesteader",
            "locality": actor_locality.get("name") or "Locality not recorded",
        },
        "connections": connections,
    }


async def start_connection(store, actor: dict, username: str, topic: str | None) -> dict:
    target = await store.get_property_by_username(username)
    if target is None or not target.get("chatwoot_user_id") or str(target["id"]) == str(actor["id"]):
        # A generic answer prevents username probing from distinguishing missing,
        # inactive, and self records.
        raise G01Error("No available homesteader has that username.", 404)
    opened = await open_peer_conversation(store, str(actor["id"]), str(target["id"]), topic)
    return {
        "conversation_id": opened["conversation_id"],
        "conversation_path": urlsplit(opened["conversation_url"]).path,
        "existing": opened["existing"],
        "topic": opened.get("topic"),
    }
