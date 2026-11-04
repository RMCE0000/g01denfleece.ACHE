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
  analyze [all|engagement|northstar|network|polls]
                                    Deterministic analyses over all users and chats
  set <user> <field> <value>        Update a whitelisted North Star/profile field
  connect <left> <right> [topic]    Open a private homesteader conversation
  rank <user> <service-tag>         Preview local sponsor ranking
  jobs <polls|matches|referrals|connections|all>
                                    Run one disabled background workflow now
  localities                        Signup regions and ZIP allowlists
  capabilities                      What Chatwoot/g01 features actually do
  help                              Show this list
  quit                              Exit

Quote names or topics containing spaces. Mutating commands ask for confirmation.
Set fields: aesthetic, labor-hours, material, material-surplus, energetic,
energetic-profitable, contained, street-address, latitude, longitude.
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
            "integrations": {
                "chatwoot_account_api": bool(self.settings.chatwoot_api_token),
                "chatwoot_platform_api": bool(self.settings.chatwoot_platform_token),
                "chatwoot_webhook_auth": bool(self.settings.chatwoot_webhook_secret),
                "ollama_model": self.settings.ollama_model,
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
        if kind not in {"all", "engagement", "northstar", "network", "polls"}:
            raise G01Error("analysis must be all, engagement, northstar, network, or polls", 422)
        users = await self.store.list_properties()
        chats = (await list_conversations(self.store))["conversations"]
        analyses = {
            "engagement": self._engagement(users, chats),
            "northstar": self._northstar(users),
            "network": self._network(users, chats),
            "polls": await self.poll_analysis(),
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
            {"area": "Sign-in and password reset", "status": "active", "operator_action": "Chatwoot owns auth; SMTP sends reset mail."},
            {"area": "Homesteader signup", "status": "active", "operator_action": "g01 creates an agent, property, and private Jane inbox."},
            {"area": "Private Jane chat", "status": "active", "operator_action": "Ollama receives Jane's constitution and visible history."},
            {"area": "Homesteader connections", "status": "active", "operator_action": "Users open Community in Chatwoot, or the operator uses `connect`."},
            {"area": "Messages, files, and private notes", "status": "active", "operator_action": "Stock Chatwoot behavior remains available in every permitted inbox."},
            {"area": "Contacts, labels, and custom fields", "status": "active", "operator_action": "Chatwoot CRM works normally; homesteaders see contacts only in permitted inboxes."},
            {"area": "Assignment, status, snooze, priority", "status": "active", "operator_action": "Stock Chatwoot controls remain available without changing g01 records."},
            {"area": "Reports", "status": "administrator", "operator_action": "Use Chatwoot reports for messaging operations and this console for g01 analyses."},
            {"area": "Campaigns and help center", "status": "administrator", "operator_action": "Use their normal Chatwoot workflows when content and audiences are configured."},
            {"area": "Email, WhatsApp, social channels", "status": "provider required", "operator_action": "Add and verify each external provider before using its inbox."},
            {"area": "North Star and ledger", "status": "inspectable", "operator_action": "Use `user` or `analyze northstar`; live MS chat does not update it."},
            {"area": "Jane daily and poll-mode questions", "status": "active", "operator_action": "Use `polls`, `poll`, `poll-create`, or `analyze polls`; Jane schedules and captures answers."},
            {"area": "Automatic matchmaking", "status": "active with approval", "operator_action": "Discovery is automatic. Use `matches`, then `match-approve` or `match-reject`; pending matches never contact users."},
            {"area": "Legacy demand polling", "status": "manual", "operator_action": "Use `jobs polls`; the Celery scheduler remains off in MS."},
            {"area": "Sponsor ranking", "status": "inspectable", "operator_action": "Use `rank <user> <service-tag>`."},
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
        if command == "rank" and len(args) == 2:
            return CommandOutput("Sponsor ranking", await self.rank(args[0], args[1]))
        if command in {"job", "jobs"} and len(args) == 1:
            return CommandOutput(f"Jobs: {args[0]}", await self.run_jobs(args[0], allow_write=allow_write))
        if command == "localities" and not args:
            return CommandOutput("Localities", await self.localities())
        if command == "capabilities" and not args:
            return CommandOutput("Chatwoot and g01 capabilities", self.capabilities())
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
            approved = input("This changes data or can send Chatwoot messages. Continue? [y/N] ").strip().casefold()
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
