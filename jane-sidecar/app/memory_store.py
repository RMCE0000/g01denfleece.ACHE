"""Process-local store used when Postgres is not configured. Same rules as the SQL path."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.errors import G01Error
from app.northstar import DEFAULT_LEDGER, automated_pct_from_hours, clamp_aesthetic, clamp_energetic
from app.seed import demo_localities, demo_promos, demo_properties, demo_sponsors
from app.sourcing import rank_sponsor_rows, sponsor_rejection_reason


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class MemoryStore:
    def __init__(self, now=None):
        self._now = now or _now_utc
        self.localities: list[dict] = []
        self.properties: list[dict] = []
        self.sponsors: list[dict] = []
        self.promos: list[dict] = []
        self.polls: list[dict] = []
        self.invites: list[dict] = []
        self.votes: list[dict] = []
        self.community_polls: list[dict] = []
        self.community_poll_recipients: list[dict] = []
        self.community_poll_answers: list[dict] = []
        self.economy_notes: list[dict] = []
        self.matches: list[dict] = []
        self.peers: list[dict] = []
        self.referrals: list[dict] = []
        self.events: set[str] = set()
        self.checkouts: dict[str, str] = {}
        self.checkout_details: dict[str, dict] = {}
        self.outbox: list[dict] = []
        self.transcript: list[dict] = []

    async def close(self) -> None:
        return None

    async def apply_schema(self) -> None:
        return None

    def _clock(self) -> datetime:
        current = self._now()
        if current.tzinfo is None:
            return current.replace(tzinfo=timezone.utc)
        return current

    async def list_localities(self) -> list[dict]:
        return deepcopy(self.localities)

    async def get_locality(self, locality_id: str) -> dict | None:
        for locality in self.localities:
            if locality["id"] == locality_id:
                return deepcopy(locality)
        return None

    async def locality_for_zip(self, zip_code: str) -> dict | None:
        for locality in self.localities:
            if zip_code in locality["allowed_zip_codes"]:
                return deepcopy(locality)
        return None

    async def create_property(self, fields: dict) -> dict:
        existing = await self.get_property_by_contact(fields["chatwoot_contact_id"])
        if existing:
            return existing
        hours = float(fields.get("outside_aid_hours_per_week", 40))
        prop = {
            "id": fields.get("id") or str(uuid4()),
            "chatwoot_account_id": int(fields["chatwoot_account_id"]),
            "chatwoot_user_id": fields.get("chatwoot_user_id"),
            "chatwoot_contact_id": int(fields["chatwoot_contact_id"]),
            "primary_conversation_id": fields.get("primary_conversation_id"),
            "chatwoot_inbox_id": fields.get("chatwoot_inbox_id"),
            "email": fields.get("email"),
            "display_name": fields.get("display_name"),
            "username": fields["username"],
            "locality_id": fields["locality_id"],
            "street_address": fields.get("street_address"),
            "zip_code": fields["zip_code"],
            "lat": float(fields["lat"]),
            "lng": float(fields["lng"]),
            "outside_aid_hours_per_week": hours,
            "northstar_automated_pct": automated_pct_from_hours(hours),
            "northstar_aesthetic_pct": float(fields.get("northstar_aesthetic_pct", 50)),
            "northstar_material_independent": bool(fields.get("northstar_material_independent", False)),
            "material_surplus_profitable": bool(fields.get("material_surplus_profitable", False)),
            "northstar_energetic_pct": float(fields.get("northstar_energetic_pct", 0)),
            "northstar_energetic_profitable": bool(fields.get("northstar_energetic_profitable", False)),
            "northstar_contained_zero_waste": bool(fields.get("northstar_contained_zero_waste", False)),
            "known_facts_ledger": deepcopy(fields.get("known_facts_ledger") or DEFAULT_LEDGER),
            "sponsor_draft": deepcopy(fields.get("sponsor_draft")),
            "kyc_verified": bool(fields.get("kyc_verified", False)),
            "stripe_identity_session_id": fields.get("stripe_identity_session_id"),
            "stripe_identity_session_url": fields.get("stripe_identity_session_url"),
            "updated_at": self._clock(),
            "goals_embedding": fields.get("goals_embedding"),
        }
        self.properties.append(prop)
        return deepcopy(prop)

    def _find_property(self, predicate) -> dict | None:
        for prop in self.properties:
            if predicate(prop):
                return deepcopy(prop)
        return None

    async def get_property(self, property_id: str) -> dict | None:
        return self._find_property(lambda row: row["id"] == property_id)

    async def get_property_by_contact(self, contact_id: int) -> dict | None:
        return self._find_property(lambda row: row["chatwoot_contact_id"] == int(contact_id))

    async def get_property_by_conversation(self, conversation_id: int) -> dict | None:
        return self._find_property(
            lambda row: row["primary_conversation_id"] is not None and int(row["primary_conversation_id"]) == int(conversation_id)
        )

    async def get_property_by_user(self, user_id: int) -> dict | None:
        return self._find_property(lambda row: row["chatwoot_user_id"] is not None and int(row["chatwoot_user_id"]) == int(user_id))

    async def get_property_by_email(self, email: str) -> dict | None:
        wanted = (email or "").strip().casefold()
        if not wanted:
            return None
        return self._find_property(lambda row: (row.get("email") or "").casefold() == wanted)

    async def get_property_by_username(self, username: str) -> dict | None:
        wanted = (username or "").strip().casefold().removeprefix("@")
        if not wanted:
            return None
        return self._find_property(lambda row: (row.get("username") or "").casefold() == wanted)

    def _mutate(self, property_id: str) -> dict:
        for prop in self.properties:
            if prop["id"] == property_id:
                prop["updated_at"] = self._clock()
                return prop
        raise G01Error("property not found", 404)

    async def update_aesthetic(self, property_id: str, aesthetic: float) -> dict:
        prop = self._mutate(property_id)
        prop["northstar_aesthetic_pct"] = clamp_aesthetic(aesthetic)
        return deepcopy(prop)

    async def update_labor_hours(self, property_id: str, hours: float) -> dict:
        if hours < 0:
            raise G01Error("hours cannot be negative", 422)
        prop = self._mutate(property_id)
        prop["outside_aid_hours_per_week"] = float(hours)
        prop["northstar_automated_pct"] = automated_pct_from_hours(float(hours))
        return deepcopy(prop)

    async def apply_profile_patch(self, property_id: str, fields: dict) -> dict:
        prop = self._mutate(property_id)
        if "northstar_material_independent" in fields:
            prop["northstar_material_independent"] = bool(fields["northstar_material_independent"])
        if "material_surplus_profitable" in fields:
            prop["material_surplus_profitable"] = bool(fields["material_surplus_profitable"])
        if "northstar_energetic_pct" in fields and fields["northstar_energetic_pct"] is not None:
            prop["northstar_energetic_pct"] = clamp_energetic(float(fields["northstar_energetic_pct"]))
        if "northstar_energetic_profitable" in fields:
            prop["northstar_energetic_profitable"] = bool(fields["northstar_energetic_profitable"])
        if "northstar_contained_zero_waste" in fields:
            prop["northstar_contained_zero_waste"] = bool(fields["northstar_contained_zero_waste"])
        if "street_address" in fields:
            prop["street_address"] = fields["street_address"]
        if "lat" in fields and fields["lat"] is not None:
            prop["lat"] = float(fields["lat"])
        if "lng" in fields and fields["lng"] is not None:
            prop["lng"] = float(fields["lng"])
        return deepcopy(prop)

    async def save_sponsor_draft(self, property_id: str, draft: dict | None) -> dict:
        prop = self._mutate(property_id)
        prop["sponsor_draft"] = deepcopy(draft) if draft is not None else None
        return deepcopy(prop)

    async def merge_ledger(self, property_id: str, ledger: dict) -> dict:
        prop = self._mutate(property_id)
        prop["known_facts_ledger"] = deepcopy(ledger)
        return deepcopy(prop)

    async def set_goals_embedding(self, property_id: str, vector: list[float] | None) -> None:
        prop = self._mutate(property_id)
        prop["goals_embedding"] = list(vector) if vector is not None else None

    async def list_local_properties(self, locality_id: str) -> list[dict]:
        return [deepcopy(row) for row in self.properties if row["locality_id"] == locality_id]

    async def create_promo(self, fields: dict) -> dict:
        code = fields["code"].strip().upper()
        if any(row["code"] == code for row in self.promos):
            raise G01Error("promo code already exists", 409)
        promo = {
            "code": code,
            "stripe_coupon_id": fields["stripe_coupon_id"],
            "discount_percent": int(fields["discount_percent"]),
            "recommendation_boost": float(fields.get("recommendation_boost", 1)),
            "restricted_locality_id": fields.get("restricted_locality_id"),
            "max_uses": int(fields.get("max_uses", 100)),
            "current_uses": 0,
            "active": True,
        }
        if not 1 <= promo["discount_percent"] <= 100:
            raise G01Error("discount percent must be between 1 and 100", 422)
        if not 0.5 <= promo["recommendation_boost"] <= 3:
            raise G01Error("recommendation boost must be between 0.50 and 3.00", 422)
        self.promos.append(promo)
        return deepcopy(promo)

    async def get_promo(self, code: str) -> dict | None:
        wanted = (code or "").strip().upper()
        for promo in self.promos:
            if promo["code"] == wanted:
                return deepcopy(promo)
        return None

    async def consume_promo(self, code: str) -> dict:
        wanted = code.strip().upper()
        for promo in self.promos:
            if promo["code"] != wanted:
                continue
            if not promo["active"] or promo["current_uses"] >= promo["max_uses"]:
                raise G01Error("promo code is not usable", 422)
            promo["current_uses"] += 1
            return deepcopy(promo)
        raise G01Error("promo code not found", 404)

    async def create_sponsor(self, fields: dict) -> dict:
        locality = await self.get_locality(fields["locality_id"])
        if not locality:
            raise G01Error("locality not found", 404)
        if fields.get("property_id"):
            prop = await self.get_property(fields["property_id"])
            if not prop:
                raise G01Error("linked homesteader not found", 404)
            if str(prop["locality_id"]) != str(fields["locality_id"]):
                raise G01Error("linked homesteader and sponsor must share a locality", 422)
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
        if fields["sourcing_tier"] not in ("local_manufacturer", "local_service_or_stock", "local_logistics_proxy"):
            raise G01Error("sourcing tier must be a sponsor tier, not homestead fabrication", 422)
        sponsor = {
            "id": str(uuid4()),
            "property_id": fields.get("property_id"),
            "locality_id": fields["locality_id"],
            "company_name": fields["company_name"].strip(),
            "founding_city": fields["founding_city"].strip(),
            "founding_state": fields["founding_state"].strip(),
            "is_franchise_or_chain": bool(fields.get("is_franchise_or_chain")),
            "sourcing_tier": fields["sourcing_tier"],
            "service_tags": list(fields["service_tags"]),
            "capabilities_summary": fields["capabilities_summary"].strip(),
            "lat": float(fields["lat"]),
            "lng": float(fields["lng"]),
            "referrals_last_14d": 0,
            "last_referred_at": None,
            "homesteader_rating": 5.0,
            "promo_boost_weight": 1.0,
            "stripe_customer_id": None,
            "stripe_subscription_id": None,
            "applied_promo_code": fields.get("applied_promo_code"),
            "promo_consumed_at": None,
            "is_active_sponsor": bool(fields.get("is_active_sponsor", False)),
            "created_at": self._clock(),
            "capabilities_embedding": None,
        }
        self.sponsors.append(sponsor)
        return deepcopy(sponsor)

    async def get_sponsor(self, sponsor_id: str) -> dict | None:
        for sponsor in self.sponsors:
            if sponsor["id"] == sponsor_id:
                return deepcopy(sponsor)
        return None

    async def list_sponsors(self, status: str | None = None, limit: int = 100) -> list[dict]:
        rows = self.sponsors
        if status == "active":
            rows = [row for row in rows if row.get("is_active_sponsor")]
        elif status == "inactive":
            rows = [row for row in rows if not row.get("is_active_sponsor")]
        return deepcopy(rows[: max(limit, 1)])

    async def update_sponsor(self, sponsor_id: str, patch: dict) -> dict:
        for index, sponsor in enumerate(self.sponsors):
            if sponsor["id"] != sponsor_id:
                continue
            merged = {**sponsor, **patch}
            locality = await self.get_locality(merged["locality_id"])
            if not locality:
                raise G01Error("locality not found", 404)
            if merged.get("property_id"):
                prop = await self.get_property(merged["property_id"])
                if not prop:
                    raise G01Error("linked homesteader not found", 404)
                if str(prop["locality_id"]) != str(merged["locality_id"]):
                    raise G01Error("linked homesteader and sponsor must share a locality", 422)
            reason = sponsor_rejection_reason(
                company_name=merged["company_name"],
                is_franchise_or_chain=bool(merged.get("is_franchise_or_chain")),
                locality_city=locality["primary_city"],
                locality_state=locality["state_code"],
                founding_city=merged["founding_city"],
                founding_state=merged["founding_state"],
                capabilities_summary=merged.get("capabilities_summary", ""),
            )
            if reason:
                raise G01Error(reason, 422)
            if merged["sourcing_tier"] not in (
                "local_manufacturer",
                "local_service_or_stock",
                "local_logistics_proxy",
            ):
                raise G01Error("invalid sponsor sourcing tier", 422)
            self.sponsors[index] = merged
            return deepcopy(merged)
        raise G01Error("sponsor not found", 404)

    async def rank_sponsors(self, property_id: str, service_tag: str, limit: int = 5) -> list[dict]:
        prop = await self.get_property(property_id)
        if not prop:
            raise G01Error("property not found", 404)
        locality = await self.get_locality(prop["locality_id"])
        return rank_sponsor_rows(
            property_row=prop,
            locality=locality or {},
            sponsors=self.sponsors,
            service_tag=service_tag,
            limit=limit,
        )

    async def record_referrals(self, property_id: str, sponsor_ids: list[str], service_tag: str, source_event_id: str) -> None:
        for sponsor_id in sponsor_ids:
            event_id = f"{source_event_id}:{sponsor_id}"
            if any(row["source_event_id"] == event_id for row in self.referrals):
                continue
            self.referrals.append(
                {
                    "id": str(uuid4()),
                    "sponsor_id": sponsor_id,
                    "property_id": property_id,
                    "service_tag": service_tag,
                    "source_event_id": event_id,
                    "created_at": self._clock(),
                }
            )
        await self.recount_referrals()

    async def recount_referrals(self) -> None:
        cutoff = self._clock() - timedelta(days=14)
        counts: dict[str, int] = {}
        latest: dict[str, datetime] = {}
        for event in self.referrals:
            if event["created_at"] < cutoff:
                continue
            counts[event["sponsor_id"]] = counts.get(event["sponsor_id"], 0) + 1
            current = latest.get(event["sponsor_id"])
            if current is None or event["created_at"] > current:
                latest[event["sponsor_id"]] = event["created_at"]
        for sponsor in self.sponsors:
            sponsor["referrals_last_14d"] = counts.get(sponsor["id"], 0)
            sponsor["last_referred_at"] = latest.get(sponsor["id"])

    async def create_poll(self, fields: dict) -> dict:
        poll = {
            "id": str(uuid4()),
            "requester_property_id": fields["requester_property_id"],
            "locality_id": fields["locality_id"],
            "topic_slug": fields["topic_slug"],
            "question_sent_to_neighbors": fields["question_sent_to_neighbors"],
            "status": "polling",
            "mature_at": fields["mature_at"],
            "final_synthesis_report": None,
            "created_at": self._clock(),
        }
        self.polls.append(poll)
        return deepcopy(poll)

    async def add_invites(self, poll_id: str, neighbors: list[dict]) -> None:
        for neighbor in neighbors:
            if any(row["poll_id"] == poll_id and row["neighbor_property_id"] == neighbor["id"] for row in self.invites):
                continue
            self.invites.append(
                {
                    "id": str(uuid4()),
                    "poll_id": poll_id,
                    "neighbor_property_id": neighbor["id"],
                    "conversation_id": neighbor.get("primary_conversation_id"),
                    "created_at": self._clock(),
                }
            )

    async def open_invites_for_property(self, property_id: str) -> list[dict]:
        open_polls = {poll["id"]: poll for poll in self.polls if poll["status"] == "polling"}
        found = []
        for invite in self.invites:
            if invite["neighbor_property_id"] != property_id or invite["poll_id"] not in open_polls:
                continue
            if any(vote["poll_id"] == invite["poll_id"] and vote["neighbor_property_id"] == property_id for vote in self.votes):
                continue
            row = deepcopy(invite)
            row["question_sent_to_neighbors"] = open_polls[invite["poll_id"]]["question_sent_to_neighbors"]
            row["topic_slug"] = open_polls[invite["poll_id"]]["topic_slug"]
            found.append(row)
        return found

    async def add_vote(self, poll_id: str, neighbor_property_id: str, raw_reply: str, weekly_units: float, price: float) -> dict:
        for vote in self.votes:
            if vote["poll_id"] == poll_id and vote["neighbor_property_id"] == neighbor_property_id:
                return deepcopy(vote)
        vote = {
            "id": str(uuid4()),
            "poll_id": poll_id,
            "neighbor_property_id": neighbor_property_id,
            "raw_reply": raw_reply,
            "weekly_units_demanded": float(weekly_units),
            "willing_price_per_unit_usd": float(price),
            "created_at": self._clock(),
        }
        self.votes.append(vote)
        return deepcopy(vote)

    async def get_poll(self, poll_id: str) -> dict | None:
        for poll in self.polls:
            if poll["id"] == poll_id:
                return deepcopy(poll)
        return None

    async def votes_for_poll(self, poll_id: str) -> list[dict]:
        return [deepcopy(vote) for vote in self.votes if vote["poll_id"] == poll_id]

    async def open_polls_for_requester(self, property_id: str) -> list[dict]:
        return [
            deepcopy(poll)
            for poll in self.polls
            if poll["requester_property_id"] == property_id and poll["status"] == "polling"
        ]

    async def mature_polls(self) -> list[dict]:
        current = self._clock()
        return [deepcopy(poll) for poll in self.polls if poll["status"] == "polling" and poll["mature_at"] <= current]

    async def complete_poll(self, poll_id: str, report: str) -> dict | None:
        for poll in self.polls:
            if poll["id"] == poll_id and poll["status"] == "polling":
                poll["status"] = "completed"
                poll["final_synthesis_report"] = report
                return deepcopy(poll)
        return None

    async def create_community_poll(self, fields: dict) -> tuple[dict, bool]:
        for poll in self.community_polls:
            if poll["poll_key"] == fields["poll_key"]:
                return deepcopy(poll), False
        poll = {
            "id": str(uuid4()),
            "poll_key": fields["poll_key"],
            "poll_kind": fields["poll_kind"],
            "requester_property_id": fields.get("requester_property_id"),
            "question": fields["question"],
            "status": "open",
            "opens_at": fields["opens_at"],
            "closes_at": fields["closes_at"],
            "compiled_report": None,
            "compiled_analysis": None,
            "created_at": self._clock(),
        }
        self.community_polls.append(poll)
        return deepcopy(poll), True

    async def add_community_poll_recipients(self, poll_id: str, properties: list[dict]) -> list[dict]:
        added = []
        for prop in properties:
            if any(
                row["poll_id"] == poll_id and row["property_id"] == prop["id"]
                for row in self.community_poll_recipients
            ):
                continue
            row = {
                "id": str(uuid4()),
                "poll_id": poll_id,
                "property_id": prop["id"],
                "conversation_id": prop.get("primary_conversation_id"),
                "created_at": self._clock(),
            }
            self.community_poll_recipients.append(row)
            added.append(deepcopy(row))
        return added

    async def community_poll_recipients_for(self, poll_id: str) -> list[dict]:
        return [
            deepcopy(row)
            for row in self.community_poll_recipients
            if row["poll_id"] == poll_id
        ]

    async def pending_community_polls(self, property_id: str) -> list[dict]:
        answered = {
            row["poll_id"]
            for row in self.community_poll_answers
            if row["property_id"] == property_id
        }
        polls = {row["id"]: row for row in self.community_polls if row["status"] == "open"}
        found = []
        for recipient in self.community_poll_recipients:
            if recipient["property_id"] != property_id or recipient["poll_id"] in answered:
                continue
            poll = polls.get(recipient["poll_id"])
            if poll:
                found.append({**deepcopy(poll), "recipient_id": recipient["id"]})
        return sorted(found, key=lambda row: (row["opens_at"], row["id"]))

    async def answer_community_poll(self, poll_id: str, property_id: str, answer: str) -> dict | None:
        for row in self.community_poll_answers:
            if row["poll_id"] == poll_id and row["property_id"] == property_id:
                return deepcopy(row)
        poll = next(
            (row for row in self.community_polls if row["id"] == poll_id and row["status"] == "open"),
            None,
        )
        recipient = any(
            row["poll_id"] == poll_id and row["property_id"] == property_id
            for row in self.community_poll_recipients
        )
        if poll is None or not recipient:
            return None
        row = {
            "id": str(uuid4()),
            "poll_id": poll_id,
            "property_id": property_id,
            "answer": answer,
            "created_at": self._clock(),
        }
        self.community_poll_answers.append(row)
        return deepcopy(row)

    async def community_poll_answers_for(self, poll_id: str) -> list[dict]:
        properties = {row["id"]: row for row in self.properties}
        found = []
        for answer in self.community_poll_answers:
            if answer["poll_id"] != poll_id:
                continue
            prop = properties.get(answer["property_id"], {})
            found.append(
                {
                    **deepcopy(answer),
                    "username": prop.get("username"),
                    "display_name": prop.get("display_name"),
                }
            )
        return found

    async def get_community_poll(self, poll_id: str) -> dict | None:
        for poll in self.community_polls:
            if poll["id"] == poll_id:
                return deepcopy(poll)
        return None

    async def list_community_polls(self, limit: int = 50) -> list[dict]:
        rows = sorted(self.community_polls, key=lambda row: (row["created_at"], row["id"]), reverse=True)
        return [deepcopy(row) for row in rows[:limit]]

    async def due_community_polls(self) -> list[dict]:
        now = self._clock()
        return [
            deepcopy(row)
            for row in self.community_polls
            if row["status"] == "open" and row["closes_at"] <= now
        ]

    async def get_community_poll_by_key(self, poll_key: str) -> dict | None:
        for poll in self.community_polls:
            if poll["poll_key"] == poll_key:
                return deepcopy(poll)
        return None

    async def homesteader_transcripts(self, conversation_ids: list[int]) -> list[dict]:
        wanted = {int(conversation_id) for conversation_id in conversation_ids}
        if not wanted:
            return []
        return [
            deepcopy(row)
            for row in self.transcript
            if int(row["conversation_id"]) in wanted and row.get("role") == "homesteader"
        ]

    async def save_economy_note(self, fields: dict) -> dict:
        for note in self.economy_notes:
            if note["property_id"] == fields["property_id"] and note["poll_id"] == fields["poll_id"]:
                if fields.get("answer"):
                    note["answer"] = fields["answer"]
                return deepcopy(note)
        note = {
            "id": str(uuid4()),
            "property_id": fields["property_id"],
            "zip_code": str(fields.get("zip_code") or ""),
            "poll_id": fields["poll_id"],
            "source": fields["source"],
            "question": fields["question"],
            "answer": fields.get("answer"),
            "created_at": self._clock(),
        }
        self.economy_notes.append(note)
        return deepcopy(note)

    async def economy_notes_for_property(self, property_id: str) -> list[dict]:
        return [deepcopy(row) for row in self.economy_notes if row["property_id"] == property_id]

    async def list_economy_notes(self) -> list[dict]:
        return [deepcopy(row) for row in self.economy_notes]

    async def close_community_poll(self, poll_id: str, report: str, analysis: dict) -> dict | None:
        for poll in self.community_polls:
            if poll["id"] == poll_id and poll["status"] == "open":
                poll["status"] = "closed"
                poll["compiled_report"] = report
                poll["compiled_analysis"] = deepcopy(analysis)
                return deepcopy(poll)
        return None

    async def create_match(self, fields: dict) -> dict | None:
        peer_a, peer_b = sorted([fields["peer_a_property_id"], fields["peer_b_property_id"]])
        title = fields["proposed_project_title"]
        for match in self.matches:
            if match["peer_a_property_id"] == peer_a and match["peer_b_property_id"] == peer_b and match["proposed_project_title"] == title:
                return None
        match = {
            "id": str(uuid4()),
            "locality_id": fields["locality_id"],
            "peer_a_property_id": peer_a,
            "peer_b_property_id": peer_b,
            "proposed_project_title": title,
            "jane_synergy_rationale": fields["jane_synergy_rationale"],
            "operator_status": "pending",
            "operator_review_note": None,
            "operator_reviewed_at": None,
            "peer_a_status": "pitched",
            "peer_b_status": "pitched",
            "shared_chatwoot_conversation_id": None,
            "shared_conversation_opening": False,
            "shared_conversation_claimed_at": None,
            "created_at": self._clock(),
        }
        self.matches.append(match)
        return deepcopy(match)

    async def get_match(self, match_id: str) -> dict | None:
        for match in self.matches:
            if match["id"] == match_id:
                return deepcopy(match)
        return None

    async def list_matches(self, operator_status: str | None = None, limit: int = 100) -> list[dict]:
        rows = self.matches
        if operator_status:
            rows = [row for row in rows if row["operator_status"] == operator_status]
        ordered = sorted(rows, key=lambda row: (row["created_at"], row["id"]), reverse=True)
        return [deepcopy(row) for row in ordered[:limit]]

    async def set_match_operator_status(self, match_id: str, status: str, note: str | None = None) -> dict:
        if status not in ("approved", "rejected"):
            raise G01Error("operator match status must be approved or rejected", 422)
        for match in self.matches:
            if match["id"] != match_id:
                continue
            if match["operator_status"] != "pending":
                raise G01Error(f"match is already {match['operator_status']}", 409)
            match["operator_status"] = status
            match["operator_review_note"] = note
            match["operator_reviewed_at"] = self._clock()
            return deepcopy(match)
        raise G01Error("match not found", 404)

    async def matches_for_property(self, property_id: str) -> list[dict]:
        return [
            deepcopy(match)
            for match in self.matches
            if property_id in (match["peer_a_property_id"], match["peer_b_property_id"])
            and match["operator_status"] == "approved"
            and match["shared_chatwoot_conversation_id"] is None
            and "declined" not in (match["peer_a_status"], match["peer_b_status"])
        ]

    async def set_match_status(self, match_id: str, peer_property_id: str, status: str) -> dict:
        if status not in ("pitched", "accepted", "declined"):
            raise G01Error("invalid match status", 422)
        for match in self.matches:
            if match["id"] != match_id:
                continue
            if match["operator_status"] != "approved":
                raise G01Error("match requires operator approval", 409)
            if match["peer_a_property_id"] == peer_property_id:
                match["peer_a_status"] = status
            elif match["peer_b_property_id"] == peer_property_id:
                match["peer_b_status"] = status
            else:
                raise G01Error("property is not on this match", 404)
            return deepcopy(match)
        raise G01Error("match not found", 404)

    async def set_shared_conversation(self, match_id: str, conversation_id: int) -> dict:
        for match in self.matches:
            if match["id"] == match_id:
                match["shared_chatwoot_conversation_id"] = int(conversation_id)
                match["shared_conversation_opening"] = False
                match["shared_conversation_claimed_at"] = None
                return deepcopy(match)
        raise G01Error("match not found", 404)

    async def claim_shared_conversation(self, match_id: str) -> bool:
        for match in self.matches:
            if match["id"] != match_id or match.get("shared_chatwoot_conversation_id") is not None:
                continue
            claimed_at = match.get("shared_conversation_claimed_at")
            stale = claimed_at is not None and claimed_at <= self._clock() - timedelta(minutes=5)
            if match.get("shared_conversation_opening") and not stale:
                return False
            match["shared_conversation_opening"] = True
            match["shared_conversation_claimed_at"] = self._clock()
            return True
        return False

    async def release_shared_conversation_claim(self, match_id: str) -> None:
        for match in self.matches:
            if match["id"] == match_id and match.get("shared_chatwoot_conversation_id") is None:
                match["shared_conversation_opening"] = False
                match["shared_conversation_claimed_at"] = None

    async def ready_matches_without_thread(self) -> list[dict]:
        ready = []
        for match in self.matches:
            if match["shared_chatwoot_conversation_id"] is not None:
                continue
            if match["operator_status"] != "approved":
                continue
            if match["peer_a_status"] != "accepted" or match["peer_b_status"] != "accepted":
                continue
            peer_a = await self.get_property(match["peer_a_property_id"])
            peer_b = await self.get_property(match["peer_b_property_id"])
            if peer_a and peer_b and peer_a["kyc_verified"] and peer_b["kyc_verified"]:
                ready.append(deepcopy(match))
        return ready

    async def mark_event(self, event_id: str) -> bool:
        if event_id in self.events:
            return False
        self.events.add(event_id)
        return True

    async def unmark_event(self, event_id: str) -> None:
        self.events.discard(event_id)

    async def list_properties(self) -> list[dict]:
        return deepcopy(self.properties)

    async def list_peer_conversations(self) -> list[dict]:
        return deepcopy(self.peers)

    async def append_transcript(
        self,
        *,
        conversation_id: int | None,
        message_id: str | None,
        role: str,
        speaker: str,
        content: str,
    ) -> dict | None:
        text = str(content or "").strip()
        if conversation_id is None or not text:
            return None
        if message_id:
            for row in self.transcript:
                if int(row["conversation_id"]) == int(conversation_id) and row.get("message_id") == str(message_id):
                    return deepcopy(row)
        row = {
            "id": str(uuid4()),
            "conversation_id": int(conversation_id),
            "message_id": str(message_id) if message_id else None,
            "role": role,
            "speaker": speaker or ("Jane" if role == "jane" else "Homesteader"),
            "content": text,
            "created_at": self._clock(),
        }
        self.transcript.append(row)
        return deepcopy(row)

    async def list_transcript(self, conversation_id: int) -> list[dict]:
        rows = [row for row in self.transcript if int(row["conversation_id"]) == int(conversation_id)]
        return deepcopy(rows)

    async def transcript_conversation_ids(self) -> list[int]:
        return sorted({int(row["conversation_id"]) for row in self.transcript})

    async def add_outbox(self, conversation_id: int | None, content: str, delivered: bool) -> dict:
        row = {
            "id": str(uuid4()),
            "conversation_id": conversation_id,
            "content": content,
            "delivered": delivered,
            "created_at": self._clock(),
        }
        self.outbox.append(row)
        return deepcopy(row)

    async def set_kyc(self, property_id: str, verified: bool, session_id: str | None = None) -> dict:
        prop = self._mutate(property_id)
        prop["kyc_verified"] = bool(verified)
        if session_id is not None:
            prop["stripe_identity_session_id"] = session_id
        return deepcopy(prop)

    async def set_identity_session(self, property_id: str, session_id: str, session_url: str | None = None) -> dict:
        prop = self._mutate(property_id)
        prop["stripe_identity_session_id"] = session_id
        prop["stripe_identity_session_url"] = session_url
        return deepcopy(prop)

    async def property_by_identity_session(self, session_id: str) -> dict | None:
        return self._find_property(lambda row: row.get("stripe_identity_session_id") == session_id)

    async def attach_checkout(
        self,
        session_id: str,
        sponsor_id: str,
        url: str | None = None,
        billing_email: str | None = None,
    ) -> None:
        self.checkouts[session_id] = sponsor_id
        details = dict(self.checkout_details.get(session_id) or {})
        if url:
            details["url"] = url
        if billing_email:
            details["billing_email"] = billing_email
        self.checkout_details[session_id] = details

    async def latest_open_checkout(self, property_id: str) -> dict | None:
        for session_id, sponsor_id in reversed(list(self.checkouts.items())):
            sponsor = await self.get_sponsor(sponsor_id)
            if not sponsor or str(sponsor.get("property_id")) != str(property_id):
                continue
            if sponsor.get("is_active_sponsor"):
                continue
            details = self.checkout_details.get(session_id) or {}
            return {
                "session_id": session_id,
                "sponsor_id": sponsor_id,
                "company_name": sponsor["company_name"],
                "url": details.get("url"),
                "billing_email": details.get("billing_email"),
            }
        return None

    async def sponsor_by_checkout(self, session_id: str) -> dict | None:
        sponsor_id = self.checkouts.get(session_id)
        if not sponsor_id:
            return None
        return await self.get_sponsor(sponsor_id)

    async def activate_sponsor(self, sponsor_id: str, customer_id: str | None, subscription_id: str | None, promo_boost: float | None) -> dict:
        for sponsor in self.sponsors:
            if sponsor["id"] != sponsor_id:
                continue
            sponsor["is_active_sponsor"] = True
            sponsor["stripe_customer_id"] = customer_id
            sponsor["stripe_subscription_id"] = subscription_id
            if promo_boost is not None:
                sponsor["promo_boost_weight"] = float(promo_boost)
            return deepcopy(sponsor)
        raise G01Error("sponsor not found", 404)

    async def activate_sponsor_checkout(self, sponsor_id: str, customer_id: str | None, subscription_id: str | None) -> dict:
        for sponsor in self.sponsors:
            if sponsor["id"] != sponsor_id:
                continue
            if sponsor.get("applied_promo_code") and sponsor.get("promo_consumed_at") is None:
                try:
                    promo = await self.consume_promo(sponsor["applied_promo_code"])
                except G01Error:
                    promo = None
                sponsor["promo_consumed_at"] = self._clock()
                if promo is not None:
                    sponsor["promo_boost_weight"] = float(promo["recommendation_boost"])
            sponsor["is_active_sponsor"] = True
            sponsor["stripe_customer_id"] = customer_id
            sponsor["stripe_subscription_id"] = subscription_id
            return deepcopy(sponsor)
        raise G01Error("sponsor not found", 404)

    async def remember_sponsor_billing(self, sponsor_id: str, customer_id: str | None, subscription_id: str | None) -> dict:
        for sponsor in self.sponsors:
            if sponsor["id"] != sponsor_id:
                continue
            if customer_id:
                sponsor["stripe_customer_id"] = customer_id
            if subscription_id:
                sponsor["stripe_subscription_id"] = subscription_id
            return deepcopy(sponsor)
        raise G01Error("sponsor not found", 404)

    async def latest_inactive_sponsor(self, property_id: str) -> dict | None:
        found = None
        for sponsor in self.sponsors:
            if str(sponsor.get("property_id")) == str(property_id) and not sponsor.get("is_active_sponsor"):
                found = sponsor
        return deepcopy(found) if found else None

    async def inactive_sponsor_named(self, property_id: str, company_name: str) -> dict | None:
        from app.sponsor_chat import sponsor_name_key

        wanted = sponsor_name_key(company_name)
        if not wanted:
            return None
        found = None
        for sponsor in self.sponsors:
            if str(sponsor.get("property_id")) != str(property_id) or sponsor.get("is_active_sponsor"):
                continue
            if sponsor_name_key(sponsor.get("company_name") or "") == wanted:
                found = sponsor
        return deepcopy(found) if found else None

    async def latest_sponsor(self, property_id: str) -> dict | None:
        found = None
        for sponsor in self.sponsors:
            if str(sponsor.get("property_id")) == str(property_id):
                found = sponsor
        return deepcopy(found) if found else None

    async def sponsor_by_subscription(self, subscription_id: str) -> dict | None:
        for sponsor in self.sponsors:
            if sponsor.get("stripe_subscription_id") == subscription_id:
                return deepcopy(sponsor)
        return None

    async def set_sponsor_subscription_active(self, subscription_id: str, active: bool) -> dict | None:
        for sponsor in self.sponsors:
            if sponsor.get("stripe_subscription_id") == subscription_id:
                sponsor["is_active_sponsor"] = bool(active)
                return deepcopy(sponsor)
        return None

    async def properties_with_goals(self) -> list[dict]:
        answers: dict[str, list[str]] = {}
        for answer in self.community_poll_answers:
            answers.setdefault(answer["property_id"], []).append(answer["answer"])
        rows = []
        for prop in self.properties:
            goals = list((prop.get("known_facts_ledger") or {}).get("active_goals") or [])
            signals = [*goals, *answers.get(prop["id"], [])]
            if not signals and not prop.get("goals_embedding"):
                continue
            row = deepcopy(prop)
            ledger = deepcopy(row.get("known_facts_ledger") or {})
            ledger["active_goals"] = signals
            row["known_facts_ledger"] = ledger
            rows.append(row)
        return rows

    def _ordered_pair(self, left: str, right: str) -> tuple[str, str]:
        first, second = str(left), str(right)
        if first == second:
            raise G01Error("choose two different homesteaders", 422)
        return (first, second) if first < second else (second, first)

    async def find_peer_between(self, left_id: str, right_id: str) -> dict | None:
        first, second = self._ordered_pair(left_id, right_id)
        for row in self.peers:
            if row["property_a_id"] == first and row["property_b_id"] == second:
                return deepcopy(row)
        return None

    async def get_peer_by_conversation(self, conversation_id: int) -> dict | None:
        for row in self.peers:
            if int(row["chatwoot_conversation_id"]) == int(conversation_id):
                return deepcopy(row)
        return None

    async def is_peer_conversation(self, conversation_id: int) -> bool:
        return await self.get_peer_by_conversation(conversation_id) is not None

    async def remember_peer_conversation(
        self,
        conversation_id: int,
        left_id: str,
        right_id: str,
        inbox_id: int | None = None,
        topic: str | None = None,
    ) -> dict:
        first, second = self._ordered_pair(left_id, right_id)
        existing = await self.find_peer_between(first, second)
        if existing:
            return existing
        by_conversation = await self.get_peer_by_conversation(conversation_id)
        if by_conversation:
            return by_conversation
        row = {
            "id": str(uuid4()),
            "chatwoot_conversation_id": int(conversation_id),
            "chatwoot_inbox_id": int(inbox_id) if inbox_id is not None else None,
            "property_a_id": first,
            "property_b_id": second,
            "topic": topic,
            "created_at": self._clock(),
        }
        self.peers.append(row)
        return deepcopy(row)


def seed_demo(store: MemoryStore) -> MemoryStore:
    store.localities = demo_localities()
    store.properties = demo_properties()
    store.sponsors = demo_sponsors()
    store.promos = demo_promos()
    return store
