# g01denfleece ACHE

Jane is a peer inside an ordinary Chatwoot thread. The thread stays open. The work of a homestead is the five-part North Star, and the only shops Jane will name are in the homesteader's own locality.

| Dimension | Stored as | Meaning |
| --- | --- | --- |
| Automated | float 0.0–100.0 | Reduction from a 40-hour full-manual week. 0 hours on the record is 100. |
| Aesthetic | float 0.0–100.0 | The homesteader's own rating. Nothing else writes it. |
| Material | boolean | The household can live indefinitely off the property. |
| Energetic | float (0–500) and `energetic_profitable` boolean | Power produced, plus whether surplus is sold at a profit. |
| Contained | boolean | No harmful waste leaves the property. |

Sourcing is a fixed prize order:

1. Homestead fabrication, weight **1.00**
2. Local manufacturer, weight **0.85**
3. Local sponsor or stock, weight **0.70**
4. Local logistics sponsor, weight **0.50**

Jane does not link to Amazon, Home Depot, Lowe's, or any other checkout. Walmart can appear only as a Rogers, Arkansas origin sponsor, and only when that row is in the registry. Sponsor order is deterministic:

`tier_weight * (0.45 + 0.25 * distance_score + 0.20 * rotation_score + 0.10 * rating_score) * promo_boost_weight`

Ties break toward fewer referrals in the last 14 days, then sponsor id.

## Layout

- `chatwoot-fork/` — notes and optional proxy controllers. Compose runs upstream Chatwoot, not a rewritten Rails app.
- `jane-sidecar/` — FastAPI, LangGraph, and Stripe. It has no homesteader page.
- `sql/001_init_g01_schema.sql` — g01 tables, pgvector, and the ranking functions. Apply after Chatwoot prepares the database. The sidecar also applies this file on boot.

Live chat turns use `gemini-2.5-flash`. Poll synthesis and matchmaking use `gemini-2.5-pro`. Embeddings use `text-embedding-004` (768 dimensions) with `AsyncPostgresSaver` when `G01_DATABASE_URL` is set. Without a Gemini key, Jane still posts from the ledger and the registry; she does not invent scores.

## Run

```bash
cp .env.example .env
docker compose up --build
```

The homesteader page is Chatwoot's own widget. After bootstrap finishes, `.chatwoot-bootstrap/operator.txt` has the widget URL (`http://localhost:3000/widget?website_token=...`) and Jane's agent login. The pre-chat form asks for a name and email. Jane attaches the property when the person sends a ZIP. Scores, labor hours, aesthetic, local ranking, sponsorship, and identity verification are replies in that thread. Stripe Checkout and Stripe Identity stay on Stripe; Jane may paste those links.

The sidecar on port 8000 accepts the Chatwoot webhook, the Stripe webhook, and the admin promo route. It does not serve a dashboard or a signup form. Auto-resolve is left unset so the thread stays open. Agent account signup is off; the bootstrap user is the operator.

For a memory-backed webhook demo without Docker:

```bash
python -m venv .venv
.venv/bin/pip install -r jane-sidecar/requirements-dev.txt
cd jane-sidecar && ../.venv/bin/uvicorn app.main:app --port 8000
```

The seeded Lake Charles thread is conversation 501, contact 101. Rogers is conversation 502. Ask in the webhook payload the way a Chatwoot `message_created` event would: "What are my scores?", "Where can I get a grow light?", or the sponsor answers.

Turn off the Chatwoot inbox auto-resolve timer. Jane's user id defaults to 1. Point a `message_created` webhook at `http://jane:8000/webhooks/chatwoot`. Do not add a Dashboard App.

Tests:

```bash
cd jane-sidecar && python -m pytest
```
