"""Chatwoot REST wrapper. Messaging and auth stay in Chatwoot; this only calls them."""

import logging
from urllib.parse import quote

import httpx

from app.config import get_settings
from app.errors import G01Error

log = logging.getLogger(__name__)


def _webhook_urls(payload) -> set[str]:
    found: set[str] = set()
    if isinstance(payload, dict):
        url = payload.get("url")
        if isinstance(url, str):
            found.add(url)
        for value in payload.values():
            found.update(_webhook_urls(value))
    elif isinstance(payload, list):
        for item in payload:
            found.update(_webhook_urls(item))
    return found


class ChatwootClient:
    def __init__(self, settings=None):
        self.settings = settings or get_settings()

    def configured(self) -> bool:
        return bool(self.settings.chatwoot_api_token and self.settings.chatwoot_base_url)

    def platform_configured(self) -> bool:
        return self.configured() and bool(self.settings.chatwoot_platform_token)

    async def _request(self, method: str, path: str, body: dict | None = None, platform: bool = False):
        token = self.settings.chatwoot_platform_token if platform else self.settings.chatwoot_api_token
        url = self.settings.chatwoot_base_url.rstrip("/") + path
        headers = {"api_access_token": token, "Accept": "application/json"}
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.request(method, url, headers=headers, json=body)
        if response.status_code >= 400:
            detail = " ".join(response.text.split())[:180]
            raise G01Error(f"Chatwoot returned {response.status_code}: {detail}", 502)
        if not response.content:
            return {}
        return response.json()

    def _account(self) -> int:
        return int(self.settings.chatwoot_account_id)

    async def post_message(self, conversation_id: int, content: str) -> dict:
        return await self._request(
            "POST",
            f"/api/v1/accounts/{self._account()}/conversations/{int(conversation_id)}/messages",
            {
                "content": content,
                "message_type": "outgoing",
                "private": False,
                "content_attributes": {"g01_author": "jane"},
            },
        )

    async def create_platform_user(self, name: str, email: str, password: str) -> dict:
        payload = await self._request(
            "POST",
            "/platform/api/v1/users",
            {"name": name, "display_name": name, "email": email, "password": password, "custom_attributes": {"g01": True}},
            platform=True,
        )
        if isinstance(payload, dict) and "id" not in payload and isinstance(payload.get("user"), dict):
            return payload["user"]
        return payload

    async def add_account_user(self, user_id: int, role: str = "agent") -> dict:
        return await self._request(
            "POST",
            f"/platform/api/v1/accounts/{self._account()}/account_users",
            {"user_id": int(user_id), "role": role},
            platform=True,
        )

    async def sso_link(self, user_id: int) -> str | None:
        if not self.platform_configured():
            return None
        try:
            payload = await self._request("GET", f"/platform/api/v1/users/{int(user_id)}/login", platform=True)
        except G01Error:
            log.exception("Chatwoot did not issue a sign-in link for user %s", user_id)
            return None
        if isinstance(payload, dict):
            return payload.get("url")
        return None

    async def create_contact(self, name: str, email: str) -> dict:
        payload = await self._request(
            "POST",
            f"/api/v1/accounts/{self._account()}/contacts",
            {"name": name, "email": email, "identifier": email},
        )
        # Chatwoot wraps the contact under "payload" on some versions and returns it bare on others.
        if isinstance(payload, dict) and "payload" in payload and isinstance(payload["payload"], dict):
            return payload["payload"].get("contact") or payload["payload"]
        return payload

    async def search_contact(self, email: str) -> dict | None:
        payload = await self._request(
            "GET",
            f"/api/v1/accounts/{self._account()}/contacts/search?q={quote(email)}",
        )
        rows = payload.get("payload") if isinstance(payload, dict) else None
        if isinstance(rows, dict):
            rows = rows.get("contacts") or rows.get("payload")
        if not isinstance(rows, list):
            return None
        wanted = email.casefold()
        for row in rows:
            if isinstance(row, dict) and str(row.get("email") or "").casefold() == wanted:
                return row
        return None

    async def create_conversation(
        self,
        contact_id: int,
        content: str | None = None,
        inbox_id: int | None = None,
        assignee_id: int | None = None,
    ) -> dict:
        body = {
            "inbox_id": int(inbox_id or self.settings.chatwoot_inbox_id),
            "contact_id": int(contact_id),
            "status": "open",
        }
        if content:
            body["message"] = {"content": content}
        if assignee_id:
            body["assignee_id"] = int(assignee_id)
        return await self._request("POST", f"/api/v1/accounts/{self._account()}/conversations", body)

    async def create_api_inbox(self, name: str, greeting: str) -> dict:
        return await self._request(
            "POST",
            f"/api/v1/accounts/{self._account()}/inboxes",
            {
                "name": name[:80],
                "greeting_enabled": True,
                "greeting_message": greeting,
                "enable_auto_assignment": False,
                "lock_to_single_conversation": True,
                "channel": {"type": "api"},
            },
        )

    async def add_inbox_members(self, inbox_id: int, user_ids: list[int]) -> dict:
        return await self._request(
            "POST",
            f"/api/v1/accounts/{self._account()}/inbox_members",
            {"inbox_id": int(inbox_id), "user_ids": [int(user_id) for user_id in user_ids]},
        )

    async def add_participants(self, conversation_id: int, user_ids: list[int]) -> dict:
        return await self._request(
            "POST",
            f"/api/v1/accounts/{self._account()}/conversations/{int(conversation_id)}/participants",
            {"user_ids": [int(user_id) for user_id in user_ids]},
        )

    async def open_agent_conversation(
        self,
        *,
        inbox_name: str,
        greeting: str,
        contact_name: str,
        contact_email: str,
        user_ids: list[int],
    ) -> dict:
        """Private inbox whose only agents are the given users plus whoever was passed in."""
        if not self.configured():
            raise G01Error("Chatwoot API token is not configured", 503)
        members = _unique_ids(user_ids)
        if len(members) < 2:
            raise G01Error("a homestead conversation needs the homesteader and Jane", 422)
        inbox = await self.create_api_inbox(inbox_name, greeting)
        inbox_id = _record_id(inbox)
        await self.add_inbox_members(inbox_id, members)
        try:
            contact = await self.create_contact(contact_name, contact_email)
        except G01Error as exc:
            if "422" not in exc.message:
                raise
            contact = await self.search_contact(contact_email)
            if contact is None:
                raise
        jane_id = int(self.settings.jane_user_id)
        others = [user_id for user_id in members if user_id != jane_id]
        created = await self.create_conversation(
            _record_id(contact),
            inbox_id=inbox_id,
            assignee_id=others[0] if len(others) == 1 else None,
        )
        conversation_id = _record_id(created)
        await self.add_participants(conversation_id, members)
        return {"inbox_id": inbox_id, "contact_id": _record_id(contact), "conversation_id": conversation_id}

    async def create_shared_conversation(self, peer_a: dict, peer_b: dict) -> int | None:
        """Open one private thread and seat both homesteaders plus Jane."""
        if not self.configured():
            return None
        if not peer_a.get("chatwoot_user_id") or not peer_b.get("chatwoot_user_id"):
            return None
        name_a = peer_a.get("display_name") or "Homesteader"
        name_b = peer_b.get("display_name") or "Homesteader"
        inbox_name = f"{name_a} and {name_b}"[:80]
        opened = await self.open_agent_conversation(
            inbox_name=inbox_name,
            greeting="This homestead conversation stays open.",
            contact_name=inbox_name,
            contact_email=f"pair-{peer_a['chatwoot_user_id']}-{peer_b['chatwoot_user_id']}@example.com",
            user_ids=[peer_a["chatwoot_user_id"], peer_b["chatwoot_user_id"], self.settings.jane_user_id],
        )
        try:
            await self.post_message(
                opened["conversation_id"],
                f"This conversation is {name_a} and {name_b}. I stay quiet unless you say my name. The thread stays open.",
            )
        except G01Error:
            log.exception("opened conversation %s without the intro", opened["conversation_id"])
        return opened["conversation_id"]

    async def ensure_webhook(self) -> None:
        if not self.configured():
            return
        target = self.settings.public_base_url.rstrip("/") + "/webhooks/chatwoot"
        if self.settings.chatwoot_webhook_secret:
            target += "?token=" + self.settings.chatwoot_webhook_secret
        existing = await self._request("GET", f"/api/v1/accounts/{self._account()}/webhooks")
        if target in _webhook_urls(existing):
            return
        await self._request(
            "POST",
            f"/api/v1/accounts/{self._account()}/webhooks",
            {"webhook": {"url": target, "name": "g01 Jane", "subscriptions": ["message_created"]}},
        )


def _unique_ids(values) -> list[int]:
    seen: list[int] = []
    for value in values:
        if value is None or value == "":
            continue
        number = int(value)
        if number not in seen:
            seen.append(number)
    return seen


def _record_id(payload) -> int:
    if isinstance(payload, dict):
        if "id" in payload and not isinstance(payload["id"], dict):
            return int(payload["id"])
        for key in ("payload", "contact", "user", "inbox"):
            inner = payload.get(key)
            if isinstance(inner, dict) and "id" in inner and not isinstance(inner["id"], dict):
                return int(inner["id"])
    raise G01Error("Chatwoot response did not include an id", 502)
