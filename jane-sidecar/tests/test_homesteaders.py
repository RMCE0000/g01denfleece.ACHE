import asyncio

from fastapi.testclient import TestClient

from app.chatwoot_client import ChatwootClient
from app.config import get_settings
from app.main import create_app


class FakeChatwoot:
    calls = []
    seq = 800
    preexisting = {}
    orphaned = set()
    omit_custom_attributes = False

    def __init__(self, settings=None):
        self.settings = settings

    @classmethod
    def reset(cls):
        cls.calls = []
        cls.seq = 800
        cls.preexisting = {}
        cls.orphaned = set()
        cls.omit_custom_attributes = False

    def configured(self):
        return True

    def platform_configured(self):
        return True

    def _next(self):
        FakeChatwoot.seq += 1
        return FakeChatwoot.seq

    async def create_platform_user(self, name, email, password, signup_nonce=None):
        if email in FakeChatwoot.preexisting:
            user_id = FakeChatwoot.preexisting[email]
            FakeChatwoot.calls.append(("user", user_id, email))
            if email in FakeChatwoot.orphaned:
                return {
                    "id": user_id,
                    "name": name,
                    "email": email,
                    "custom_attributes": {"g01": True, "g01_signup": "old-attempt"},
                    "accounts": [],
                    "account_id": None,
                }
            return {"id": user_id, "name": name, "email": email, "custom_attributes": {}}
        user_id = self._next()
        FakeChatwoot.calls.append(("user", user_id, email))
        attributes = {"g01": True}
        if signup_nonce:
            attributes["g01_signup"] = signup_nonce
        user = {"id": user_id, "name": name, "email": email, "accounts": [], "account_id": None}
        if not FakeChatwoot.omit_custom_attributes:
            user["custom_attributes"] = attributes
        return user

    async def add_account_user(self, user_id, role="agent"):
        FakeChatwoot.calls.append(("account_user", int(user_id), role))
        return {"user_id": user_id, "role": role}

    async def open_agent_conversation(self, *, inbox_name, greeting, contact_name, contact_email, user_ids):
        FakeChatwoot.calls.append(("inbox", inbox_name, [int(user_id) for user_id in user_ids]))
        return {
            "inbox_id": self._next(),
            "contact_id": self._next(),
            "conversation_id": self._next(),
        }

    async def post_message(self, conversation_id, content):
        FakeChatwoot.calls.append(("message", int(conversation_id), content))
        return {"id": 1}

    async def set_contact_labels(self, contact_id, labels):
        FakeChatwoot.calls.append(("contact_labels", int(contact_id), labels))
        return {}

    async def update_contact_custom_attributes(self, contact_id, attributes):
        FakeChatwoot.calls.append(("contact_attributes", int(contact_id), attributes))
        return {}

    async def set_conversation_labels(self, conversation_id, labels):
        FakeChatwoot.calls.append(("conversation_labels", int(conversation_id), labels))
        return {}

    async def update_conversation_custom_attributes(self, conversation_id, attributes):
        FakeChatwoot.calls.append(("conversation_attributes", int(conversation_id), attributes))
        return {}

    async def sso_link(self, user_id):
        return f"http://localhost:3000/auth/sso?user={int(user_id)}"


def _person(name, email, zip_code, username=None):
    return {
        "name": name,
        "username": username or email.split("@", 1)[0],
        "email": email,
        "password": "Pasture-70601",
        "zip_code": zip_code,
    }


