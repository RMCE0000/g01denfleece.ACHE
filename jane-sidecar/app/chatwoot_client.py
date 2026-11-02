"""Chatwoot REST wrapper. Messaging and auth stay in Chatwoot; this only calls them."""

import logging

import httpx

from app.config import get_settings
from app.errors import G01Error

log = logging.getLogger(__name__)


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
            raise G01Error(f"Chatwoot returned {response.status_code}", 502)
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
        return await self._request(
            "POST",
            "/platform/api/v1/users",
            {"name": name, "display_name": name, "email": email, "password": password, "custom_attributes": {"g01": True}},
            platform=True,
        )

    async def add_account_user(self, user_id: int) -> dict:
        return await self._request(
            "POST",
            f"/platform/api/v1/accounts/{self._account()}/account_users",
            {"user_id": int(user_id), "role": "agent"},
            platform=True,
        )

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

    async def create_conversation(self, contact_id: int, content: str | None = None) -> dict:
        body = {
            "inbox_id": int(self.settings.chatwoot_inbox_id),
            "contact_id": int(contact_id),
            "status": "open",
        }
        if content:
            body["message"] = {"content": content}
        return await self._request("POST", f"/api/v1/accounts/{self._account()}/conversations", body)

    async def add_participant(self, conversation_id: int, user_id: int) -> dict:
        return await self._request(
            "POST",
            f"/api/v1/accounts/{self._account()}/conversations/{int(conversation_id)}/participants",
            {"user_id": int(user_id)},
        )

    async def create_shared_conversation(self, peer_a: dict, peer_b: dict) -> int | None:
        """Open one Chatwoot thread and seat both homesteaders plus Jane as participants."""
        if not self.configured():
            return None
        created = await self.create_conversation(
            int(peer_a["chatwoot_contact_id"]),
            "Shared homestead thread. Jane is a peer here. This conversation stays open.",
        )
        conversation_id = int(created["id"])
        for user_id in (peer_a.get("chatwoot_user_id"), peer_b.get("chatwoot_user_id"), self.settings.jane_user_id):
            if user_id:
                await self.add_participant(conversation_id, int(user_id))
        return conversation_id

    async def ensure_webhook(self) -> None:
        if not self.configured():
            return
        target = self.settings.public_base_url.rstrip("/") + "/webhooks/chatwoot"
        if self.settings.chatwoot_webhook_secret:
            target += "?token=" + self.settings.chatwoot_webhook_secret
        existing = await self._request("GET", f"/api/v1/accounts/{self._account()}/webhooks")
        rows = existing.get("payload", existing) if isinstance(existing, dict) else existing
        if isinstance(rows, list) and any(target in str(row.get("url", "")) for row in rows if isinstance(row, dict)):
            return
        await self._request(
            "POST",
            f"/api/v1/accounts/{self._account()}/webhooks",
            {"url": target, "subscriptions": ["message_created"]},
        )
