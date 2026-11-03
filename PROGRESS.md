# g01 progress log

Updated 3 Nov 2026, 12:40 PM America/Chicago.

## Still open from the MVP

The four MVP behaviors are on `main`: chat scores, local ranking, 24-hour polls, and the neighbor gate. These parts are still short of a finished stack.

1. **Scheduled polls and the neighbor scan fail when Postgres is on.** Celery compiles those graphs with the Postgres checkpointer and then runs them without a `thread_id`. LangGraph rejects that call, so the 24-hour synthesis and the background match do not finish in Compose. The pytest suite stays green because it uses the memory store. Live turns also do not record a checkpoint.

2. **Stripe and Gemini are unwired until their keys are set.** With the keys empty, Jane answers from the ledger and the phrase rules, goal embeddings are never computed, a filed sponsor stays inactive, and identity verification cannot complete. Promo codes stay closed until `G01_ADMIN_TOKEN` is set. An admin still creates the Stripe coupon; the sidecar only stores the coupon id.

3. **Two ranking inputs never move.** `homesteader_rating` stays at 5.00, and `capabilities_embedding` is never written.

4. **The original brief also named plan and blueprint reading, and a way to forget a recorded fact.** Neither is in the sidecar. The constitution's later laws were inferred because the source brief stopped at "3. DIY".

## This slice

Signed-in Chatwoot, gold and white, the g01 logo, and a backend conversation between two homesteaders.

- Chatwoot's own login at `/app/login` is the sign-in. The shell is white with gold accents, and the g01 mark replaces the Chatwoot logo. The public widget header is the same gold. **Create an account** on that page opens a sign-in and a Jane thread for a new homesteader. Chatwoot's separate-account signup stays off.
- `POST /api/admin/homesteaders` creates a Chatwoot user, a private "Jane — {name}" inbox, and the property row. That person signs in and talks to Jane there.
- `POST /api/admin/conversations` opens a private inbox named for the pair. Both homesteaders and Jane are members. Jane stays quiet in that thread unless someone says her name.
- Compose seeds Ada Yard (`ada.yard@example.com`) and Bea Chenier (`bea.chenier@example.com`) and the conversation between them. Passwords are in `.chatwoot-bootstrap/homesteaders.txt` after Jane starts. They are local demo passwords.

The checkpointer bug, Stripe, Gemini, sponsor ratings, capability embeddings, blueprints, and forget are unchanged.