def test_admin_opens_sign_in_and_a_private_conversation(store, monkeypatch):
    FakeChatwoot.reset()
    monkeypatch.setenv("G01_ADMIN_TOKEN", "secret-admin")
    monkeypatch.setenv("G01_CHATWOOT_API_TOKEN", "api-token")
    monkeypatch.setenv("G01_CHATWOOT_PLATFORM_TOKEN", "platform-token")
    monkeypatch.setenv("G01_CHATWOOT_PUBLIC_URL", "http://localhost:3000")
    monkeypatch.setenv("G01_JANE_USER_ID", "4")
    get_settings.cache_clear()
    monkeypatch.setattr("app.homesteaders.ChatwootClient", FakeChatwoot)

    with TestClient(create_app(store)) as client:
        denied = client.post("/api/admin/homesteaders", json=_person("Ada Yard", "ada.yard@example.com", "70601"))
        assert denied.status_code == 401

        created = client.post(
            "/api/admin/homesteaders",
            headers={"x-g01-admin-token": "secret-admin"},
            json=_person("Ada Yard", "Ada.Yard@Example.com", "70601"),
        )
        assert created.status_code == 200
        ada = created.json()
        assert ada["existing"] is False
        assert ada["email"] == "ada.yard@example.com"
        assert ada["username"] == "ada.yard"
        assert ada["name"] == "Ada Yard"
        assert ada["login_url"] == "http://localhost:3000/app/login"
        assert ada["conversation_url"].startswith("http://localhost:3000/app/accounts/1/conversations/")
        assert ada["sso_url"].startswith("http://localhost:3000/auth/sso?user=")

        again = client.post(
            "/api/admin/homesteaders",
            headers={"x-g01-admin-token": "secret-admin"},
            json=_person("Ada Yard", "ada.yard@example.com", "70601"),
        )
        assert again.json()["existing"] is True
        assert again.json()["property_id"] == ada["property_id"]
        assert [kind for kind, *_rest in FakeChatwoot.calls].count("user") == 1

        client.post(
            "/api/admin/homesteaders",
            headers={"x-g01-admin-token": "secret-admin"},
            json=_person("Bea Chenier", "bea.chenier@example.com", "70605"),
        )
        outside = client.post(
            "/api/admin/homesteaders",
            headers={"x-g01-admin-token": "secret-admin"},
            json=_person("Cara North", "cara.north@example.com", "10001"),
        )
        assert outside.status_code == 422

        peer = client.post(
            "/api/admin/conversations",
            headers={"x-g01-admin-token": "secret-admin"},
            json={"left": "ada.yard@example.com", "right": str(ada["chatwoot_user_id"]), "topic": "the well"},
        )
        assert peer.status_code == 422

        opened = client.post(
            "/api/admin/conversations",
            headers={"x-g01-admin-token": "secret-admin"},
            json={"left": "ada.yard@example.com", "right": "bea.chenier@example.com", "topic": "the well"},
        )
        assert opened.status_code == 200
        body = opened.json()
        assert body["existing"] is False
        assert body["topic"] == "the well"
        assert "conversations/" in body["conversation_url"]

        swapped = client.post(
            "/api/admin/conversations",
            headers={"x-g01-admin-token": "secret-admin"},
            json={"left": "bea.chenier@example.com", "right": "ada.yard@example.com"},
        )
        assert swapped.json()["existing"] is True
        assert swapped.json()["conversation_id"] == body["conversation_id"]

        inbox_calls = [call for call in FakeChatwoot.calls if call[0] == "inbox"]
        assert inbox_calls[0][1] == "Jane — Ada Yard"
        assert 4 in inbox_calls[0][2]
        assert inbox_calls[-1][1] == "Ada Yard and Bea Chenier"
        assert set(inbox_calls[-1][2]) >= {ada["chatwoot_user_id"], 4}
        assert any(call[0] == "contact_labels" and call[2] == ["g01-homesteader"] for call in FakeChatwoot.calls)
        assert any(call[0] == "conversation_labels" and "g01-connection" in call[2] for call in FakeChatwoot.calls)
        assert any(
            call[0] == "conversation_attributes" and call[2].get("g01_kind") == "connection"
            for call in FakeChatwoot.calls
        )

        intro = [call for call in FakeChatwoot.calls if call[0] == "message" and "stay quiet" in call[2]]
        assert intro and "the well" in intro[0][2]
        assert any(call[0] == "message" and "Ada Yard and Bea Chenier" in call[2] for call in FakeChatwoot.calls)

        def _message(content, message_id):
            return {
                "event": "message_created",
                "id": message_id,
                "content": content,
                "message_type": "outgoing",
                "private": False,
                "content_attributes": {},
                "sender": {"id": 880, "type": "user"},
                "conversation": {"id": body["conversation_id"], "account_id": 1, "meta": {"sender": {"id": 880, "type": "contact"}}},
                "account": {"id": 1},
            }

        quiet = client.post("/webhooks/chatwoot", json=_message("The cistern is full.", 90))
        assert quiet.json()["ignored"] == "peer"
        named = client.post("/webhooks/chatwoot", json=_message("Jane, the cistern is full.", 91))
        assert named.status_code == 200
        assert named.json().get("ignored") != "peer"
        assert named.json()["reply"]


