import asyncio
from types import SimpleNamespace

import httpx
import pytest

from app.chatwoot_client import ChatwootClient
from app.errors import G01Error


class _Response:
    def __init__(self, status_code=200, payload=None, text=None, bad_json=False):
        self.status_code = status_code
        self._payload = payload or {}
        self.bad_json = bad_json
        self.text = "{}" if text is None else text
        self.content = self.text.encode()

    def json(self):
        if self.bad_json:
            raise ValueError("not json")
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

    with pytest.raises(G01Error, match="g01 returned 308") as redirected:
        asyncio.run(ChatwootClient(_settings())._request("POST", "/platform/api/v1/users", {}))
    assert redirected.value.status_code == 502


def test_unreachable_g01_is_unavailable_instead_of_a_server_error(monkeypatch):
    class _Down:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def request(self, *_args, **_kwargs):
            raise httpx.ConnectError("refused")

    monkeypatch.setattr("app.chatwoot_client.httpx.AsyncClient", _Down)

    with pytest.raises(G01Error, match="could not be reached") as failure:
        asyncio.run(ChatwootClient(_settings())._request("POST", "/platform/api/v1/users", {}))
    assert failure.value.status_code == 503


def test_plain_upstream_failure_and_unreadable_success_stay_explained(monkeypatch):
    pages = iter(
        (
            _Response(status_code=500, text="Internal Server Error"),
            _Response(status_code=200, text="<html>", bad_json=True),
        )
    )
    monkeypatch.setattr(
        "app.chatwoot_client.httpx.AsyncClient",
        lambda timeout: _HttpClient(next(pages), {}),
    )
    client = ChatwootClient(_settings())

    with pytest.raises(G01Error, match="could not finish that request") as crashed:
        asyncio.run(client._request("POST", "/platform/api/v1/users", {}))
    assert crashed.value.status_code == 502

    with pytest.raises(G01Error, match="could not read") as unreadable:
        asyncio.run(client._request("GET", "/platform/api/v1/users/1"))
    assert unreadable.value.status_code == 502


def test_duplicate_sign_in_from_g01_is_a_conflict(monkeypatch):
    monkeypatch.setattr(
        "app.chatwoot_client.httpx.AsyncClient",
        lambda timeout: _HttpClient(
            _Response(status_code=422, text='{"message":"Email has already been taken"}'),
            {},
        ),
    )

    with pytest.raises(G01Error, match="already has a sign-in") as taken:
        asyncio.run(ChatwootClient(_settings()).create_platform_user("Ada Yard", "ada@example.com", "Pasture-70601"))
    assert taken.value.status_code == 409
