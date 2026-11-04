# Chatwoot overlay

Chatwoot's Rails and Vue code stays upstream. `docker-compose.yml` runs `chatwoot/chatwoot:latest` unchanged. Jane does not replace ActionCable, message persistence, or login.

This directory does not carry a Chatwoot source fork. The running image loads
small, versioned overlays from `ops/` and `branding/`: branding/signup
middleware, an authenticated community controller, and the g01 Community
sidebar dialog. Messaging and the rest of the dashboard stay upstream.

1. A homesteader signs in at Chatwoot's own `/app/login`. **Create an account** on that page posts to `/g01/signup`, which Jane turns into a user on the g01 account. Chatwoot's own signup stays off.
2. The first ZIP Jane hears opens one conversation with `status: open`. Turn off that inbox's auto-resolve timer so the thread stays open.
3. Jane is a peer (`G01_JANE_USER_ID`, default user 1, or an AgentBot). Her posts set `content_attributes.g01_author = jane`, and the webhook ignores them.
4. Chatwoot's account webhook `message_created` points at `http://jane:8000/webhooks/chatwoot`.
5. Jane answers from a small local model. Each prompt is her constitution and the message history.
6. Signed-in homesteaders can use **g01 Community** to open their own private peer inbox. The same-origin Rails route authenticates the dashboard user and bridges only that identity to Jane.
7. g01 labels and custom attributes make contacts and conversations useful in normal Chatwoot filtering while sensitive homestead data remains in Jane's tables.

On boot, when `G01_CHATWOOT_API_TOKEN` is set, the sidecar tries to register that webhook through Chatwoot's API. It does not register a dashboard app.