def test_login_page_signup_opens_a_sign_in(store, monkeypatch):
    FakeChatwoot.reset()
    monkeypatch.setenv("G01_CHATWOOT_API_TOKEN", "api-token")
    monkeypatch.setenv("G01_CHATWOOT_PLATFORM_TOKEN", "platform-token")
    monkeypatch.setenv("G01_CHATWOOT_PUBLIC_URL", "http://localhost:3000")
    monkeypatch.setenv("G01_JANE_USER_ID", "4")
    get_settings.cache_clear()
    monkeypatch.setattr("app.homesteaders.ChatwootClient", FakeChatwoot)

    with TestClient(create_app(store)) as client:
        created = client.post("/api/signup", json=_person("Cara North", "cara.north@example.com", "70607"))
        assert created.status_code == 200
        body = created.json()
        assert body["email"] == "cara.north@example.com"
        assert body["username"] == "cara.north"
        assert body["sso_url"].startswith("http://localhost:3000/auth/sso?user=")
        assert "api_access_token" not in body
        assert any(call[0] == "inbox" and call[1] == "Jane — Cara North" for call in FakeChatwoot.calls)

        FakeChatwoot.omit_custom_attributes = True
        older = client.post("/api/signup", json=_person("Sam Field", "sam.field@example.com", "70601"))
        assert older.status_code == 200
        assert older.json()["email"] == "sam.field@example.com"

        FakeChatwoot.preexisting["pat.orphaned@example.com"] = 78
        FakeChatwoot.orphaned.add("pat.orphaned@example.com")
        resumed = client.post("/api/signup", json=_person("Pat Orchard", "pat.orphaned@example.com", "70601"))
        assert resumed.status_code == 200
        assert resumed.json()["email"] == "pat.orphaned@example.com"

        again = client.post("/api/signup", json=_person("Cara North", "cara.north@example.com", "70607"))
        assert again.status_code == 409
        assert "sso_url" not in again.json()

        username_taken = client.post(
            "/api/signup",
            json=_person("Other Cara", "other.cara@example.com", "70601", username="cara.north"),
        )
        assert username_taken.status_code == 409
        assert "username" in username_taken.json()["detail"].lower()

        FakeChatwoot.preexisting["drew.existing@example.com"] = 77
        taken = client.post("/api/signup", json=_person("Drew Existing", "drew.existing@example.com", "70601"))
        assert taken.status_code == 409
        assert not any(call[0] == "inbox" and "Drew Existing" in call[1] for call in FakeChatwoot.calls)

        outside = client.post("/api/signup", json=_person("Cara North", "cara.other@example.com", "10001"))
        assert outside.status_code == 422


def test_chatwoot_bridge_dials_exact_username_without_member_directory(store, monkeypatch):
    FakeChatwoot.reset()
    monkeypatch.setenv("G01_CHATWOOT_API_TOKEN", "api-token")
    monkeypatch.setenv("G01_CHATWOOT_PLATFORM_TOKEN", "platform-token")
    monkeypatch.setenv("G01_CHATWOOT_PUBLIC_URL", "http://localhost:3000")
    monkeypatch.setenv("G01_JANE_USER_ID", "4")
    monkeypatch.setenv("G01_BRIDGE_SECRET", "bridge-secret")
    get_settings.cache_clear()
    monkeypatch.setattr("app.homesteaders.ChatwootClient", FakeChatwoot)

    with TestClient(create_app(store)) as client:
        client.post("/api/signup", json=_person("Ada Yard", "ada.community@example.com", "70601"))
        client.post("/api/signup", json=_person("Bea Chenier", "bea.community@example.com", "70605"))
        ada = next(row for row in store.properties if row.get("email") == "ada.community@example.com")
        bea = next(row for row in store.properties if row.get("email") == "bea.community@example.com")
        headers = {
            "x-g01-bridge-secret": "bridge-secret",
            "x-g01-account-id": "1",
            "x-g01-user-id": str(ada["chatwoot_user_id"]),
        }

        assert client.get("/api/internal/community", headers={**headers, "x-g01-bridge-secret": "wrong"}).status_code == 401
        directory = client.get("/api/internal/community", headers=headers)
        assert directory.status_code == 200
        assert directory.json()["connections"] == []
        assert directory.json()["self"]["username"] == "ada.community"
        assert "Bea Chenier" not in directory.text
        assert "bea.community" not in directory.text
        assert "email" not in directory.text
        assert "zip" not in directory.text

        missing = client.post(
            "/api/internal/community/connections",
            headers=headers,
            json={"username": "unknown.person", "topic": "seed exchange"},
        )
        assert missing.status_code == 404

        opened = client.post(
            "/api/internal/community/connections",
            headers=headers,
            json={"username": "@bea.community", "topic": "seed exchange"},
        )
        assert opened.status_code == 201
        assert opened.json()["conversation_path"].startswith("/app/accounts/1/conversations/")
        assert opened.json()["existing"] is False

        repeated = client.post(
            "/api/internal/community/connections",
            headers=headers,
            json={"username": "bea.community", "topic": "ignored duplicate topic"},
        )
        assert repeated.status_code == 200
        assert repeated.json()["conversation_id"] == opened.json()["conversation_id"]
        assert repeated.json()["existing"] is True
        connected = client.get("/api/internal/community", headers=headers).json()["connections"]
        assert connected[0]["username"] == "bea.community"
        assert connected[0]["name"] == "Bea Chenier"


