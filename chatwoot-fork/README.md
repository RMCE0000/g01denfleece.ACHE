# Chatwoot overlay

Chatwoot's Rails and Vue code stays upstream. `docker-compose.yml` runs `chatwoot/chatwoot:latest` unchanged. Jane does not replace ActionCable, message persistence, or login.

This directory does not add a page, a Dashboard App, or a proxy form. The stock image does not load these notes. The running integration is:

1. A homesteader signs in at Chatwoot's own `/app/login`. The backend creates that user; account signup stays off.
2. The first ZIP Jane hears opens one conversation with `status: open`. Turn off that inbox's auto-resolve timer so the thread stays open.
3. Jane is a peer (`G01_JANE_USER_ID`, default user 1, or an AgentBot). Her posts set `content_attributes.g01_author = jane`, and the webhook ignores them.
4. Chatwoot's account webhook `message_created` points at `http://jane:8000/webhooks/chatwoot`.
5. Scores, ranking, sponsorship, and identity verification are questions in that thread. There is no g01 iframe and no extra Rails route.

On boot, when `G01_CHATWOOT_API_TOKEN` is set, the sidecar tries to register that webhook through Chatwoot's API. It does not register a dashboard app.
