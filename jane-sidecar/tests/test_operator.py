import json
import os

import pytest

from app.config import get_settings
from app.operator import CommandOutput, OperatorBackend, WriteConfirmationRequired, load_bootstrap_environment, render
from app.seed import DEMO_CONVERSATION_ID, DEMO_PROPERTY_ID


@pytest.fixture
def backend(store):
    store.properties[0]["display_name"] = "Lake Charles Homestead"
    store.properties[0]["email"] = "lake@example.com"
    store.properties[1]["display_name"] = "Rogers Homestead"
    store.properties[1]["email"] = "rogers@example.com"
    return OperatorBackend(store, get_settings())


async def test_dashboard_users_and_complete_user_view(backend):
    dashboard = await backend.dashboard()
    assert dashboard["mode"] == "minimum showcase"
    assert dashboard["homesteaders"] == 2
    assert dashboard["localities"] == 2
    assert dashboard["integrations"]["ollama_model"] == "qwen2.5:1.5b"

    users = await backend.users()
    assert users[0]["name"] == "Lake Charles Homestead"
    assert users[0]["locality"] == "Lake Charles & Calcasieu Suburbs"

    user = await backend.user("lake@example.com")
    assert user["identity"]["property_id"] == DEMO_PROPERTY_ID
    assert user["location"]["zip_code"] == "70601"
    assert user["northstar"]["northstar"]["automated"] == 25.0
    assert user["known_facts_ledger"]["active_goals"] == ["aquaponics"]


async def test_conversation_and_analyses_use_visible_history(backend, store):
    await store.append_transcript(
        conversation_id=DEMO_CONVERSATION_ID,
        message_id="operator-test-1",
        role="homesteader",
        speaker="Lake Charles Homestead",
        content="I want to improve the greenhouse.",
    )
    await store.append_transcript(
        conversation_id=DEMO_CONVERSATION_ID,
        message_id="operator-test-2",
        role="jane",
        speaker="Jane",
        content="Let us start with the water loop.",
    )
    chats = await backend.chats()
    assert next(row for row in chats if row["conversation_id"] == DEMO_CONVERSATION_ID)["messages"] == 2

    chat = await backend.chat(DEMO_CONVERSATION_ID)
    assert chat["messages"][0]["role"] == "homesteader"

    engagement = await backend.analyze("engagement")
    assert engagement["summary"]["active_in_private_thread"] == 1
    assert engagement["users"][0]["homesteader_messages"] == 1

    northstar = await backend.analyze("northstar")
    assert northstar["summary"]["homesteaders"] == 2
    assert northstar["summary"]["with_active_goals"] == 2

    network = await backend.analyze("network")
    assert network["summary"]["isolated_homesteaders"] == 2


async def test_command_dispatch_and_write_confirmation(backend, monkeypatch):
    output = await backend.execute(["analyze", "network"])
    assert output.title == "Analysis: network"

    with pytest.raises(WriteConfirmationRequired):
        await backend.execute(["connect", "lake@example.com", "rogers@example.com", "water", "catchment"])

    async def fake_open(_store, left, right, topic):
        return {"left": left, "right": right, "topic": topic, "existing": False}

    monkeypatch.setattr("app.operator.open_peer_conversation", fake_open)
    output = await backend.execute(
        ["connect", "lake@example.com", "rogers@example.com", "water", "catchment"],
        allow_write=True,
    )
    assert output.value["topic"] == "water catchment"

    with pytest.raises(WriteConfirmationRequired):
        await backend.execute(["set", "lake@example.com", "aesthetic", "82"])
    output = await backend.execute(["set", "lake@example.com", "aesthetic", "82"], allow_write=True)
    assert output.value["northstar"]["northstar"]["aesthetic"] == 82.0


async def test_capability_catalog_and_json_output(backend):
    output = await backend.execute(["capabilities"])
    areas = {row["area"]: row["status"] for row in output.value}
    assert areas["Private Jane chat"] == "active"
    assert areas["Reports, campaigns, help center"] == "unused"

    payload = json.loads(render(CommandOutput("Test", {"at": None, "ok": True}), as_json=True))
    assert payload == {"title": "Test", "data": {"at": None, "ok": True}}


def test_bootstrap_environment_is_loaded_without_overriding_explicit_values(tmp_path, monkeypatch):
    env_file = tmp_path / "chatwoot.env"
    env_file.write_text(
        "G01_CHATWOOT_API_TOKEN='from bootstrap'\n"
        "G01_CHATWOOT_ACCOUNT_ID=4\n"
        "UNRELATED_SECRET=do-not-load\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("G01_CHATWOOT_API_TOKEN", "")
    monkeypatch.setenv("G01_CHATWOOT_ACCOUNT_ID", "9")
    monkeypatch.delenv("UNRELATED_SECRET", raising=False)

    load_bootstrap_environment(str(env_file))

    assert get_settings().model_config["env_prefix"] == "G01_"
    assert os.environ["G01_CHATWOOT_API_TOKEN"] == "from bootstrap"
    assert os.environ["G01_CHATWOOT_ACCOUNT_ID"] == "9"
    assert "UNRELATED_SECRET" not in os.environ
