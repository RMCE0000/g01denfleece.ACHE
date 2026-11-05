import asyncio
from types import SimpleNamespace

import pytest

from app.chatwoot_client import ChatwootClient
from app.errors import G01Error


class _Response:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.content = b"{}"
        self.text = "{}"

    def json(self):
        return self._payload


class _HttpClient:
    def __init__(self, response, captured):
        self.response = response
        self.captured = captured

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def request(self, method, url, headers=None, json=None):
        self.captured.update(method=method, url=url, headers=headers, json=json)
        return self.response


def _settings():
    return SimpleNamespace(
        chatwoot_api_token="api-token",
        chatwoot_platform_token="platform-token",
        chatwoot_base_url="http://rails:3000",
        chatwoot_account_id=1,
        jane_user_id=1,
    )


def test_private_chatwoot_requests_identify_the_public_https_scheme(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "app.chatwoot_client.httpx.AsyncClient",
        lambda timeout: _HttpClient(_Response(payload={"ok": True}), captured),
    )

    result = asyncio.run(ChatwootClient(_settings())._request("GET", "/api/v1/accounts/1/webhooks"))

    assert result == {"ok": True}
    assert captured["url"] == "http://rails:3000/api/v1/accounts/1/webhooks"
    assert captured["headers"]["X-Forwarded-Proto"] == "https"


def test_chatwoot_redirect_is_an_error_instead_of_empty_success(monkeypatch):
    monkeypatch.setattr(
        "app.chatwoot_client.httpx.AsyncClient",
        lambda timeout: _HttpClient(_Response(status_code=308), {}),
    )

    with pytest.raises(G01Error, match="Chatwoot returned 308"):
        asyncio.run(ChatwootClient(_settings())._request("POST", "/platform/api/v1/users", {}))
