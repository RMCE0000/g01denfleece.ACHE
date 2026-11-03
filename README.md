# g01denfleece ACHE

Jane is a peer inside an ordinary Chatwoot thread. This is the minimum showcase: a small, free, local model. Each time she is prompted she receives her constitution (`jane-sidecar/CONSTITUTION.md`) and the message history, and nothing else. Background jobs are off.

The work she is written to care about is the five-part North Star, and the only shops she will name are in the homesteader's own locality.

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
- `jane-sidecar/` — FastAPI. The live turn calls Ollama. It has no homesteader page.
- `sql/001_init_g01_schema.sql` — g01 tables, pgvector, and the ranking functions. Apply after Chatwoot prepares the database. The sidecar also applies this file on boot.

Live turns call Ollama (`qwen2.5:1.5b` unless `G01_OLLAMA_MODEL` is set) at `G01_OLLAMA_BASE_URL`. The system text is the constitution. The user text is the thread, one line per message. If Ollama is down, Jane says she could not reach the local model. Celery beat and the worker are not started; `docker compose --profile background up` is what would start them.

## Run

```bash
cp .env.example .env
docker compose up --build
```

The homesteader signs in at Chatwoot: `http://localhost:3000/app/login`. The screen is white with gold accents and the g01 logo. **Forgot your password?** emails a reset link. Locally that mail is in Mailpit at `http://localhost:8025`. A public launch points `SMTP_ADDRESS` at a real mailbox. **Create an account** on the login page asks for a name, email, password, and a ZIP already on the record (such as 70601). That creates the sign-in and a private thread with Jane, then opens it. Chatwoot's own account signup stays off, because that form would open a separate empty account. After bootstrap, `.chatwoot-bootstrap/operator.txt` has Jane's agent login and the admin token. When Jane finishes starting, `.chatwoot-bootstrap/homesteaders.txt` has two local demo people:

- Ada Yard, `ada.yard@example.com`, password `G01seed-Ada-70601`
- Bea Chenier, `bea.chenier@example.com`, password `G01seed-Bea-70605`

Each has a private inbox named `Jane — {name}` for talking with Jane, and a shared inbox `Ada Yard and Bea Chenier`. Jane stays quiet in the shared inbox unless someone says her name. The public widget remains at the URL in `operator.txt`; its header is the same gold.

Create another sign-in, then a conversation between two of them:

```bash
curl -s -X POST http://localhost:8000/api/admin/homesteaders \
  -H "X-G01-Admin-Token: g01-local-admin-token" \
  -H "Content-Type: application/json" \
  -d '{"name":"Cara North","email":"cara.north@example.com","password":"Pasture-70607","zip_code":"70607"}'

curl -s -X POST http://localhost:8000/api/admin/conversations \
  -H "X-G01-Admin-Token: g01-local-admin-token" \
  -H "Content-Type: application/json" \
  -d '{"left":"ada.yard@example.com","right":"cara.north@example.com","topic":"the well"}'
```

`left` and `right` take an email, a Chatwoot user id, or a property id. Read every thread before opening one:

```bash
curl -s http://localhost:8000/api/admin/conversations \
  -H "X-G01-Admin-Token: g01-local-admin-token"
```

Each row is a Jane thread or a connection, with the people, the topic, and the messages. Jane stays quiet in a connection unless someone says her name.

The sidecar on port 8000 accepts the Chatwoot webhook, the login-page signup at `POST /api/signup`, and the admin routes. It does not serve a dashboard. Auto-resolve is left unset so the thread stays open. The bootstrap user is the operator. Chatwoot's own agent signup stays off.

For a memory-backed webhook demo without Docker:

```bash
python -m venv .venv
.venv/bin/pip install -r jane-sidecar/requirements-dev.txt
cd jane-sidecar && ../.venv/bin/uvicorn app.main:app --port 8000
```

The seeded Lake Charles thread is conversation 501, contact 101. Rogers is conversation 502. A `message_created` webhook is answered by the local model from the constitution and that thread's history.

Turn off the Chatwoot inbox auto-resolve timer. Jane's user id defaults to 1. Point a `message_created` webhook at `http://jane:8000/webhooks/chatwoot`. Do not add a Dashboard App.

Tests:

```bash
cd jane-sidecar && python -m pytest
```
