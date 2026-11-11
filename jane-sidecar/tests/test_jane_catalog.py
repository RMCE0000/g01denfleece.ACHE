"""Jane offers only filed insurance, and she sees knowledge only for the topic at hand."""

import asyncio

from app.epistemic import affirmed_defensible, affirmed_insured, extract_utilized
from app.gemini_flow import gemini_override
from app.jane_catalog import render_catalog, select_knowledge
from app.config import get_settings
from app.operator import OperatorBackend, WriteConfirmationRequired
from app.seed import DEMO_CONTACT_ID, DEMO_CONVERSATION_ID, DEMO_USER_ID


def _backend(store):
    store.properties[0]["display_name"] = "Lake Charles Homestead"
    store.properties[0]["email"] = "lake@example.com"
    return OperatorBackend(store, get_settings())


def test_a_wish_for_coverage_is_not_a_perfectly_insured_homestead():
    assert affirmed_insured("We are perfectly insured.")
    assert affirmed_insured("The property and all homesteaders are perfectly insured.")
    assert not affirmed_insured("I want insurance for the barn.")
    assert not affirmed_insured("Can you quote a policy?")
    assert extract_utilized("The property is fully recorded on our financial tools.") == 100
    assert extract_utilized("It is not recorded on any financial tools.") == 0
    assert extract_utilized("Utilized 40 on the financial tools.") == 40
    assert extract_utilized("The pressure tank is short-cycling.") is None
    assert affirmed_defensible("The property can defend against invasion.")
    assert affirmed_defensible("We can defend the homestead against invasion.")
    assert not affirmed_defensible("I want the place to be able to defend against invasion.")
    assert not affirmed_defensible("We have a fence and a dog.")


def test_knowledge_is_selected_by_topic_and_drafts_stay_out_of_the_note():
    products = [
        {"name": "Dwelling", "covers": "the house", "summary": "Covers the dwelling.", "status": "offered"},
        {"name": "Draft barn", "covers": "the barn", "summary": "Not ready.", "status": "draft"},
    ]
    knowledge = [
        {"title": "Dwelling terms", "topics": ["dwelling", "house"], "body": "The deductible is stated here."},
        {"title": "Well terms", "topics": ["well"], "body": "A well limit that must not leak into a house question."},
    ]
    assert [row["title"] for row in select_knowledge(knowledge, "What does dwelling cover?")] == ["Dwelling terms"]
    note = render_catalog(products, knowledge, "The pressure tank is short-cycling.")
    assert "Dwelling: covers the house." in note
    assert "Draft barn" not in note
    assert "deductible is stated here" not in note
    assert "well limit" not in note
    house = render_catalog(products, knowledge, "Tell me about dwelling insurance.")
    assert "deductible is stated here" in house
    assert "well limit" not in house
    empty = render_catalog([], [], "What can you insure?")
    assert "Products Jane may offer: none." in empty


async def test_operator_files_a_product_the_way_a_sponsor_is_filed(store):
    backend = _backend(store)
    try:
        await backend.execute(
            ["product-add", "Dwelling", "the house", "Covers the dwelling.", "offered"]
        )
    except WriteConfirmationRequired:
        pass
    else:
        raise AssertionError("filing a product must ask before it writes")
    created = await backend.execute(
        ["product-add", "Dwelling", "the house", "Covers the dwelling.", "offered"],
        allow_write=True,
    )
    product_id = created.value["id"]
    assert created.value["status"] == "offered"
    drafted = await backend.execute(
        ["product-add", "Livestock", "the animals", "Not offered yet.", "draft"],
        allow_write=True,
    )
    offered = await backend.products("offered")
    assert [row["name"] for row in offered] == ["Dwelling"]
    await backend.execute(["product-withdraw", product_id], allow_write=True)
    assert await backend.products("offered") == []
    entry = await backend.execute(
        ["knowledge-add", "Dwelling terms", "dwelling, house", "The deductible is one season's hay."],
        allow_write=True,
    )
    assert entry.value["topics"] == ["dwelling", "house"]
    await backend.execute(["knowledge-remove", entry.value["id"]], allow_write=True)
    assert await backend.knowledge() == []
    assert drafted.value["status"] == "draft"


def _message(content, message_id):
    return {
        "event": "message_created",
        "id": message_id,
        "content": content,
        "message_type": "outgoing",
        "private": False,
        "sender": {"id": DEMO_USER_ID, "type": "user", "name": "Ada"},
        "conversation": {
            "id": DEMO_CONVERSATION_ID,
            "account_id": 1,
            "meta": {"sender": {"id": DEMO_CONTACT_ID, "type": "contact"}},
        },
        "account": {"id": 1},
    }


def test_jane_is_told_the_offered_product_and_not_the_draft(client, store):
    asyncio.run(
        store.create_jane_product(
            {"name": "Dwelling", "covers": "the house", "summary": "Covers the dwelling.", "status": "offered"}
        )
    )
    asyncio.run(
        store.create_jane_product(
            {"name": "Secret barn", "covers": "the barn", "summary": "Do not say this.", "status": "draft"}
        )
    )
    asyncio.run(
        store.create_jane_knowledge(
            {"title": "Dwelling terms", "topics": ["dwelling"], "body": "The deductible is one season's hay."}
        )
    )
    seen = []

    def think(_model, messages, _complexity):
        seen.append(messages[0].content)
        return "Dwelling is filed. I have not bound it."

    token = gemini_override.set(think)
    try:
        quiet = client.post("/webhooks/chatwoot", json=_message("The pressure tank is short-cycling.", 910))
        asked = client.post("/webhooks/chatwoot", json=_message("What dwelling insurance can you offer?", 911))
    finally:
        gemini_override.reset(token)

    assert quiet.status_code == 200
    assert "Dwelling: covers the house." in seen[0]
    assert "Secret barn" not in seen[0]
    assert "one season's hay" not in seen[0]
    assert asked.status_code == 200
    assert "one season's hay" in seen[1]
    assert "not a bound policy" in seen[1]
    assert "Secret barn" not in seen[1]
