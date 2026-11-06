"""Apply a grounded decision to the property record and post Jane's reply."""

from datetime import datetime, timedelta, timezone

from app.config import get_settings
from app.delivery import deliver
from app.errors import G01Error
from app.epistemic import (
    affirmed_contained,
    affirmed_energy_profit,
    affirmed_material,
    affirmed_material_surplus,
    extract_aesthetic,
    extract_energetic_pct,
    extract_hours,
    extract_zip,
    gate_ledger_patch,
)
from app.heuristic import heuristic_decision, status_reply
from app.sanitize import sanitize_reply
from app.sourcing import format_ladder, haversine_miles
from app.sponsor_chat import file_sponsor_application, missing_fields, next_prompt, resend_sponsor_payment
from app.stripe_service import create_identity_session


def _rogers(locality: dict | None) -> bool:
    if not locality:
        return False
    return locality.get("primary_city", "").casefold() == "rogers" and locality.get("state_code", "").casefold() == "ar"


def _enforce_user_words(decision: dict, user_text: str) -> dict:
    """Drop any score the model asserted that the user did not actually say."""
    cleaned = dict(decision)
    extracted_hours = extract_hours(user_text)
    if cleaned.get("outside_aid_hours_per_week") is not None:
        if extracted_hours is None or float(extracted_hours) != float(cleaned["outside_aid_hours_per_week"]):
            cleaned["outside_aid_hours_per_week"] = extracted_hours
    extracted_aesthetic = extract_aesthetic(user_text)
    if cleaned.get("aesthetic_pct") is not None:
        if extracted_aesthetic is None or float(extracted_aesthetic) != float(cleaned["aesthetic_pct"]):
            cleaned["aesthetic_pct"] = extracted_aesthetic
    extracted_energy = extract_energetic_pct(user_text)
    if cleaned.get("energetic_pct") is not None:
        if extracted_energy is None or float(extracted_energy) != float(cleaned["energetic_pct"]):
            cleaned["energetic_pct"] = extracted_energy
    if cleaned.get("material_independent") is True and not affirmed_material(user_text):
        cleaned["material_independent"] = None
    if cleaned.get("material_surplus_profitable") is True and not affirmed_material_surplus(user_text):
        cleaned["material_surplus_profitable"] = None
    if cleaned.get("contained_zero_waste") is True and not affirmed_contained(user_text):
        cleaned["contained_zero_waste"] = None
    if cleaned.get("energetic_profitable") is True and not affirmed_energy_profit(user_text):
        cleaned["energetic_profitable"] = None
    return cleaned


async def open_demand_poll(store, prop: dict, topic: str, question: str) -> str:
    existing = await store.open_polls_for_requester(prop["id"])
    if any(poll["topic_slug"] == topic for poll in existing):
        return "That question is already with neighbors. I will synthesize it when 24 hours are up, and not before."
    settings = get_settings()
    mature_at = datetime.now(timezone.utc) + timedelta(hours=settings.poll_mature_hours)
    poll = await store.create_poll(
        {
            "requester_property_id": prop["id"],
            "locality_id": prop["locality_id"],
            "topic_slug": topic[:120],
            "question_sent_to_neighbors": question,
            "mature_at": mature_at,
        }
    )
    neighbors = [
        neighbor
        for neighbor in await store.list_local_properties(prop["locality_id"])
        if neighbor["id"] != prop["id"]
    ]
    await store.add_invites(poll["id"], neighbors)
    outbound = (
        question.strip()
        + f"\n\nReply in this exact form: DEMAND {poll['id']}: 2 units/week at $5 per unit."
    )
    for neighbor in neighbors:
        if neighbor.get("primary_conversation_id"):
            await deliver(store, neighbor["primary_conversation_id"], outbound)
    return (
        f"I asked {len(neighbors)} other homestead(s) in this locality. "
        "The synthesis waits until 24 hours from now. I will not invent their answers."
    )


