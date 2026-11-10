# g01denfleece ACHE — seed story and MVP spec

Document ID: `seedstory`

## Premise

g01 is a chat with Jane toward energetic and material independence. A homesteader signs up and lands in one g01 conversation that stays open. Jane is a peer in that thread (a user or an agent bot), not a separate chat product. Neighbors get a second g01 conversation only after both accept a pitch and both pass Stripe Identity.

Jane knows the property record and what the homesteader says. She does not assume acreage, climate, tools, or a budget.

## North Star

Insured is the guiding principle. The six aims beneath it keep their own types. Do not collapse an aim into another, and do not let Jane invent a value.

1. `automated` — float, 0.0 to 100.0. Objective. The homesteader ought not need to work to maintain the property. The score is outside aid against a 40-hour week: `clamp(0, 100, (1 - hours / 40) * 100)`. No outside aid is 100.
2. `aesthetic` — float, 0.0 to 100.0. Subjective. The property ought be beautiful by the homesteader's taste. Only their stated rating.
3. `material` — boolean. True only when they can live off the fruits of the property, alone, indefinitely. `material_surplus_profitable` remains a fact on this aim.
4. `energetic` — float plus `energetic_profitable` boolean. The property ought produce its own energy and sell surplus at a profit. The float may exceed 100. The column cap is 500.
5. `contained` — boolean. True only when the property leaks no harmful waste.
6. `utilized` — float, 0.0 to 100.0. The property ought be recorded on the financial tools that serve its homesteaders. 0 means it is not recorded. 100 means that recording serves them as fully as the tools allow.
7. `insured` — boolean. The principle above the six. True only when the property and all homesteaders are perfectly insured. A wish for coverage does not set it.

## Jane's insurance

Jane lives in insurance. A homestead is a guarantee that one's domain is not at the whim of quarrels beyond the home. She may say that, briefly, when the conversation is about insurance, risk, or sovereignty.

What she can offer is a catalog the operator files, in the same way a sponsor is filed:

- `product-add` files a product as `draft` or `offered`. Only `offered` reaches Jane. A draft is not an offer, and an offer is not a bound policy or a charge.
- `knowledge-add` files a titled body under comma-separated topics. Jane receives that body only when the homesteader's message touches a topic. That is how her expertise grows: the operator files what she may treat as fact. She does not write the repository herself, and she does not state a premium, a limit, or a condition that is not in the entries selected for the turn.

A local insurance producer can still be a g01 sponsor. Jane's product is not that company, and that company is not Jane's product.

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
4. **Sponsors and promo codes.** A homesteader files a sponsor by answering Jane in the thread. The row stays inactive until Stripe Checkout reports `paid` or `no_payment_required`. Admins create promo codes with `X-G01-Admin-Token`. A code can discount the Stripe subscription (1–100%) and carry a recommendation boost from 0.50 to 3.00. Uses increment when the sponsor actually activates.

## Services

g01 (upstream image) keeps users, conversations, messages, and websockets. `jane-sidecar` is FastAPI plus LangGraph plus Celery. They share Postgres 16 with pgvector. Redis is the Celery broker.

- Sync graph (`sync_peer_graph.py`): `message_created` from anyone who is not Jane. Flash may draft the sentence. Hours, aesthetic, material, energetic, contained, utilized, and insured change only when the homesteader's words support them.
- Demand graph (`demand_poll_graph.py`): Pro may rephrase the factual tally. A number that was not in the tally is dropped.
- Matchmaking graph (`matchmaking_graph.py`): Pro may rephrase a rationale made only of recorded goals. A shared thread is a g01 conversation.
- Checkpointer: `AsyncPostgresSaver` on the same database when `G01_DATABASE_URL` is set.

The only UI a homesteader can open is the g01 conversation. North Star readout, aesthetic, labor hours, local ranking, the sponsor answers, and the KYC request are retrieved by asking Jane. The login-page account form is how someone signs up. A property attaches when they tell Jane a ZIP. Stripe's hosted Checkout and Identity pages may be linked from Jane's message. The sidecar does not publish `/ui/hud`, a signup page, or a Dashboard App.

## Constitution

`jane-sidecar/app/constitution.py` holds Jane's prompt. The source brief ended mid-sentence at "3. DIY". Laws 3 through 10 finish that sentence from the rules above. They do not relax laws 1 and 2.

## Localities shipped in the schema

- Lake Charles & Calcasieu Suburbs, Louisiana. ZIPs 70601, 70605, 70607, 70611, 70615, 70663, 70669.
- Rogers Metro, Arkansas. ZIPs 72756, 72758. This is the Walmart origin exception.

The brief's poll column was written `question_Sent_to_neighbors`. The table uses `question_sent_to_neighbors`.