def test_homesteader_routes_need_chatwoot(store, monkeypatch):
    monkeypatch.setenv("G01_ADMIN_TOKEN", "secret-admin")
    monkeypatch.setenv("G01_CHATWOOT_API_TOKEN", "")
    monkeypatch.setenv("G01_CHATWOOT_PLATFORM_TOKEN", "")
    get_settings.cache_clear()
    with TestClient(create_app(store)) as client:
        response = client.post(
            "/api/admin/homesteaders",
            headers={"x-g01-admin-token": "secret-admin"},
            json=_person("Ada Yard", "ada.yard@example.com", "70601"),
        )
        assert response.status_code == 503
        missing = client.post(
            "/api/admin/conversations",
            headers={"x-g01-admin-token": "secret-admin"},
            json={"left": "ada.yard@example.com", "right": "bea.chenier@example.com"},
        )
        assert missing.status_code == 404


def test_shared_conversation_seats_both_sign_ins(monkeypatch):
    calls = []

    async def _request(self, method, path, body=None, platform=False):
        calls.append((method, path, body))
        if path.endswith("/inboxes"):
            return {"id": 9, "name": body["name"]}
        if path.endswith("/inbox_members"):
            return {}
        if path.endswith("/contacts"):
            return {"id": 40}
        if path.endswith("/conversations"):
            return {"id": 12}
        if path.endswith("/participants"):
            return {}
        if path.endswith("/messages"):
            return {"id": 1}
        return {}

    monkeypatch.setenv("G01_CHATWOOT_API_TOKEN", "api-token")
    monkeypatch.setenv("G01_JANE_USER_ID", "4")
    get_settings.cache_clear()
    monkeypatch.setattr(ChatwootClient, "_request", _request)
    client = ChatwootClient()
    missing = asyncio.run(
        client.create_shared_conversation(
            {"chatwoot_contact_id": 1},
            {"chatwoot_user_id": 3, "chatwoot_contact_id": 2},
        )
    )
    assert missing is None
    assert calls == []

    opened = asyncio.run(
        client.create_shared_conversation(
            {"chatwoot_user_id": 2, "display_name": "Ada Yard", "chatwoot_contact_id": 1},
            {"chatwoot_user_id": 3, "display_name": "Bea Chenier", "chatwoot_contact_id": 2},
        )
    )
    assert opened == 12
    members = next(body for _method, path, body in calls if path.endswith("/inbox_members"))
    assert members["user_ids"] == [2, 3, 4]
    participants = next(body for _method, path, body in calls if path.endswith("/participants"))
    assert participants["user_ids"] == [2, 3, 4]
    assert any(body and body.get("content_attributes", {}).get("g01_author") == "jane" for _method, path, body in calls if path.endswith("/messages"))
    calls.clear()
    awaitable = client.open_agent_conversation(
        inbox_name="Jane — Ada Yard",
        greeting="open",
        contact_name="Ada Yard",
        contact_email="ada.yard@example.com",
        user_ids=[2, 4],
    )
    opened_one = asyncio.run(awaitable)
    assert opened_one["conversation_id"] == 12
    created = next(body for _method, path, body in calls if path.endswith("/conversations") and _method == "POST")
    assert created["assignee_id"] == 2