async def commit_decision(store, message: dict, decision: dict, prop: dict | None, locality: dict | None) -> str:
    from app.collaboration import refresh_match_gate

    user_text = message.get("content") or ""
    decision = _enforce_user_words(decision, user_text)
    notes: list[str] = []

    if prop is None:
        zip_code = decision.get("zip_code") or extract_zip(user_text)
        contact_id = message.get("contact_id")
        found = await store.locality_for_zip(zip_code) if zip_code else None
        if found and contact_id and message.get("conversation_id"):
            prop = await store.create_property(
                {
                    "chatwoot_account_id": message.get("account_id") or get_settings().chatwoot_account_id,
                    "chatwoot_user_id": message.get("user_id"),
                    "chatwoot_contact_id": int(contact_id),
                    "primary_conversation_id": int(message["conversation_id"]),
                    "username": f"homesteader-{int(contact_id)}",
                    "locality_id": found["id"],
                    "zip_code": zip_code,
                    "lat": found["center_lat"],
                    "lng": found["center_lng"],
                }
            )
            locality = found
            notes.append(
                f"This thread is now the open homestead conversation for {found['name']} "
                f"(ZIP {zip_code}). The map pin is the locality center until you give me a precise latitude and longitude."
            )
            decision = _enforce_user_words(
                heuristic_decision(
                    {
                        "message": message,
                        "property": prop,
                        "locality": locality,
                        "invites": [],
                        "matches": [],
                    }
                ),
                user_text,
            )
        else:
            if zip_code and contact_id:
                reply = f"ZIP {zip_code} is outside every locality on the record. I did not attach this thread."
            else:
                reply = decision.get("reply") or "Tell me your ZIP code so I can attach this thread to a locality."
            final = sanitize_reply(reply, allow_walmart_name=False)
            await deliver(store, message.get("conversation_id"), final)
            return final

    if decision.get("outside_aid_hours_per_week") is not None:
        prop = await store.update_labor_hours(prop["id"], float(decision["outside_aid_hours_per_week"]))
    if decision.get("aesthetic_pct") is not None:
        prop = await store.update_aesthetic(prop["id"], float(decision["aesthetic_pct"]))
    profile = {}
    mapping = {
        "material_independent": "northstar_material_independent",
        "material_surplus_profitable": "material_surplus_profitable",
        "energetic_pct": "northstar_energetic_pct",
        "energetic_profitable": "northstar_energetic_profitable",
        "contained_zero_waste": "northstar_contained_zero_waste",
    }
    for source, column in mapping.items():
        if decision.get(source) is not None:
            profile[column] = decision[source]
    if decision.get("street_address"):
        profile["street_address"] = decision["street_address"]
        notes.append("I stored the street address on the property. I will not repeat it to neighbors.")
    if decision.get("property_lat") is not None and decision.get("property_lng") is not None and locality:
        miles = haversine_miles(
            float(locality["center_lat"]),
            float(locality["center_lng"]),
            float(decision["property_lat"]),
            float(decision["property_lng"]),
        )
        radius = float(locality.get("max_radius_miles") or 25)
        if miles <= radius:
            profile["lat"] = float(decision["property_lat"])
            profile["lng"] = float(decision["property_lng"])
            notes.append(f"The map pin is now {profile['lat']:.5f}, {profile['lng']:.5f}.")
        else:
            notes.append("That pin sits outside this locality, so I left the map pin where it was.")
    if profile:
        prop = await store.apply_profile_patch(prop["id"], profile)
    ledger = gate_ledger_patch(prop.get("known_facts_ledger") or {}, decision.get("ledger_patch") or {}, user_text)
    prop = await store.merge_ledger(prop["id"], ledger)

    if decision.get("report_scores"):
        fresh_locality = locality or await store.get_locality(prop["locality_id"])
        notes.append(status_reply(prop, fresh_locality))

    if decision.get("request_kyc"):
        if prop.get("kyc_verified"):
            notes.append("Your identity is already verified.")
        elif prop.get("stripe_identity_session_url") and not decision.get("reset_kyc"):
            notes.append(f"Use your existing Stripe Identity link: {prop['stripe_identity_session_url']}")
        else:
            try:
                session = await create_identity_session(prop["id"])
            except G01Error:
                notes.append("Stripe Identity is not configured, so I cannot verify you from this thread yet.")
            else:
                await store.set_identity_session(prop["id"], session["id"], session["url"])
                notes.append(f"Verify with Stripe Identity: {session['url']}")

    if decision.get("cancel_sponsor"):
        prop = await store.save_sponsor_draft(prop["id"], None)
    elif decision.get("sponsor_active"):
        draft = dict(prop.get("sponsor_draft") or {})
        draft.update(decision.get("sponsor_fields") or {})
        if "promo_code" in draft and str(draft["promo_code"]).casefold() == "none":
            draft.pop("promo_code", None)
        sponsor_locality = locality or await store.get_locality(prop["locality_id"])
        if missing_fields(draft):
            prop = await store.save_sponsor_draft(prop["id"], draft)
            notes.append(next_prompt(draft))
        else:
            notes.append(await file_sponsor_application(store, prop, sponsor_locality, draft))
            prop = await store.get_property(prop["id"])

    if decision.get("resend_payment_email"):
        notes.append(await resend_sponsor_payment(store, prop, decision.get("payment_email")))

    if decision.get("start_poll"):
        question = decision.get("poll_question") or "Would you buy any of this weekly, and at what price per unit?"
        topic = decision.get("poll_topic") or "local_demand"
        notes.append(await open_demand_poll(store, prop, topic, question))

    if decision.get("vote_poll_id"):
        await store.add_vote(
            decision["vote_poll_id"],
            prop["id"],
            user_text,
            float(decision.get("weekly_units") or 0),
            float(decision.get("price_per_unit") or 0),
        )

    if decision.get("match_id") and decision.get("match_decision"):
        await store.set_match_status(decision["match_id"], prop["id"], decision["match_decision"])
        notes.append(await refresh_match_gate(store, decision["match_id"], speaker_property_id=prop["id"]))

    if decision.get("service_tag"):
        rows = await store.rank_sponsors(prop["id"], decision["service_tag"], limit=5)
        source = str(message.get("event_id") or message.get("message_id") or prop["id"])
        await store.record_referrals(prop["id"], [row["sponsor_id"] for row in rows], decision["service_tag"], source)
        notes.append(format_ladder(decision["service_tag"].replace("_", " "), rows))

    allow_walmart = _rogers(locality)
    prose = sanitize_reply(decision.get("reply") or "", allow_walmart_name=allow_walmart)
    parts = [part for part in [prose, *notes] if part]
    final = sanitize_reply("\n\n".join(parts), allow_walmart_name=allow_walmart)
    await deliver(store, message.get("conversation_id"), final)
    return final
