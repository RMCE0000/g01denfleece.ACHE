# g01 progress log

Updated 3 Nov 2026, 4:49 PM America/Chicago.

## Still open from the MVP

The four MVP behaviors are on `main`: chat scores, local ranking, 24-hour polls, and the neighbor gate. These parts are still short of a finished stack.

1. **The legacy 24-hour demand-poll job still fails when Postgres is on.** Celery compiles that graph with the Postgres checkpointer and then runs it without a `thread_id`. Jane's daily community polls and automatic match discovery do not use that broken path.

2. **Stripe and Gemini are unwired until their keys are set.** With the keys empty, Jane answers from the ledger and the phrase rules, goal embeddings are never computed, a filed sponsor stays inactive, and identity verification cannot complete. Promo codes stay closed until `G01_ADMIN_TOKEN` is set. An admin still creates the Stripe coupon; the sidecar only stores the coupon id.

3. **Two ranking inputs never move.** `homesteader_rating` stays at 5.00, and `capabilities_embedding` is never written.

4. **The original brief also named plan and blueprint reading, and a way to forget a recorded fact.** Neither is in the sidecar. The constitution's later laws were inferred because the source brief stopped at "3. DIY".

## This slice

The minimum showcase (MS). Jane is a small local model. A prompt is her constitution and the message history.

- `jane-sidecar/CONSTITUTION.md` is what she is given. It is not the old JSON ledger prompt.
- Ollama serves `qwen2.5:1.5b` (override with `G01_OLLAMA_MODEL`). Compose pulls it once. If it is down, she says she could not reach the local model.
- `GET /api/admin/conversations` lists every Jane thread and every connection, with the people and the messages, so a connection can be opened with `POST /api/admin/conversations`.
- `docker compose exec jane python -m app.operator` opens the private operator command center. It can inspect all homesteaders and transcripts, run engagement/North Star/network/poll analyses, create and inspect Jane polls, open connections, preview sponsor ranking, and explicitly run dormant jobs. The `capabilities` command distinguishes active Chatwoot features, administrator workflows, provider-backed channels, and g01-only operations.
- Jane sends one rotating question per America/Chicago day to every private Jane thread. `poll mode` starts a community-action poll and `poll mode: <question>` broadcasts a supplied question. Free-text answers are captured once, compiled without invented consensus, and available through `polls`, `poll`, and `analyze polls`.
- Jane automatically compares recorded goals and poll answers within each locality. A proposal stays invisible to both users until an operator reviews it with `matches` and confirms `match-approve`; rejection contacts no one. After approval, both users must still accept and pass identity verification before a shared thread opens.
- Normal Chatwoot workspace behavior stays available. Messages, attachments, private notes, contacts, labels, assignment, status, snooze, and priority use upstream endpoints. g01 mirrors safe locality/thread metadata into labels and custom fields, and **g01 Community** lets a signed-in homesteader open a private connection by entering an exact username; it does not publish a member list.
- `jane-worker` and `jane-beat` are behind the Compose profile `background` and are not started. Jane's focused daily-poll and match-discovery schedulers run in the sidecar; the legacy Celery beat schedule stays empty unless `G01_BACKGROUND_JOBS` is on.
- Sign-in, the gold and white g01 chat, **Create an account**, and the private pair inbox are unchanged. Jane stays quiet in a connection unless someone says her name.
- **Forgot your password?** sends a reset link. Compose delivers that mail to Mailpit (`http://localhost:8025`) until `SMTP_ADDRESS` is a real mailbox.
- The website name is **g01denfleece.com** (`https://g01denfleece.com`). Login, the widget, and reset mail use that name. This machine still serves the app at `localhost` until the public host points here.
- The public host is one DigitalOcean droplet in Atlanta: Ubuntu 24.04, 8 GB RAM, 4 vCPU. `docker-compose.prod.yml` publishes only ports 80 and 443. Jane's admin API stays on `127.0.0.1:8000`.
- Launch review: images are pinned, strict bootstrap requires both Chatwoot tokens, Caddy waits for Jane's health check, the droplet installs Git, and postflight checks the public stack. Jane receives the same constitution and history with real chat roles so the small model keeps Jane and the homesteader distinct.

The legacy demand-poll checkpointer bug, Stripe, Gemini, sponsor ratings, capability embeddings, blueprints, and forget are unchanged. They are not on the live turn.
