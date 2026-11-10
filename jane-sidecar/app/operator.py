"""Terminal command center for the g01 operator.

Run inside the Jane container so the console shares the sidecar's database and
configuration:

    docker compose exec jane python -m app.operator
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shlex
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from app.errors import G01Error
from app.homesteaders import open_peer_conversation, resolve_homesteader
from app.jobs import mature_demand_polls, open_ready_collaborations, recount_referral_windows, scan_neighbor_synergies
from app.matchmaking import approve_match, reject_match
from app.northstar import view_from_property
from app.polling import close_due_community_polls, compile_community_poll, create_operator_poll
from app.runtime import open_store
from app.showcase import list_conversations
from app.sourcing import SPONSOR_TIERS, normalize_service_tag


HELP = """Commands
  dashboard                         Counts and integration readiness
  users                             All homesteaders
  user <username|email|user-id|property-id>
                                    Complete profile, ledger, scores, polls, and matches
  chats                             Every Jane and homesteader connection thread
  chat <conversation-id>            Full transcript and participants
  polls [limit]                     Daily, requested, and operator polls
  poll <poll-id>                    Question, response metrics, themes, and answers
  poll-create "<question>"          Ask every homesteader in their private Jane thread
  matches [pending|approved|rejected|all]
                                    Automatically discovered match proposals
  match <match-id>                  Full proposal and both homesteaders
  match-approve <match-id> [note]   Approve and privately pitch the match
  match-reject <match-id> [note]    Reject without contacting either user
  analyze [all|engagement|northstar|network|polls|economy]
                                    Deterministic analyses over all users and chats
  set <user> <field> <value>        Update a whitelisted North Star/profile field
  connect <left> <right> [topic]    Open a private homesteader conversation
  sponsors [active|inactive|all]    Sponsor profiles, including standalone companies
  sponsor <sponsor-id>              Complete sponsor profile
  sponsor-add <locality> <name> <tier> <tags> <summary> <lat> <lng> <active|inactive> [homesteader|-]
                                    Add a company profile; homestead link is optional
  sponsor-edit <id> <field> <value> Edit name, tier, tags, summary, location, or link
  sponsor-activate <id>             Include a sponsor in Jane's recommendations
  sponsor-disable <id>              Remove a sponsor from recommendations
  rank <user> <service-tag>         Preview local sponsor ranking
  jobs <polls|matches|referrals|connections|all>
                                    Run one disabled background workflow now
  localities                        Signup regions and ZIP allowlists
  capabilities                      What g01 features actually do
  help                              Show this list
  quit                              Exit

