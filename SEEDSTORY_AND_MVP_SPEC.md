# g01denfleece ACHE — seed story and MVP spec

Document ID: `seedstory`

## Premise

g01 is a chat with Jane toward energetic and material independence. A homesteader signs up and lands in one Chatwoot conversation that stays open. Jane is a peer in that thread (a user or an agent bot), not a separate chat product. Neighbors get a second Chatwoot conversation only after both accept a pitch and both pass Stripe Identity.

Jane knows the property record and what the homesteader says. She does not assume acreage, climate, tools, or a budget.

## North Star

These five stay five. Do not collapse them and do not change the types.

1. `automated` — float, 0.0 to 100.0. Objective. Computed from weekly hours of the homesteader's labor plus outside aid, against a 40-hour full-manual week: `clamp(0, 100, (1 - hours / 40) * 100)`.
2. `aesthetic` — float, 0.0 to 100.0. Subjective. Only the homesteader's stated rating.
3. `material` — boolean. True only when the household can live indefinitely off the property. `material_surplus_profitable` is a fact on this dimension, not a sixth score.
4. `energetic` — float plus `energetic_profitable` boolean. The float may exceed 100 when the property produces surplus. The column cap is 500. The boolean is true only when surplus energy is sold at a net profit.
5. `contained` — boolean. True only when the property leaks no harmful waste.

## Sourcing

Prize order, highest first:

| Tier | Who | Weight |
| --- | --- | --- |
| 1 | The homestead fabricates it | 1.00 |
| 2 | `local_manufacturer` | 0.85 |
| 3 | `local_service_or_stock` | 0.70 |
| 4 | `local_logistics_proxy` | 0.50 |

No Amazon, Home Depot, Lowe's, Walmart (except the Rogers, Arkansas origin exception), franchises, or e-commerce APIs. A logistics sponsor may buy from somewhere else. g01 still only talks to that local sponsor, and that path scores lowest.

When more than one sponsor can do the job:

`score = tier_weight * (0.45 + 0.25 * distance_score + 0.20 * rotation_score + 0.10 * rating_score) * promo_boost_weight`

`distance_score` falls from 1 at the homestead to 0 at `max_radius_miles`. `rotation_score` is `1 / (1 + referrals in the last 14 days)`. Rating is `homesteader_rating / 5`, clamped to 0–1. Sort by score descending, then fewer recent referrals, then sponsor id.

## What the MVP does

1. **Chat and education.** Jane reads the ledger, asks for gaps, and ranks the local registry when a part is needed. Tier 1 is always stated first. The ranked rows come from SQL (`g01_rank_local_sponsors`) or the same formula in the memory store. The model does not invent the order.
2. **Demand polls.** A market question becomes a poll that matures 24 hours later. Neighbors are asked without the requester's street address. The synthesis quotes only the votes that came back.
3. **Neighbor threads.** Background matching uses shared recorded goals, or 768-d cosine similarity at or above 0.72 when embeddings exist. Pitches go to each existing thread. The shared conversation id is written only after both statuses are `accepted` and both `kyc_verified` flags are true.
4. **Sponsors and promo codes.** A logged-in homesteader can submit the questionnaire. The row stays inactive until Stripe Checkout reports `paid` or `no_payment_required`. Admins create promo codes with `X-G01-Admin-Token`. A code can discount the Stripe subscription (1–100%) and carry a recommendation boost from 0.50 to 3.00. Uses increment when the sponsor actually activates.

## Services

Chatwoot (upstream image) keeps users, conversations, messages, and websockets. `jane-sidecar` is FastAPI plus LangGraph plus Celery. They share Postgres 16 with pgvector. Redis is the Celery broker.

- Sync graph (`sync_peer_graph.py`): `message_created` from anyone who is not Jane. Flash may draft the sentence. Hours, aesthetic, material, energetic, and contained change only when the homesteader's words support them.
- Demand graph (`demand_poll_graph.py`): Pro may rephrase the factual tally. A number that was not in the tally is dropped.
- Matchmaking graph (`matchmaking_graph.py`): Pro may rephrase a rationale made only of recorded goals. A shared thread is a Chatwoot conversation.
- Checkpointer: `AsyncPostgresSaver` on the same database when `G01_DATABASE_URL` is set.

The HUD at `/ui/hud` is the Chatwoot Dashboard App. It listens for `appContext`. Aesthetic is a slider. Automated moves only when hours are saved.

## Constitution

`jane-sidecar/app/constitution.py` holds Jane's prompt. The source brief ended mid-sentence at "3. DIY". Laws 3 through 10 finish that sentence from the rules above. They do not relax laws 1 and 2.

## Localities shipped in the schema

- Lake Charles & Calcasieu Suburbs, Louisiana. ZIPs 70601, 70605, 70607, 70611, 70615, 70663, 70669.
- Rogers Metro, Arkansas. ZIPs 72756, 72758. This is the Walmart origin exception.

The brief's poll column was written `question_Sent_to_neighbors`. The table uses `question_sent_to_neighbors`.
