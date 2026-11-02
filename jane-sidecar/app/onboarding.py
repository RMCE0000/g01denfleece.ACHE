"""Create the Chatwoot user, contact, and the one open thread with Jane."""

import re

from app.chatwoot_client import ChatwootClient
from app.config import get_settings
from app.delivery import deliver
from app.errors import G01Error

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


async def signup_homesteader(store, body: dict, client: ChatwootClient | None = None) -> dict:
    name = (body.get("name") or "").strip()
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    zip_code = (body.get("zip_code") or "").strip()
    if len(name) < 2:
        raise G01Error("name is required", 422)
    if not _EMAIL.match(email):
        raise G01Error("email is not valid", 422)
    if len(password) < 8:
        raise G01Error("password must be at least 8 characters", 422)
    locality = await store.locality_for_zip(zip_code)
    if not locality:
        raise G01Error("that ZIP is outside every g01 locality", 422)

    chatwoot = client or ChatwootClient(get_settings())
    if not chatwoot.platform_configured():
        raise G01Error("Chatwoot platform API is not configured", 503)

    user = await chatwoot.create_platform_user(name, email, password)
    user_id = int(user["id"])
    await chatwoot.add_account_user(user_id)
    contact = await chatwoot.create_contact(name, email)
    contact_id = int(contact["id"])
    conversation = await chatwoot.create_conversation(
        contact_id,
        f"This thread stays open. I'm Jane. {name}, tell me about the homestead when you're ready.",
    )
    conversation_id = int(conversation["id"])
    await chatwoot.add_participant(conversation_id, user_id)
    jane_id = get_settings().jane_user_id
    if jane_id and jane_id != user_id:
        await chatwoot.add_participant(conversation_id, int(jane_id))

    prop = await store.create_property(
        {
            "chatwoot_account_id": get_settings().chatwoot_account_id,
            "chatwoot_user_id": user_id,
            "chatwoot_contact_id": contact_id,
            "primary_conversation_id": conversation_id,
            "locality_id": locality["id"],
            "street_address": body.get("street_address"),
            "zip_code": zip_code,
            "lat": float(body["lat"]) if body.get("lat") is not None else locality["center_lat"],
            "lng": float(body["lng"]) if body.get("lng") is not None else locality["center_lng"],
        }
    )
    await deliver(
        store,
        conversation_id,
        "The five scores start from what you tell me: automated from labor hours, aesthetic from your own rating, "
        "material and contained as yes or no, and energetic as a percent plus whether surplus power sells at a profit. "
        "I won't send you to a chain.",
    )
    return prop
