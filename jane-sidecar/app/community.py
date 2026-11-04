"""Authenticated homesteader directory behind the Chatwoot Rails bridge."""

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


async def list_members(store, actor: dict) -> dict:
    localities = {str(row["id"]): row for row in await store.list_localities()}
    members = []
    for prop in await store.list_properties():
        if str(prop["id"]) == str(actor["id"]) or not prop.get("chatwoot_user_id"):
            continue
        peer = await store.find_peer_between(actor["id"], prop["id"])
        locality = localities.get(str(prop.get("locality_id")), {})
        row = {
            "id": str(prop["id"]),
            "name": prop.get("display_name") or "Homesteader",
            "locality": locality.get("name") or "Locality not recorded",
            "connected": peer is not None,
        }
        if peer:
            conversation_id = int(peer["chatwoot_conversation_id"])
            row["conversation_id"] = conversation_id
            row["conversation_path"] = urlsplit(conversation_url(conversation_id)).path
            row["topic"] = peer.get("topic")
        members.append(row)
    members.sort(key=lambda row: (row["name"].casefold(), row["id"]))
    actor_locality = localities.get(str(actor.get("locality_id")), {})
    return {
        "self": {
            "name": actor.get("display_name") or "Homesteader",
            "locality": actor_locality.get("name") or "Locality not recorded",
        },
        "members": members,
    }


async def start_connection(store, actor: dict, member_id: str, topic: str | None) -> dict:
    target = await store.get_property(member_id)
    if target is None or not target.get("chatwoot_user_id") or str(target["id"]) == str(actor["id"]):
        # Do not let the directory endpoint enumerate private property identifiers.
        raise G01Error("community member not found", 404)
    opened = await open_peer_conversation(store, str(actor["id"]), str(target["id"]), topic)
    return {
        "conversation_id": opened["conversation_id"],
        "conversation_path": urlsplit(opened["conversation_url"]).path,
        "existing": opened["existing"],
        "topic": opened.get("topic"),
    }
