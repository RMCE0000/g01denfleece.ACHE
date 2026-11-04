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
    assert areas["Contacts, labels, and custom fields"] == "active"
    assert areas["Reports"] == "administrator"
    assert areas["Jane daily and poll-mode questions"] == "active"

    payload = json.loads(render(CommandOutput("Test", {"at": None, "ok": True}), as_json=True))
    assert payload == {"title": "Test", "data": {"at": None, "ok": True}}


async def test_operator_can_create_inspect_and_analyze_polls(backend):
    with pytest.raises(WriteConfirmationRequired):
        await backend.execute(["poll-create", "What", "should", "we", "build?"])

    created = await backend.execute(
        ["poll-create", "What", "should", "we", "build?"],
        allow_write=True,
    )
    poll_id = created.value["poll"]["id"]
    assert created.value["recipients_added"] == 2

    listed = await backend.execute(["polls"])
    assert listed.value[0]["id"] == poll_id
    assert listed.value[0]["responses"] == "0/2"

    await backend.store.answer_community_poll(
        poll_id,
        backend.store.properties[0]["id"],
        "Build a seed library.",
    )
    inspected = await backend.execute(["poll", poll_id])
    assert inspected.value["analysis"]["response_count"] == 1
    analysis = await backend.execute(["analyze", "polls"])
    assert analysis.value["summary"]["responses"] == 1
    assert analysis.value["polls"][0]["action_candidates"][0]["answer"] == "Build a seed library."


async def test_operator_must_confirm_match_approval_before_users_are_pitched(backend, store):
    match = await store.create_match(
        {
            "locality_id": store.properties[0]["locality_id"],
            "peer_a_property_id": store.properties[0]["id"],
            "peer_b_property_id": store.properties[1]["id"],
            "proposed_project_title": "shared seed library",
            "jane_synergy_rationale": "Both recorded seed-library work.",
        }
    )
    pending = await backend.execute(["matches"])
    assert pending.value[0]["operator_status"] == "pending"
    assert store.outbox == []

    with pytest.raises(WriteConfirmationRequired):
        await backend.execute(["match-approve", match["id"], "Grounded", "proposal"])

    approved = await backend.execute(
        ["match-approve", match["id"], "Grounded", "proposal"],
        allow_write=True,
    )
    assert approved.value["match"]["operator_status"] == "approved"
    assert approved.value["match"]["operator_review_note"] == "Grounded proposal"
    assert len(approved.value["pitched_property_ids"]) == 2
    assert len(store.outbox) == 2

    rejected_match = await store.create_match(
        {
            "locality_id": store.properties[0]["locality_id"],
            "peer_a_property_id": store.properties[0]["id"],
            "peer_b_property_id": store.properties[1]["id"],
            "proposed_project_title": "second proposal",
            "jane_synergy_rationale": "A separate recorded proposal.",
        }
    )
    rejected = await backend.execute(
        ["match-reject", rejected_match["id"], "Not", "appropriate"],
        allow_write=True,
    )
    assert rejected.value["match"]["operator_status"] == "rejected"
    assert rejected.value["pitched_property_ids"] == []
    assert len(store.outbox) == 2


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