Quote names or topics containing spaces. Mutating commands ask for confirmation.
Set fields: aesthetic, labor-hours, material, material-surplus, energetic,
energetic-profitable, contained, street-address, latitude, longitude.
Sponsor tiers: local_manufacturer, local_service_or_stock, local_logistics_proxy.
Sponsor edit fields: name, tier, tags, summary, latitude, longitude,
founding-city, founding-state, franchise, homesteader.
"""


class WriteConfirmationRequired(Exception):
    """Raised when a command with side effects was not explicitly approved."""


def load_bootstrap_environment(path: str = "/bootstrap/chatwoot.env") -> None:
    """Load bootstrap outputs for `docker compose exec`, which skips ENTRYPOINT."""
    allowed = {
        "G01_CHATWOOT_API_TOKEN",
        "G01_CHATWOOT_PLATFORM_TOKEN",
        "G01_CHATWOOT_ACCOUNT_ID",
        "G01_CHATWOOT_INBOX_ID",
        "G01_JANE_USER_ID",
    }
    env_path = Path(path)
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        key, separator, raw_value = raw_line.partition("=")
        key = key.strip()
        if separator != "=" or key not in allowed or os.environ.get(key):
            continue
        try:
            parsed = shlex.split(raw_value, comments=True, posix=True)
        except ValueError:
            continue
        if len(parsed) == 1:
            os.environ[key] = parsed[0]


@dataclass
class CommandOutput:
    title: str
    value: Any


def _name(prop: dict) -> str:
    return str(prop.get("display_name") or prop.get("email") or prop.get("id") or "Unknown")


def _jsonable(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


class OperatorBackend:
    """Read and operate on the same store used by Jane."""

    def __init__(self, store, settings: Settings | None = None):
        self.store = store
        self.settings = settings or get_settings()

    async def dashboard(self) -> dict:
        users = await self.store.list_properties()
        chats = (await list_conversations(self.store))["conversations"]
        localities = await self.store.list_localities()
        community_polls = await self.store.list_community_polls()
        pending_matches = await self.store.list_matches("pending", 1000)
        sponsors = await self.store.list_sponsors(None, 1000)
        return {
            "mode": "minimum showcase",
            "store": type(self.store).__name__,
            "homesteaders": len(users),
            "conversation_threads": len(chats),
            "peer_connections": sum(row["kind"] == "connection" for row in chats),
            "messages_visible": sum(len(row["messages"]) for row in chats),
            "localities": len(localities),
            "community_polls": len(community_polls),
            "open_community_polls": sum(row["status"] == "open" for row in community_polls),
            "matches_waiting_for_operator": len(pending_matches),
            "sponsor_profiles": len(sponsors),
            "active_sponsors": sum(bool(row.get("is_active_sponsor")) for row in sponsors),
            "integrations": {
                "chatwoot_account_api": bool(self.settings.chatwoot_api_token),
                "chatwoot_platform_api": bool(self.settings.chatwoot_platform_token),
                "chatwoot_webhook_auth": bool(self.settings.chatwoot_webhook_secret),
                "gemini_api": bool(self.settings.gemini_api_key),
                "gemini_standard_model": self.settings.gemini_chat_model,
                "gemini_complex_model": self.settings.gemini_deliberation_model,
                "audio_transcription": self.settings.audio_transcription_enabled
                and bool(self.settings.gemini_api_key),
                "stripe": bool(self.settings.stripe_secret_key),
                "daily_poll_scheduler": self.settings.daily_poll_enabled,
                "automatic_matchmaking": self.settings.automatic_matchmaking_enabled,
                "legacy_celery_scheduler": self.settings.background_jobs,
            },
        }

    async def users(self) -> list[dict]:
        localities = {str(row["id"]): row for row in await self.store.list_localities()}
        rows = []
        for prop in await self.store.list_properties():
            locality = localities.get(str(prop.get("locality_id")), {})
            rows.append(
                {
                    "name": _name(prop),
                    "username": prop.get("username"),
                    "email": prop.get("email"),
                    "property_id": prop["id"],
                    "chatwoot_user_id": prop.get("chatwoot_user_id"),
                    "zip": prop.get("zip_code"),
                    "locality": locality.get("name"),
                    "kyc": bool(prop.get("kyc_verified")),
                    "updated_at": prop.get("updated_at"),
                }
            )
        return rows

    async def user(self, token: str) -> dict:
        prop = await resolve_homesteader(self.store, token)
        locality = await self.store.get_locality(prop["locality_id"])
        polls = await self.store.open_polls_for_requester(prop["id"])
        community_polls = await self.store.pending_community_polls(prop["id"])
        matches = await self.store.matches_for_property(prop["id"])
        connections = [
            row
            for row in await self.store.list_peer_conversations()
            if str(prop["id"]) in {str(row.get("property_a_id")), str(row.get("property_b_id"))}
        ]
        return {
            "identity": {
                "name": prop.get("display_name"),
                "username": prop.get("username"),
                "email": prop.get("email"),
                "property_id": prop["id"],
                "chatwoot_user_id": prop.get("chatwoot_user_id"),
                "chatwoot_contact_id": prop.get("chatwoot_contact_id"),
                "primary_conversation_id": prop.get("primary_conversation_id"),
                "chatwoot_inbox_id": prop.get("chatwoot_inbox_id"),
            },
            "location": {
                "street_address": prop.get("street_address"),
                "zip_code": prop.get("zip_code"),
                "latitude": prop.get("lat"),
                "longitude": prop.get("lng"),
                "locality": locality,
            },
            "northstar": view_from_property(prop),
            "known_facts_ledger": prop.get("known_facts_ledger") or {},
            "sponsor_draft": prop.get("sponsor_draft"),
            "kyc": {
                "verified": bool(prop.get("kyc_verified")),
                "stripe_identity_session_id": prop.get("stripe_identity_session_id"),
            },
            "open_polls": polls,
            "pending_community_polls": community_polls,
            "open_matches": matches,
            "connections": connections,
            "updated_at": prop.get("updated_at"),
        }

    async def chats(self) -> list[dict]:
        rows = (await list_conversations(self.store))["conversations"]
        return [
            {
                "conversation_id": row["conversation_id"],
                "kind": row["kind"],
                "people": ", ".join(person.get("name") or person.get("email") or "Unknown" for person in row["people"]),
                "topic": row.get("topic"),
                "messages": len(row["messages"]),
                "url": row["url"],
            }
            for row in rows
        ]

    async def chat(self, conversation_id: int) -> dict:
        rows = (await list_conversations(self.store))["conversations"]
        for row in rows:
            if int(row["conversation_id"]) == int(conversation_id):
                return row
        raise G01Error("conversation not found", 404)

    async def analyze(self, kind: str = "all") -> dict:
        if kind not in {"all", "engagement", "northstar", "network", "polls", "economy"}:
            raise G01Error("analysis must be all, engagement, northstar, network, polls, or economy", 422)
        users = await self.store.list_properties()
        chats = (await list_conversations(self.store))["conversations"]
        analyses = {
            "engagement": self._engagement(users, chats),
            "northstar": self._northstar(users),
            "network": self._network(users, chats),
            "polls": await self.poll_analysis(),
            "economy": await self._economy(users),
        }
        return analyses if kind == "all" else analyses[kind]

    async def polls(self, limit: int = 50) -> list[dict]:
        rows = []
        for poll in await self.store.list_community_polls(limit):
            compiled = await compile_community_poll(self.store, poll)
            analysis = compiled["analysis"]
            rows.append(
                {
                    "id": poll["id"],
                    "kind": poll["poll_kind"],
                    "status": poll["status"],
                    "question": poll["question"],
                    "responses": f"{analysis['response_count']}/{analysis['recipient_count']}",
                    "response_rate_pct": analysis["response_rate_pct"],
                    "closes_at": poll["closes_at"],
                }
            )
        return rows

    async def poll(self, poll_id: str) -> dict:
        poll = await self.store.get_community_poll(poll_id)
        if poll is None:
            raise G01Error("poll not found", 404)
        return await compile_community_poll(self.store, poll)

    async def create_poll(self, question: str, *, allow_write: bool) -> dict:
        if not allow_write:
            raise WriteConfirmationRequired
        return await create_operator_poll(self.store, question, self.settings)

    async def poll_analysis(self) -> dict:
        polls = await self.store.list_community_polls(1000)
        compiled = [await compile_community_poll(self.store, poll) for poll in polls]
        themes: Counter[str] = Counter()
        for row in compiled:
            themes.update(
                {theme["theme"]: theme["mentions"] for theme in row["analysis"]["themes"]}
            )
        return {
            "summary": {
                "polls": len(polls),
                "open": sum(row["status"] == "open" for row in polls),
                "recipients": sum(row["analysis"]["recipient_count"] for row in compiled),
                "responses": sum(row["analysis"]["response_count"] for row in compiled),
            },
            "themes": [
                {"theme": theme, "mentions": mentions}
                for theme, mentions in themes.most_common(12)
            ],
            "polls": [
                {
                    "id": row["poll"]["id"],
                    "question": row["poll"]["question"],
                    "status": row["poll"]["status"],
                    **{
                        key: row["analysis"][key]
                        for key in ("recipient_count", "response_count", "response_rate_pct", "action_candidates")
                    },
                }
                for row in compiled
            ],
        }

    async def _match_view(self, match: dict) -> dict:
        left = await self.store.get_property(match["peer_a_property_id"])
        right = await self.store.get_property(match["peer_b_property_id"])
        locality = await self.store.get_locality(match["locality_id"])
        return {
            **match,
            "locality": (locality or {}).get("name"),
            "peer_a": {
                "property_id": match["peer_a_property_id"],
                "name": _name(left or {}),
                "username": (left or {}).get("username"),
            },
            "peer_b": {
                "property_id": match["peer_b_property_id"],
                "name": _name(right or {}),
                "username": (right or {}).get("username"),
            },
        }

    async def matches(self, status: str = "pending") -> list[dict]:
        if status not in {"pending", "approved", "rejected", "all"}:
            raise G01Error("match status must be pending, approved, rejected, or all", 422)
        rows = await self.store.list_matches(None if status == "all" else status)
        return [await self._match_view(row) for row in rows]

    async def match(self, match_id: str) -> dict:
        row = await self.store.get_match(match_id)
        if row is None:
            raise G01Error("match not found", 404)
        return await self._match_view(row)

    async def review_match(
        self,
        match_id: str,
        decision: str,
        note: str | None,
        *,
        allow_write: bool,
    ) -> dict:
        if not allow_write:
            raise WriteConfirmationRequired
        if decision == "approved":
            return await approve_match(self.store, match_id, note)
        return {"match": await reject_match(self.store, match_id, note), "pitched_property_ids": []}

    def _engagement(self, users: list[dict], chats: list[dict]) -> dict:
        private = {int(row["conversation_id"]): row for row in chats if row["kind"] == "jane"}
        rows = []
        active = 0
        for prop in users:
            thread = private.get(int(prop["primary_conversation_id"])) if prop.get("primary_conversation_id") else None
            messages = (thread or {}).get("messages", [])
            homesteader_messages = sum(message.get("role") == "homesteader" for message in messages)
            if homesteader_messages:
                active += 1
            rows.append(
                {
                    "name": _name(prop),
                    "property_id": prop["id"],
                    "homesteader_messages": homesteader_messages,
                    "jane_messages": sum(message.get("role") == "jane" for message in messages),
                    "total_private_messages": len(messages),
                }
            )
        return {
            "summary": {
                "registered": len(users),
                "active_in_private_thread": active,
                "without_homesteader_message": len(users) - active,
                "all_visible_messages": sum(len(row["messages"]) for row in chats),
            },
            "users": rows,
        }

    def _northstar(self, users: list[dict]) -> dict:
        if not users:
            return {"summary": {"homesteaders": 0}, "users": []}
        rows = []
        for prop in users:
            star = view_from_property(prop)["northstar"]
            goals = (prop.get("known_facts_ledger") or {}).get("active_goals") or []
            rows.append({"name": _name(prop), "property_id": prop["id"], **star, "active_goals": goals})
        return {
            "summary": {
                "homesteaders": len(users),
                "average_automated": round(sum(row["automated"] for row in rows) / len(rows), 2),
                "average_aesthetic": round(sum(row["aesthetic"] for row in rows) / len(rows), 2),
                "average_energetic": round(sum(row["energetic"] for row in rows) / len(rows), 2),
                "material_independent": sum(row["material"] for row in rows),
                "energetic_profitable": sum(row["energetic_profitable"] for row in rows),
                "contained_zero_waste": sum(row["contained"] for row in rows),
                "with_active_goals": sum(bool(row["active_goals"]) for row in rows),
            },
            "users": rows,
        }

    async def _economy(self, users: list[dict]) -> dict:
        from app.economy import shared_terms_in_answers

        notes = await self.store.list_economy_notes()
        names = {prop["id"]: _name(prop) for prop in users}
        zips: dict[str, dict] = {}
        for note in notes:
            if not note.get("answer"):
                continue
            people = zips.setdefault(str(note.get("zip_code") or ""), {})
            profile = people.setdefault(
                note["property_id"],
                {"name": names.get(note["property_id"], note["property_id"]), "answers": []},
            )
            profile["answers"].append(
                {"source": note["source"], "question": note["question"], "answer": note["answer"]}
            )
        return {
            "summary": {
                "zips": len(zips),
                "profiles": sum(len(people) for people in zips.values()),
                "answered": sum(len(profile["answers"]) for people in zips.values() for profile in people.values()),
            },
            "zips": [
                {
                    "zip_code": zip_code,
                    "profiles": list(people.values()),
                    "shared_terms": shared_terms_in_answers(people),
                }
                for zip_code, people in sorted(zips.items())
            ],
        }

    def _network(self, users: list[dict], chats: list[dict]) -> dict:
        degrees: Counter[str] = Counter()
        pairs = []
        for chat in chats:
            if chat["kind"] != "connection":
                continue
            ids = [str(person["property_id"]) for person in chat["people"] if person.get("property_id")]
            for property_id in ids:
                degrees[property_id] += 1
            pairs.append(
                {
                    "conversation_id": chat["conversation_id"],
                    "people": [person.get("name") or person.get("email") for person in chat["people"]],
                    "topic": chat.get("topic"),
                    "messages": len(chat["messages"]),
                }
            )
        user_rows = [
            {"name": _name(prop), "property_id": prop["id"], "connections": degrees[str(prop["id"])]}
            for prop in users
        ]
        return {
            "summary": {
                "homesteaders": len(users),
                "connections": len(pairs),
                "isolated_homesteaders": sum(row["connections"] == 0 for row in user_rows),
            },
            "users": user_rows,
            "connections": pairs,
        }

    async def connect(self, left: str, right: str, topic: str | None, *, allow_write: bool) -> dict:
        if not allow_write:
            raise WriteConfirmationRequired
        return await open_peer_conversation(self.store, left, right, topic)

    async def set_user_field(self, token: str, field: str, raw_value: str, *, allow_write: bool) -> dict:
        if not allow_write:
            raise WriteConfirmationRequired
        prop = await resolve_homesteader(self.store, token)
        if field == "aesthetic":
            updated = await self.store.update_aesthetic(prop["id"], float(raw_value))
        elif field == "labor-hours":
            updated = await self.store.update_labor_hours(prop["id"], float(raw_value))
        else:
            profile_fields = {
                "material": ("northstar_material_independent", "bool"),
                "material-surplus": ("material_surplus_profitable", "bool"),
                "energetic": ("northstar_energetic_pct", "float"),
                "energetic-profitable": ("northstar_energetic_profitable", "bool"),
                "contained": ("northstar_contained_zero_waste", "bool"),
                "street-address": ("street_address", "text"),
                "latitude": ("lat", "float"),
                "longitude": ("lng", "float"),
            }
            spec = profile_fields.get(field)
            if spec is None:
                raise G01Error("field is not editable; enter `help` for the allowlist", 422)
            key, kind = spec
            if kind == "bool":
                lowered = raw_value.strip().casefold()
                if lowered not in {"true", "false", "yes", "no", "1", "0"}:
                    raise G01Error("boolean values are true/false, yes/no, or 1/0", 422)
                value: Any = lowered in {"true", "yes", "1"}
            elif kind == "float":
                value = float(raw_value)
            else:
                value = raw_value
            updated = await self.store.apply_profile_patch(prop["id"], {key: value})
        return {
            "homesteader": _name(updated),
            "property_id": updated["id"],
            "field": field,
            "value": raw_value,
            "northstar": view_from_property(updated),
        }

    async def _resolve_locality(self, token: str) -> dict:
        wanted = token.strip().casefold()
        matches = [
            row
            for row in await self.store.list_localities()
            if wanted
            in {
                str(row.get("id") or "").casefold(),
                str(row.get("name") or "").casefold(),
                str(row.get("primary_city") or "").casefold(),
            }
        ]
        if not matches:
            raise G01Error("locality not found; use `localities` for valid names and ids", 404)
        if len(matches) > 1:
            raise G01Error("locality is ambiguous; use its id", 422)
        return matches[0]

    async def _sponsor_view(self, sponsor: dict) -> dict:
        locality = await self.store.get_locality(sponsor["locality_id"])
        linked = None
        if sponsor.get("property_id"):
            prop = await self.store.get_property(sponsor["property_id"])
            if prop:
                linked = {
                    "property_id": prop["id"],
                    "name": _name(prop),
                    "username": prop.get("username"),
                }
        return {
            **sponsor,
            "locality": (locality or {}).get("name"),
            "linked_homestead": linked,
            "homestead_linked": bool(linked),
        }

    async def sponsors(self, status: str = "all") -> list[dict]:
        if status not in {"active", "inactive", "all"}:
            raise G01Error("sponsor status must be active, inactive, or all", 422)
        rows = await self.store.list_sponsors(None if status == "all" else status)
        return [await self._sponsor_view(row) for row in rows]

    async def sponsor(self, sponsor_id: str) -> dict:
        row = await self.store.get_sponsor(sponsor_id)
        if not row:
            raise G01Error("sponsor not found", 404)
        return await self._sponsor_view(row)

    async def add_sponsor(
        self,
        locality_token: str,
        company_name: str,
        tier: str,
        tags_csv: str,
        summary: str,
        latitude: str,
        longitude: str,
        status: str,
        homesteader: str | None,
        *,
        allow_write: bool,
    ) -> dict:
        if not allow_write:
            raise WriteConfirmationRequired
        if tier not in SPONSOR_TIERS:
            raise G01Error("invalid sponsor tier; enter `help` for valid tiers", 422)
        if status not in {"active", "inactive"}:
            raise G01Error("sponsor status must be active or inactive", 422)
        tags = [
            tag
            for raw in tags_csv.split(",")
            if (tag := normalize_service_tag(raw))
        ]
        if not tags:
            raise G01Error("provide at least one product or service tag", 422)
        locality = await self._resolve_locality(locality_token)
        prop = None
        if homesteader and homesteader not in {"-", "none"}:
            prop = await resolve_homesteader(self.store, homesteader)
        created = await self.store.create_sponsor(
            {
                "property_id": prop["id"] if prop else None,
                "locality_id": locality["id"],
                "company_name": company_name,
                "founding_city": locality["primary_city"],
                "founding_state": locality["state_code"],
                "is_franchise_or_chain": False,
                "sourcing_tier": tier,
                "service_tags": tags,
                "capabilities_summary": summary,
                "lat": float(latitude),
                "lng": float(longitude),
                "is_active_sponsor": status == "active",
            }
        )
        return await self._sponsor_view(created)

    async def edit_sponsor(
        self,
        sponsor_id: str,
        field: str,
        raw_value: str,
        *,
        allow_write: bool,
    ) -> dict:
        if not allow_write:
            raise WriteConfirmationRequired
        if field == "name":
            patch: dict[str, Any] = {"company_name": raw_value}
        elif field == "tier":
            if raw_value not in SPONSOR_TIERS:
                raise G01Error("invalid sponsor tier; enter `help` for valid tiers", 422)
            patch = {"sourcing_tier": raw_value}
        elif field == "tags":
            tags = [
                tag
                for raw in raw_value.split(",")
                if (tag := normalize_service_tag(raw))
            ]
            if not tags:
                raise G01Error("provide at least one product or service tag", 422)
            patch = {"service_tags": tags}
        elif field == "summary":
            patch = {"capabilities_summary": raw_value}
        elif field in {"latitude", "longitude"}:
            patch = {"lat" if field == "latitude" else "lng": float(raw_value)}
        elif field in {"founding-city", "founding-state"}:
            patch = {
                "founding_city" if field == "founding-city" else "founding_state":
                raw_value.upper() if field == "founding-state" else raw_value
            }
        elif field == "franchise":
            lowered = raw_value.casefold()
            if lowered not in {"true", "false", "yes", "no", "1", "0"}:
                raise G01Error("franchise must be true or false", 422)
            patch = {"is_franchise_or_chain": lowered in {"true", "yes", "1"}}
        elif field == "homesteader":
            if raw_value.casefold() in {"-", "none", "unlink"}:
                patch = {"property_id": None}
            else:
                prop = await resolve_homesteader(self.store, raw_value)
                patch = {"property_id": prop["id"]}
        else:
            raise G01Error("sponsor field is not editable; enter `help` for the allowlist", 422)
        return await self._sponsor_view(await self.store.update_sponsor(sponsor_id, patch))

    async def set_sponsor_status(
        self,
        sponsor_id: str,
        active: bool,
        *,
        allow_write: bool,
    ) -> dict:
        if not allow_write:
            raise WriteConfirmationRequired
        updated = await self.store.set_sponsor_active_flag(sponsor_id, active)
        if not updated:
            raise G01Error("sponsor not found", 404)
        return await self._sponsor_view(updated)

    async def rank(self, token: str, service_tag: str) -> dict:
        prop = await resolve_homesteader(self.store, token)
        return {
            "homesteader": _name(prop),
            "service_tag": service_tag,
            "results": await self.store.rank_sponsors(prop["id"], service_tag),
        }

    async def run_jobs(self, name: str, *, allow_write: bool) -> dict:
        valid = {"polls", "community-polls", "matches", "referrals", "connections", "all"}
        if name not in valid:
            raise G01Error("job must be polls, community-polls, matches, referrals, connections, or all", 422)
        if not allow_write:
            raise WriteConfirmationRequired
        result: dict[str, Any] = {}
        if name in {"polls", "all"}:
            result["poll_reports"] = await mature_demand_polls(self.store)
        if name in {"community-polls", "all"}:
            result["closed_community_poll_ids"] = [
                row["id"] for row in await close_due_community_polls(self.store)
            ]
        if name in {"matches", "all"}:
            result["new_match_ids"] = await scan_neighbor_synergies(self.store)
        if name in {"referrals", "all"}:
            await recount_referral_windows(self.store)
            result["referrals_recounted"] = True
        if name in {"connections", "all"}:
            result["opened_conversation_ids"] = await open_ready_collaborations(self.store)
        return result

    async def localities(self) -> list[dict]:
        return await self.store.list_localities()

    def capabilities(self) -> list[dict]:
        return [
            {"area": "Sign-in and password reset", "status": "active", "operator_action": "g01 owns auth; SMTP sends reset mail."},
            {"area": "Homesteader signup", "status": "active", "operator_action": "g01 creates an agent, property, and private Jane inbox."},
            {"area": "Private Jane chat", "status": "active with Gemini key", "operator_action": "LangChain routes ordinary turns to Gemini Flash and complex planning/analysis to Gemini Pro."},
            {"area": "Homesteader connections", "status": "active", "operator_action": "Users open Community in g01, or the operator uses `connect`."},
            {"area": "Messages, files, audio, and private notes", "status": "active", "operator_action": "g01 delivers and plays recordings between humans; Jane transcribes audio with Gemini before processing it."},
            {"area": "Contacts, labels, and custom fields", "status": "active", "operator_action": "g01 CRM works normally; homesteaders see contacts only in permitted inboxes."},
            {"area": "Assignment, status, snooze, priority", "status": "active", "operator_action": "Stock g01 controls remain available without changing g01 records."},
            {"area": "Reports", "status": "administrator", "operator_action": "Use g01 reports for messaging operations and this console for g01 analyses."},
            {"area": "Campaigns and help center", "status": "administrator", "operator_action": "Use their normal g01 workflows when content and audiences are configured."},
            {"area": "Email, WhatsApp, social channels", "status": "provider required", "operator_action": "Add and verify each external provider before using its inbox."},
            {"area": "North Star and ledger", "status": "active", "operator_action": "Jane applies grounded user statements in live private chat; use `user` or `analyze northstar` to inspect them."},
            {"area": "Jane daily and poll-mode questions", "status": "active", "operator_action": "Jane asks one question per ZIP each day. A small ZIP uses the 400-question list, which asks what the homesteader wants to do. A larger ZIP with shared recorded words is asked whether they are interested in that word too. A live conversation can add one more question. Use `polls`, `poll`, `poll-create`, or `analyze economy`."},
            {"area": "Automatic matchmaking", "status": "active with approval", "operator_action": "Discovery is automatic. Use `matches`, then `match-approve` or `match-reject`; pending matches never contact users."},
            {"area": "24-hour demand polling", "status": "active", "operator_action": "Jane schedules grounded demand synthesis in the sidecar; `jobs polls` remains available for operators."},
            {"area": "Sponsor profiles and ranking", "status": "active", "operator_action": "Use `sponsor-add`, `sponsors`, lifecycle commands, and `rank`; a homestead link is optional."},
            {"area": "Stripe and identity", "status": "configured only with keys", "operator_action": "Dashboard shows readiness; payment webhooks remain supported."},
        ]

    async def execute(self, words: list[str], *, allow_write: bool = False) -> CommandOutput:
        if not words:
            return CommandOutput("Dashboard", await self.dashboard())
        command, *args = words
        if command == "dashboard" and not args:
            return CommandOutput("Dashboard", await self.dashboard())
        if command == "users" and not args:
            return CommandOutput("Homesteaders", await self.users())
        if command == "user" and len(args) == 1:
            return CommandOutput(f"Homesteader: {args[0]}", await self.user(args[0]))
        if command in {"chats", "conversations"} and not args:
            return CommandOutput("Conversations", await self.chats())
        if command in {"chat", "conversation"} and len(args) == 1 and args[0].isdigit():
            return CommandOutput(f"Conversation {args[0]}", await self.chat(int(args[0])))
        if command == "polls" and len(args) <= 1 and (not args or args[0].isdigit()):
            limit = int(args[0]) if args else 50
            return CommandOutput("Jane polls", await self.polls(limit))
        if command == "poll" and len(args) == 1:
            return CommandOutput(f"Jane poll: {args[0]}", await self.poll(args[0]))
        if command == "poll-create" and args:
            question = " ".join(args)
            return CommandOutput("Jane poll created", await self.create_poll(question, allow_write=allow_write))
        if command == "matches" and len(args) <= 1:
            status = args[0] if args else "pending"
            return CommandOutput(f"Matches: {status}", await self.matches(status))
        if command == "match" and len(args) == 1:
            return CommandOutput(f"Match: {args[0]}", await self.match(args[0]))
        if command in {"match-approve", "match-reject"} and args:
            decision = "approved" if command == "match-approve" else "rejected"
            note = " ".join(args[1:]).strip() or None
            return CommandOutput(
                f"Match {decision}",
                await self.review_match(args[0], decision, note, allow_write=allow_write),
            )
        if command == "analyze" and len(args) <= 1:
            kind = args[0] if args else "all"
            return CommandOutput(f"Analysis: {kind}", await self.analyze(kind))
        if command == "set" and len(args) >= 3:
            value = " ".join(args[2:])
            return CommandOutput(
                "Profile updated",
                await self.set_user_field(args[0], args[1], value, allow_write=allow_write),
            )
        if command == "connect" and len(args) >= 2:
            topic = " ".join(args[2:]).strip() or None
            return CommandOutput("Connection", await self.connect(args[0], args[1], topic, allow_write=allow_write))
        if command == "sponsors" and len(args) <= 1:
            status = args[0] if args else "all"
            return CommandOutput(f"Sponsors: {status}", await self.sponsors(status))
        if command == "sponsor" and len(args) == 1:
            return CommandOutput(f"Sponsor: {args[0]}", await self.sponsor(args[0]))
        if command == "sponsor-add" and len(args) in {8, 9}:
            return CommandOutput(
                "Sponsor created",
                await self.add_sponsor(
                    *args[:8],
                    args[8] if len(args) == 9 else None,
                    allow_write=allow_write,
                ),
            )
        if command == "sponsor-edit" and len(args) >= 3:
            return CommandOutput(
                "Sponsor updated",
                await self.edit_sponsor(
                    args[0],
                    args[1],
                    " ".join(args[2:]),
                    allow_write=allow_write,
                ),
            )
        if command in {"sponsor-activate", "sponsor-disable"} and len(args) == 1:
            active = command == "sponsor-activate"
            return CommandOutput(
                "Sponsor activated" if active else "Sponsor disabled",
                await self.set_sponsor_status(args[0], active, allow_write=allow_write),
            )
        if command == "rank" and len(args) == 2:
            return CommandOutput("Sponsor ranking", await self.rank(args[0], args[1]))
        if command in {"job", "jobs"} and len(args) == 1:
            return CommandOutput(f"Jobs: {args[0]}", await self.run_jobs(args[0], allow_write=allow_write))
        if command == "localities" and not args:
            return CommandOutput("Localities", await self.localities())
        if command == "capabilities" and not args:
            return CommandOutput("g01 capabilities", self.capabilities())
        if command == "help" and not args:
            return CommandOutput("Help", HELP)
        raise G01Error("unknown command or wrong arguments; enter `help`", 422)


def _line(width: int = 78) -> str:
    return "─" * width


def _cell(value: Any, limit: int = 48) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (dict, list)):
        text = json.dumps(_jsonable(value), ensure_ascii=False)
    else:
        text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _render_rows(rows: list[dict]) -> str:
    if not rows:
        return "(none)"
    columns = list(rows[0])
    widths = {column: min(32, max(len(column), *[len(_cell(row.get(column), 32)) for row in rows])) for column in columns}
    header = "  ".join(column.ljust(widths[column]) for column in columns)
    rule = "  ".join("─" * widths[column] for column in columns)
    body = [
        "  ".join(_cell(row.get(column), widths[column]).ljust(widths[column]) for column in columns)
        for row in rows
    ]
    return "\n".join([header, rule, *body])


def _render_value(value: Any, indent: int = 0) -> str:
    prefix = " " * indent
    if isinstance(value, list) and all(isinstance(row, dict) for row in value):
        return "\n".join(prefix + line for line in _render_rows(value).splitlines())
    if isinstance(value, dict):
        lines = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}{key}:")
                lines.append(_render_value(item, indent + 2))
            else:
                lines.append(f"{prefix}{key}: {_cell(item, 120)}")
        return "\n".join(lines)
    if isinstance(value, list):
        return "\n".join(f"{prefix}- {_cell(item, 120)}" for item in value) or f"{prefix}(none)"
    return prefix + str(value)


def render(output: CommandOutput, *, as_json: bool = False) -> str:
    if as_json:
        return json.dumps({"title": output.title, "data": _jsonable(output.value)}, indent=2, ensure_ascii=False)
    return f"\n{output.title}\n{_line()}\n{_render_value(output.value)}"


async def _interactive(backend: OperatorBackend) -> int:
    print("g01 operator command center")
    print("All g01 user data and workflows. Enter `help` for commands.")
    print(render(await backend.execute(["dashboard"])))
    while True:
        try:
            raw = input("\ng01> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not raw:
            continue
        try:
            words = shlex.split(raw)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            continue
        if words[0] in {"quit", "exit"}:
            return 0
        try:
            output = await backend.execute(words)
        except WriteConfirmationRequired:
            approved = input("This changes data or can send g01 messages. Continue? [y/N] ").strip().casefold()
            if approved not in {"y", "yes"}:
                print("cancelled")
                continue
            output = await backend.execute(words, allow_write=True)
        except (G01Error, ValueError) as exc:
            print(f"error: {getattr(exc, 'message', str(exc))}", file=sys.stderr)
            continue
        print(render(output))


async def _main(args: argparse.Namespace) -> int:
    load_bootstrap_environment()
    get_settings.cache_clear()
    # Jane's service startup owns schema application. Operator commands may run
    # concurrently and must not contend on DDL locks merely to read the store.
    settings = get_settings().model_copy(update={"boot_on_startup": False})
    store = await open_store(settings)
    try:
        backend = OperatorBackend(store, settings)
        if not args.command:
            return await _interactive(backend)
        try:
            output = await backend.execute(args.command, allow_write=args.yes)
        except WriteConfirmationRequired:
            print("error: this command changes data; rerun with --yes", file=sys.stderr)
            return 2
        print(render(output, as_json=args.json))
        return 0
    finally:
        await store.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="g01 operator command center")
    parser.add_argument("--json", action="store_true", help="print one-shot results as JSON")
    parser.add_argument("--yes", action="store_true", help="approve a mutating one-shot command")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="optional one-shot command")
    args = parser.parse_args(argv)
    try:
        return asyncio.run(_main(args))
    except (G01Error, RuntimeError, ValueError) as exc:
        print(f"error: {getattr(exc, 'message', str(exc))}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
