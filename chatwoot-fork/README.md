# Chatwoot overlay

Chatwoot's Rails and Vue code stays upstream. `docker-compose.yml` runs `chatwoot/chatwoot:latest` unchanged. Jane does not replace ActionCable, message persistence, or login.

This directory is the optional thin overlay if you later fork Chatwoot and want same-origin proxy routes. The stock image does not load these files. The running integration is:

1. A homesteader is a Chatwoot user with a contact profile.
2. Signup, or the first ZIP Jane hears, opens one conversation with `status: open`. Turn off that inbox's auto-resolve timer so the thread stays open.
3. Jane is a peer (`G01_JANE_USER_ID`, default user 1, or an AgentBot). Her posts set `content_attributes.g01_author = jane`, and the webhook ignores them.
4. Chatwoot's account webhook `message_created` points at `http://jane:8000/webhooks/chatwoot`.
5. The North Star, aesthetic slider, KYC link, and sponsorship form are a Dashboard App iframe at `http://jane:8000/ui/hud`. Chatwoot already passes the conversation and contact with `window.postMessage`. No Vue change is required.

On boot, when `G01_CHATWOOT_API_TOKEN` is set, the sidecar tries to register that webhook and dashboard app through Chatwoot's API.
