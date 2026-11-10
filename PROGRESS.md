# g01 progress log

Updated 4 Nov 2026, 10:08 AM America/Chicago.

## Still open from the MVP

The four MVP behaviors are on `main`: chat scores, local ranking, 24-hour polls, and the neighbor gate. These parts are still short of a finished stack.

1. **Stripe still needs account-side configuration.** The public signed webhook route, replay protection, Checkout, and Identity handlers are wired. Launch still requires matching Stripe secret, Price, and webhook signing values plus a successful test-mode smoke.

2. **Two ranking inputs never move.** `homesteader_rating` stays at 5.00, and `capabilities_embedding` is never written.

3. **The original brief also named plan and blueprint reading, and a way to forget a recorded fact.** Neither is in the sidecar. The constitution's later laws were inferred because the source brief stopped at "3. DIY".

## This slice

Insured is the guiding principle of the North Star, with utilized added beneath it beside the original five aims. Jane offers insurance only from products the operator files, and she states coverage only from knowledge entries whose topics the message touches. A local insurance producer remains a sponsor.

## Earlier slice

The minimum showcase (MS). Jane's LangChain flow sends her constitution and role-preserved message history to Gemini.

- `jane-sidecar/CONSTITUTION.md` is what she is given. It is not the old JSON ledger prompt.
- Jane's live response is a LangChain flow. Standard turns use `G01_GEMINI_CHAT_MODEL`; complex planning, comparison, and analysis use `G01_GEMINI_DELIBERATION_MODEL`. Both use `G01_GEMINI_API_KEY`, and failure is stated explicitly.
- `GET /api/admin/conversations` lists every Jane thread and every connection, with the people and the messages, so a connection can be opened with `POST /api/admin/conversations`.
- `docker compose exec jane python -m app.operator` opens the private operator command center. It can inspect all homesteaders and transcripts, run engagement/North Star/network/poll analyses, create and inspect Jane polls, open connections, preview sponsor ranking, and explicitly run dormant jobs. The `capabilities` command distinguishes active g01 features, administrator workflows, provider-backed channels, and g01-only operations.
- Jane sends one rotating question per America/Chicago day to every private Jane thread. `poll mode` starts a community-action poll and `poll mode: <question>` broadcasts a supplied question. Free-text answers are captured once, compiled without invented consensus, and available through `polls`, `poll`, and `analyze polls`.
- Jane automatically compares recorded goals and poll answers within each locality. A proposal stays invisible to both users until an operator reviews it with `matches` and confirms `match-approve`; rejection contacts no one. After approval, both users must still accept and pass identity verification before a shared thread opens.
- Normal g01 workspace behavior stays available. Messages, attachments, private notes, contacts, labels, assignment, status, snooze, and priority use upstream endpoints. g01 mirrors safe locality/thread metadata into labels and custom fields, and **g01 Community** lets a signed-in homesteader open a private connection by entering an exact username; it does not publish a member list.
- `jane-worker` and `jane-beat` are behind the Compose profile `background` and are not started. Jane's focused daily-poll, 24-hour demand-poll, and match-discovery schedulers run in the sidecar.
- Sign-in, the gold and white g01 chat, **Create an account**, and the private pair inbox are unchanged. Jane stays quiet in a connection unless someone says her name.
- **Forgot your password?** sends a reset link. Compose delivers that mail to Mailpit (`http://localhost:8025`) until `SMTP_ADDRESS` is a real mailbox.
- The website name is **g01denfleece.com** (`https://g01denfleece.com`). Login, the widget, and reset mail use that name. This machine still serves the app at `localhost` until the public host points here.
- The public host is one Google Compute Engine VM in `us-central1`: Ubuntu 24.04, `e2-standard-4`. `docker-compose.prod.yml` publishes only ports 80 and 443. Jane's admin API stays on `127.0.0.1:8000`.
- Launch review: images are pinned, strict bootstrap requires both g01 tokens, Caddy waits for Jane's health check, the VM installs Git, and postflight checks the public stack. Jane receives the same constitution and history with real chat roles so the small model keeps Jane and the homesteader distinct.

The demand-poll checkpointer path and automatic maturity are fixed. Remaining
product work is sponsor ratings, capability embeddings, blueprint reading, and
forgetting recorded facts; Stripe is code-complete but still requires the
account-side launch configuration and smoke test.
