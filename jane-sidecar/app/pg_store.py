"""Postgres store. Ranking goes through g01_rank_local_sponsors so the SQL formula is the one that runs."""

import json
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from app.errors import G01Error
from app.northstar import DEFAULT_LEDGER

_PROPERTY = """
id, chatwoot_account_id, chatwoot_user_id, chatwoot_contact_id, primary_conversation_id,
locality_id, street_address, zip_code, lat, lng,
northstar_automated_pct, outside_aid_hours_per_week, northstar_aesthetic_pct,
northstar_material_independent, material_surplus_profitable,
northstar_energetic_pct, northstar_energetic_profitable, northstar_contained_zero_waste,
known_facts_ledger, sponsor_draft, kyc_verified, stripe_identity_session_id, updated_at
"""

_SPONSOR = """
id, property_id, locality_id, company_name, founding_city, founding_state, is_franchise_or_chain,
sourcing_tier, service_tags, capabilities_summary, lat, lng, referrals_last_14d, last_referred_at,
homesteader_rating, promo_boost_weight, stripe_customer_id, stripe_subscription_id,
applied_promo_code, is_active_sponsor, created_at
"""


def _clean(value):
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean(item) for item in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    return value


class PostgresStore:
    def __init__(self, database_url: str, schema_path: str):
        self.schema_path = schema_path
        self.engine = create_async_engine(database_url, pool_pre_ping=True)

    async def close(self) -> None:
        await self.engine.dispose()

    async def apply_schema(self) -> None:
        sql = Path(self.schema_path).read_text(encoding="utf-8")
        async with self.engine.begin() as conn:
            raw = await conn.get_raw_connection()
            await raw.driver_connection.execute(sql)

    async def _all(self, sql: str, params: dict | None = None) -> list[dict]:
        async with self.engine.connect() as conn:
            result = await conn.execute(text(sql), params or {})
            return [_clean(dict(row)) for row in result.mappings().all()]

    async def _one(self, sql: str, params: dict | None = None) -> dict | None:
        rows = await self._all(sql, params)
        return rows[0] if rows else None

    async def _write(self, sql: str, params: dict | None = None) -> list[dict]:
        async with self.engine.begin() as conn:
            result = await conn.execute(text(sql), params or {})
            if not result.returns_rows:
                return []
            return [_clean(dict(row)) for row in result.mappings().all()]

    async def list_localities(self) -> list[dict]:
        return await self._all(
            """
            SELECT id, name, primary_city, state_code, allowed_zip_codes, center_lat, center_lng, max_radius_miles
            FROM g01_localities ORDER BY primary_city
            """
        )

    async def get_locality(self, locality_id: str) -> dict | None:
        return await self._one(
            """
            SELECT id, name, primary_city, state_code, allowed_zip_codes, center_lat, center_lng, max_radius_miles
            FROM g01_localities WHERE id = CAST(:id AS uuid)
            """,
            {"id": locality_id},
        )

    async def locality_for_zip(self, zip_code: str) -> dict | None:
        return await self._one(
            """
            SELECT id, name, primary_city, state_code, allowed_zip_codes, center_lat, center_lng, max_radius_miles
            FROM g01_localities WHERE :zip = ANY(allowed_zip_codes)
            """,
            {"zip": zip_code},
        )

    async def create_property(self, fields: dict) -> dict:
        existing = await self.get_property_by_contact(int(fields["chatwoot_contact_id"]))
        if existing:
            return existing
        ledger = json.dumps(fields.get("known_facts_ledger") or DEFAULT_LEDGER)
        try:
            rows = await self._write(
                f"""
                INSERT INTO g01_properties (
                    chatwoot_account_id, chatwoot_user_id, chatwoot_contact_id, primary_conversation_id,
                    locality_id, street_address, zip_code, lat, lng, known_facts_ledger
                ) VALUES (
                    :account_id, :user_id, :contact_id, :conversation_id,
                    CAST(:locality_id AS uuid), :street, :zip, :lat, :lng, CAST(:ledger AS jsonb)
                )
                RETURNING {_PROPERTY}
                """,
                {
                    "account_id": int(fields["chatwoot_account_id"]),
                    "user_id": fields.get("chatwoot_user_id"),
                    "contact_id": int(fields["chatwoot_contact_id"]),
                    "conversation_id": fields.get("primary_conversation_id"),
                    "locality_id": fields["locality_id"],
                    "street": fields.get("street_address"),
                    "zip": fields["zip_code"],
                    "lat": float(fields["lat"]),
                    "lng": float(fields["lng"]),
                    "ledger": ledger,
                },
            )
        except IntegrityError as exc:
            existing = await self.get_property_by_contact(int(fields["chatwoot_contact_id"]))
            if existing:
                return existing
            raise G01Error("could not create property", 409) from exc
        return rows[0]

    async def get_property(self, property_id: str) -> dict | None:
        return await self._one(
            f"SELECT {_PROPERTY} FROM g01_properties WHERE id = CAST(:id AS uuid)",
            {"id": property_id},
        )

    async def get_property_by_contact(self, contact_id: int) -> dict | None:
        return await self._one(
            f"SELECT {_PROPERTY} FROM g01_properties WHERE chatwoot_contact_id = :contact_id",
            {"contact_id": int(contact_id)},
        )

    async def get_property_by_conversation(self, conversation_id: int) -> dict | None:
        return await self._one(
            f"SELECT {_PROPERTY} FROM g01_properties WHERE primary_conversation_id = :conversation_id",
            {"conversation_id": int(conversation_id)},
        )

    async def get_property_by_user(self, user_id: int) -> dict | None:
        return await self._one(
            f"SELECT {_PROPERTY} FROM g01_properties WHERE chatwoot_user_id = :user_id",
            {"user_id": int(user_id)},
        )

    async def update_aesthetic(self, property_id: str, aesthetic: float) -> dict:
        rows = await self._write(
            f"""
            UPDATE g01_properties
            SET northstar_aesthetic_pct = :aesthetic
            WHERE id = CAST(:id AS uuid)
            RETURNING {_PROPERTY}
            """,
            {"id": property_id, "aesthetic": aesthetic},
        )
        if not rows:
            raise G01Error("property not found", 404)
        return rows[0]

    async def update_labor_hours(self, property_id: str, hours: float) -> dict:
        if hours < 0:
            raise G01Error("hours cannot be negative", 422)
        rows = await self._write(
            f"""
            UPDATE g01_properties
            SET outside_aid_hours_per_week = :hours
            WHERE id = CAST(:id AS uuid)
            RETURNING {_PROPERTY}
            """,
            {"id": property_id, "hours": hours},
        )
        if not rows:
            raise G01Error("property not found", 404)
        return rows[0]

    async def apply_profile_patch(self, property_id: str, fields: dict) -> dict:
        allowed = {
            "northstar_material_independent": "northstar_material_independent",
            "material_surplus_profitable": "material_surplus_profitable",
            "northstar_energetic_pct": "northstar_energetic_pct",
            "northstar_energetic_profitable": "northstar_energetic_profitable",
            "northstar_contained_zero_waste": "northstar_contained_zero_waste",
            "street_address": "street_address",
            "lat": "lat",
            "lng": "lng",
        }
        sets = []
        params: dict = {"id": property_id}
        for key, column in allowed.items():
            if key in fields and fields[key] is not None:
                sets.append(f"{column} = :{key}")
                params[key] = fields[key]
        if not sets:
            found = await self.get_property(property_id)
            if not found:
                raise G01Error("property not found", 404)
            return found
        rows = await self._write(
            f"UPDATE g01_properties SET {', '.join(sets)} WHERE id = CAST(:id AS uuid) RETURNING {_PROPERTY}",
            params,
        )
        if not rows:
            raise G01Error("property not found", 404)
        return rows[0]

    async def save_sponsor_draft(self, property_id: str, draft: dict | None) -> dict:
        rows = await self._write(
            f"""
            UPDATE g01_properties
            SET sponsor_draft = CAST(:draft AS jsonb)
            WHERE id = CAST(:id AS uuid)
            RETURNING {_PROPERTY}
            """,
            {"id": property_id, "draft": json.dumps(draft) if draft else None},
        )
        if not rows:
            raise G01Error("property not found", 404)
        return rows[0]

    async def merge_ledger(self, property_id: str, ledger: dict) -> dict:
        rows = await self._write(
            f"""
            UPDATE g01_properties
            SET known_facts_ledger = CAST(:ledger AS jsonb)
            WHERE id = CAST(:id AS uuid)
            RETURNING {_PROPERTY}
            """,
            {"id": property_id, "ledger": json.dumps(ledger)},
        )
        if not rows:
            raise G01Error("property not found", 404)
        return rows[0]

    async def set_goals_embedding(self, property_id: str, vector: list[float] | None) -> None:
        literal = None if vector is None else "[" + ",".join(f"{float(item):.8f}" for item in vector) + "]"
        await self._write(
            """
            UPDATE g01_properties
            SET goals_embedding = CAST(:embedding AS vector)
            WHERE id = CAST(:id AS uuid)
            """,
            {"id": property_id, "embedding": literal},
        )

    async def list_local_properties(self, locality_id: str) -> list[dict]:
        return await self._all(
            f"SELECT {_PROPERTY} FROM g01_properties WHERE locality_id = CAST(:id AS uuid)",
            {"id": locality_id},
        )

    async def create_promo(self, fields: dict) -> dict:
        rows = await self._write(
            """
            INSERT INTO g01_promo_codes (
                code, stripe_coupon_id, discount_percent, recommendation_boost, restricted_locality_id, max_uses
            ) VALUES (
                :code, :coupon, :discount, :boost, CAST(:locality AS uuid), :max_uses
            )
            RETURNING code, stripe_coupon_id, discount_percent, recommendation_boost,
                      restricted_locality_id, max_uses, current_uses, active
            """,
            {
                "code": fields["code"].strip().upper(),
                "coupon": fields["stripe_coupon_id"],
                "discount": int(fields["discount_percent"]),
                "boost": float(fields.get("recommendation_boost", 1)),
                "locality": fields.get("restricted_locality_id"),
                "max_uses": int(fields.get("max_uses", 100)),
            },
        )
        return rows[0]

    async def get_promo(self, code: str) -> dict | None:
        return await self._one(
            """
            SELECT code, stripe_coupon_id, discount_percent, recommendation_boost,
                   restricted_locality_id, max_uses, current_uses, active
            FROM g01_promo_codes WHERE code = :code
            """,
            {"code": (code or "").strip().upper()},
        )

    async def consume_promo(self, code: str) -> dict:
        rows = await self._write(
            """
            UPDATE g01_promo_codes
            SET current_uses = current_uses + 1
            WHERE code = :code AND active AND current_uses < max_uses
            RETURNING code, stripe_coupon_id, discount_percent, recommendation_boost,
                      restricted_locality_id, max_uses, current_uses, active
            """,
            {"code": code.strip().upper()},
        )
        if not rows:
            raise G01Error("promo code is not usable", 422)
        return rows[0]

    async def create_sponsor(self, fields: dict) -> dict:
        # The origin trigger is the database backstop. Validate first so the API gets a clean 422.
        from app.sourcing import sponsor_rejection_reason

        locality = await self.get_locality(fields["locality_id"])
        if not locality:
            raise G01Error("locality not found", 404)
        reason = sponsor_rejection_reason(
            company_name=fields["company_name"],
            is_franchise_or_chain=bool(fields.get("is_franchise_or_chain")),
            locality_city=locality["primary_city"],
            locality_state=locality["state_code"],
            founding_city=fields["founding_city"],
            founding_state=fields["founding_state"],
            capabilities_summary=fields.get("capabilities_summary", ""),
        )
        if reason:
            raise G01Error(reason, 422)
        try:
            rows = await self._write(
                f"""
                INSERT INTO g01_sponsors (
                    property_id, locality_id, company_name, founding_city, founding_state,
                    is_franchise_or_chain, sourcing_tier, service_tags, capabilities_summary,
                    lat, lng, applied_promo_code, is_active_sponsor
                ) VALUES (
                    CAST(:property_id AS uuid), CAST(:locality_id AS uuid), :company_name, :founding_city, :founding_state,
                    :franchise, :tier, string_to_array(:tags, ','), :summary,
                    :lat, :lng, :promo, :active
                )
                RETURNING {_SPONSOR}
                """,
                {
                    "property_id": fields.get("property_id"),
                    "locality_id": fields["locality_id"],
                    "company_name": fields["company_name"].strip(),
                    "founding_city": fields["founding_city"].strip(),
                    "founding_state": fields["founding_state"].strip(),
                    "franchise": bool(fields.get("is_franchise_or_chain")),
                    "tier": fields["sourcing_tier"],
                    "tags": ",".join(fields["service_tags"]),
                    "summary": fields["capabilities_summary"].strip(),
                    "lat": float(fields["lat"]),
                    "lng": float(fields["lng"]),
                    "promo": fields.get("applied_promo_code"),
                    "active": bool(fields.get("is_active_sponsor", False)),
                },
            )
        except IntegrityError as exc:
            raise G01Error("sponsor was rejected by the registry", 422) from exc
        return rows[0]

    async def get_sponsor(self, sponsor_id: str) -> dict | None:
        return await self._one(
            f"SELECT {_SPONSOR} FROM g01_sponsors WHERE id = CAST(:id AS uuid)",
            {"id": sponsor_id},
        )

    async def rank_sponsors(self, property_id: str, service_tag: str, limit: int = 5) -> list[dict]:
        return await self._all(
            """
            SELECT sponsor_id, company_name, sourcing_tier, tier_weight, distance_miles, score,
                   promo_boost_weight, referrals_last_14d, homesteader_rating
            FROM g01_rank_local_sponsors(CAST(:property_id AS uuid), :service_tag, :limit)
            """,
            {"property_id": property_id, "service_tag": service_tag, "limit": limit},
        )

    async def record_referrals(self, property_id: str, sponsor_ids: list[str], service_tag: str, source_event_id: str) -> None:
        for sponsor_id in sponsor_ids:
            await self._write(
                """
                INSERT INTO g01_referral_events (sponsor_id, property_id, service_tag, source_event_id)
                VALUES (CAST(:sponsor_id AS uuid), CAST(:property_id AS uuid), :tag, :source)
                ON CONFLICT (source_event_id) DO NOTHING
                """,
                {
                    "sponsor_id": sponsor_id,
                    "property_id": property_id,
                    "tag": service_tag,
                    "source": f"{source_event_id}:{sponsor_id}",
                },
            )
        await self.recount_referrals()

    async def recount_referrals(self) -> None:
        await self._write("SELECT g01_recount_referrals()")

    async def create_poll(self, fields: dict) -> dict:
        rows = await self._write(
            """
            INSERT INTO g01_demand_polls (
                requester_property_id, locality_id, topic_slug, question_sent_to_neighbors, mature_at
            ) VALUES (
                CAST(:requester AS uuid), CAST(:locality AS uuid), :topic, :question, :mature_at
            )
            RETURNING id, requester_property_id, locality_id, topic_slug, question_sent_to_neighbors,
                      status, mature_at, final_synthesis_report, created_at
            """,
            {
                "requester": fields["requester_property_id"],
                "locality": fields["locality_id"],
                "topic": fields["topic_slug"],
                "question": fields["question_sent_to_neighbors"],
                "mature_at": fields["mature_at"],
            },
        )
        return rows[0]

    async def add_invites(self, poll_id: str, neighbors: list[dict]) -> None:
        for neighbor in neighbors:
            await self._write(
                """
                INSERT INTO g01_poll_invites (poll_id, neighbor_property_id, conversation_id)
                VALUES (CAST(:poll_id AS uuid), CAST(:neighbor AS uuid), :conversation_id)
                ON CONFLICT (poll_id, neighbor_property_id) DO NOTHING
                """,
                {
                    "poll_id": poll_id,
                    "neighbor": neighbor["id"],
                    "conversation_id": neighbor.get("primary_conversation_id"),
                },
            )

    async def open_invites_for_property(self, property_id: str) -> list[dict]:
        return await self._all(
            """
            SELECT i.id, i.poll_id, i.neighbor_property_id, i.conversation_id,
                   p.question_sent_to_neighbors, p.topic_slug
            FROM g01_poll_invites i
            JOIN g01_demand_polls p ON p.id = i.poll_id
            WHERE i.neighbor_property_id = CAST(:property_id AS uuid)
              AND p.status = 'polling'
              AND NOT EXISTS (
                  SELECT 1 FROM g01_poll_votes v
                  WHERE v.poll_id = i.poll_id AND v.neighbor_property_id = i.neighbor_property_id
              )
            """,
            {"property_id": property_id},
        )

    async def add_vote(self, poll_id: str, neighbor_property_id: str, raw_reply: str, weekly_units: float, price: float) -> dict:
        rows = await self._write(
            """
            INSERT INTO g01_poll_votes (
                poll_id, neighbor_property_id, raw_reply, weekly_units_demanded, willing_price_per_unit_usd
            ) VALUES (
                CAST(:poll_id AS uuid), CAST(:neighbor AS uuid), :raw, :units, :price
            )
            ON CONFLICT (poll_id, neighbor_property_id) DO NOTHING
            RETURNING id, poll_id, neighbor_property_id, raw_reply, weekly_units_demanded, willing_price_per_unit_usd, created_at
            """,
            {
                "poll_id": poll_id,
                "neighbor": neighbor_property_id,
                "raw": raw_reply,
                "units": weekly_units,
                "price": price,
            },
        )
        if rows:
            return rows[0]
        found = await self._one(
            """
            SELECT id, poll_id, neighbor_property_id, raw_reply, weekly_units_demanded, willing_price_per_unit_usd, created_at
            FROM g01_poll_votes
            WHERE poll_id = CAST(:poll_id AS uuid) AND neighbor_property_id = CAST(:neighbor AS uuid)
            """,
            {"poll_id": poll_id, "neighbor": neighbor_property_id},
        )
        return found

    async def get_poll(self, poll_id: str) -> dict | None:
        return await self._one(
            """
            SELECT id, requester_property_id, locality_id, topic_slug, question_sent_to_neighbors,
                   status, mature_at, final_synthesis_report, created_at
            FROM g01_demand_polls WHERE id = CAST(:id AS uuid)
            """,
            {"id": poll_id},
        )

    async def votes_for_poll(self, poll_id: str) -> list[dict]:
        return await self._all(
            """
            SELECT id, poll_id, neighbor_property_id, raw_reply, weekly_units_demanded,
                   willing_price_per_unit_usd, created_at
            FROM g01_poll_votes WHERE poll_id = CAST(:id AS uuid)
            """,
            {"id": poll_id},
        )

    async def mature_polls(self) -> list[dict]:
        return await self._all(
            """
            SELECT id, requester_property_id, locality_id, topic_slug, question_sent_to_neighbors,
                   status, mature_at, final_synthesis_report, created_at
            FROM g01_demand_polls
            WHERE status = 'polling' AND mature_at <= NOW()
            """
        )

    async def complete_poll(self, poll_id: str, report: str) -> dict:
        rows = await self._write(
            """
            UPDATE g01_demand_polls
            SET status = 'completed', final_synthesis_report = :report
            WHERE id = CAST(:id AS uuid)
            RETURNING id, requester_property_id, locality_id, topic_slug, question_sent_to_neighbors,
                      status, mature_at, final_synthesis_report, created_at
            """,
            {"id": poll_id, "report": report},
        )
        if not rows:
            raise G01Error("poll not found", 404)
        return rows[0]

    async def create_match(self, fields: dict) -> dict | None:
        peer_a, peer_b = sorted([fields["peer_a_property_id"], fields["peer_b_property_id"]])
        rows = await self._write(
            """
            INSERT INTO g01_neighbor_matches (
                locality_id, peer_a_property_id, peer_b_property_id, proposed_project_title, jane_synergy_rationale
            ) VALUES (
                CAST(:locality AS uuid), CAST(:peer_a AS uuid), CAST(:peer_b AS uuid), :title, :rationale
            )
            ON CONFLICT (peer_a_property_id, peer_b_property_id, proposed_project_title) DO NOTHING
            RETURNING id, locality_id, peer_a_property_id, peer_b_property_id, proposed_project_title,
                      jane_synergy_rationale, peer_a_status, peer_b_status, shared_chatwoot_conversation_id, created_at
            """,
            {
                "locality": fields["locality_id"],
                "peer_a": peer_a,
                "peer_b": peer_b,
                "title": fields["proposed_project_title"],
                "rationale": fields["jane_synergy_rationale"],
            },
        )
        return rows[0] if rows else None

    async def get_match(self, match_id: str) -> dict | None:
        return await self._one(
            """
            SELECT id, locality_id, peer_a_property_id, peer_b_property_id, proposed_project_title,
                   jane_synergy_rationale, peer_a_status, peer_b_status, shared_chatwoot_conversation_id, created_at
            FROM g01_neighbor_matches WHERE id = CAST(:id AS uuid)
            """,
            {"id": match_id},
        )

    async def matches_for_property(self, property_id: str) -> list[dict]:
        return await self._all(
            """
            SELECT id, locality_id, peer_a_property_id, peer_b_property_id, proposed_project_title,
                   jane_synergy_rationale, peer_a_status, peer_b_status, shared_chatwoot_conversation_id, created_at
            FROM g01_neighbor_matches
            WHERE (peer_a_property_id = CAST(:id AS uuid) OR peer_b_property_id = CAST(:id AS uuid))
              AND shared_chatwoot_conversation_id IS NULL
              AND peer_a_status <> 'declined'
              AND peer_b_status <> 'declined'
            """,
            {"id": property_id},
        )

    async def set_match_status(self, match_id: str, peer_property_id: str, status: str) -> dict:
        match = await self.get_match(match_id)
        if not match:
            raise G01Error("match not found", 404)
        if match["peer_a_property_id"] == peer_property_id:
            column = "peer_a_status"
        elif match["peer_b_property_id"] == peer_property_id:
            column = "peer_b_status"
        else:
            raise G01Error("property is not on this match", 404)
        rows = await self._write(
            f"""
            UPDATE g01_neighbor_matches SET {column} = :status
            WHERE id = CAST(:id AS uuid)
            RETURNING id, locality_id, peer_a_property_id, peer_b_property_id, proposed_project_title,
                      jane_synergy_rationale, peer_a_status, peer_b_status, shared_chatwoot_conversation_id, created_at
            """,
            {"id": match_id, "status": status},
        )
        return rows[0]

    async def set_shared_conversation(self, match_id: str, conversation_id: int) -> dict:
        rows = await self._write(
            """
            UPDATE g01_neighbor_matches
            SET shared_chatwoot_conversation_id = :conversation_id
            WHERE id = CAST(:id AS uuid)
            RETURNING id, locality_id, peer_a_property_id, peer_b_property_id, proposed_project_title,
                      jane_synergy_rationale, peer_a_status, peer_b_status, shared_chatwoot_conversation_id, created_at
            """,
            {"id": match_id, "conversation_id": int(conversation_id)},
        )
        if not rows:
            raise G01Error("match not found", 404)
        return rows[0]

    async def ready_matches_without_thread(self) -> list[dict]:
        rows = await self._all(
            """
            SELECT m.id, m.locality_id, m.peer_a_property_id, m.peer_b_property_id, m.proposed_project_title,
                   m.jane_synergy_rationale, m.peer_a_status, m.peer_b_status, m.shared_chatwoot_conversation_id, m.created_at
            FROM g01_neighbor_matches m
            JOIN g01_properties a ON a.id = m.peer_a_property_id
            JOIN g01_properties b ON b.id = m.peer_b_property_id
            WHERE m.shared_chatwoot_conversation_id IS NULL
              AND m.peer_a_status = 'accepted'
              AND m.peer_b_status = 'accepted'
              AND a.kyc_verified
              AND b.kyc_verified
            """
        )
        return rows

    async def mark_event(self, event_id: str) -> bool:
        rows = await self._write(
            """
            INSERT INTO g01_processed_webhook_events (event_id) VALUES (:id)
            ON CONFLICT DO NOTHING
            RETURNING event_id
            """,
            {"id": event_id},
        )
        return bool(rows)

    async def unmark_event(self, event_id: str) -> None:
        await self._write("DELETE FROM g01_processed_webhook_events WHERE event_id = :id", {"id": event_id})

    async def add_outbox(self, conversation_id: int | None, content: str, delivered: bool) -> dict:
        rows = await self._write(
            """
            INSERT INTO g01_outbox (conversation_id, content, delivered)
            VALUES (:conversation_id, :content, :delivered)
            RETURNING id, conversation_id, content, delivered, created_at
            """,
            {"conversation_id": conversation_id, "content": content, "delivered": delivered},
        )
        return rows[0]

    async def set_kyc(self, property_id: str, verified: bool, session_id: str | None = None) -> dict:
        rows = await self._write(
            f"""
            UPDATE g01_properties
            SET kyc_verified = :verified,
                stripe_identity_session_id = COALESCE(:session_id, stripe_identity_session_id)
            WHERE id = CAST(:id AS uuid)
            RETURNING {_PROPERTY}
            """,
            {"id": property_id, "verified": verified, "session_id": session_id},
        )
        if not rows:
            raise G01Error("property not found", 404)
        return rows[0]

    async def set_identity_session(self, property_id: str, session_id: str) -> dict:
        rows = await self._write(
            f"""
            UPDATE g01_properties
            SET stripe_identity_session_id = :session_id
            WHERE id = CAST(:id AS uuid)
            RETURNING {_PROPERTY}
            """,
            {"id": property_id, "session_id": session_id},
        )
        if not rows:
            raise G01Error("property not found", 404)
        return rows[0]

    async def property_by_identity_session(self, session_id: str) -> dict | None:
        return await self._one(
            f"SELECT {_PROPERTY} FROM g01_properties WHERE stripe_identity_session_id = :session_id",
            {"session_id": session_id},
        )

    async def attach_checkout(self, session_id: str, sponsor_id: str) -> None:
        await self._write(
            """
            INSERT INTO g01_sponsor_checkouts (stripe_session_id, sponsor_id)
            VALUES (:session_id, CAST(:sponsor_id AS uuid))
            ON CONFLICT (stripe_session_id) DO NOTHING
            """,
            {"session_id": session_id, "sponsor_id": sponsor_id},
        )

    async def sponsor_by_checkout(self, session_id: str) -> dict | None:
        return await self._one(
            """
            SELECT s.id, s.property_id, s.locality_id, s.company_name, s.founding_city, s.founding_state,
                   s.is_franchise_or_chain, s.sourcing_tier, s.service_tags, s.capabilities_summary,
                   s.lat, s.lng, s.referrals_last_14d, s.last_referred_at, s.homesteader_rating,
                   s.promo_boost_weight, s.stripe_customer_id, s.stripe_subscription_id,
                   s.applied_promo_code, s.is_active_sponsor, s.created_at
            FROM g01_sponsors s
            JOIN g01_sponsor_checkouts c ON c.sponsor_id = s.id
            WHERE c.stripe_session_id = :session_id
            """,
            {"session_id": session_id},
        )

    async def activate_sponsor(self, sponsor_id: str, customer_id: str | None, subscription_id: str | None, promo_boost: float | None) -> dict:
        rows = await self._write(
            f"""
            UPDATE g01_sponsors
            SET is_active_sponsor = TRUE,
                stripe_customer_id = :customer_id,
                stripe_subscription_id = :subscription_id,
                promo_boost_weight = COALESCE(:boost, promo_boost_weight)
            WHERE id = CAST(:id AS uuid)
            RETURNING {_SPONSOR}
            """,
            {
                "id": sponsor_id,
                "customer_id": customer_id,
                "subscription_id": subscription_id,
                "boost": promo_boost,
            },
        )
        if not rows:
            raise G01Error("sponsor not found", 404)
        return rows[0]

    async def open_polls_for_requester(self, property_id: str) -> list[dict]:
        return await self._all(
            """
            SELECT id, requester_property_id, locality_id, topic_slug, question_sent_to_neighbors,
                   status, mature_at, final_synthesis_report, created_at
            FROM g01_demand_polls
            WHERE requester_property_id = CAST(:id AS uuid) AND status = 'polling'
            """,
            {"id": property_id},
        )

    async def properties_with_goals(self) -> list[dict]:
        rows = await self._all(
            f"""
            SELECT {_PROPERTY}, goals_embedding::text AS goals_embedding
            FROM g01_properties
            WHERE jsonb_array_length(COALESCE(known_facts_ledger->'active_goals', '[]'::jsonb)) > 0
               OR goals_embedding IS NOT NULL
            """
        )
        for row in rows:
            raw = row.get("goals_embedding")
            if isinstance(raw, str) and raw.startswith("["):
                row["goals_embedding"] = [float(part) for part in raw.strip("[]").split(",") if part]
            elif raw is None:
                row["goals_embedding"] = None
        return rows
