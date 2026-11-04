# DigitalOcean launch runbook

This runbook launches the production Compose stack at
`https://g01denfleece.com`. Run it from a release ref that contains
`docker-compose.prod.yml` and `deploy/Caddyfile`. Do not deploy an older
default branch that lacks those files.

## 1. Provider preparation

Have these ready before creating `.env`:

- A Google AI Studio API key with access to the configured Gemini models.
- A transactional SMTP account authorized to send as
  `jane@g01denfleece.com`.
- A Stripe secret key. Start with test mode, complete the smoke tests, and
  then replace all Stripe values with values from live mode.
- A recurring Stripe Product/Price for sponsorship. Record its `price_...`
  ID.
- Stripe Identity enabled on the account.
- A Stripe webhook destination:
  `https://g01denfleece.com/webhooks/stripe`, subscribed to:
  - `checkout.session.completed`
  - `identity.verification_session.verified`

Record that endpoint's `whsec_...` signing secret. Stripe test and live modes
have different keys, Price IDs, and webhook secrets; never mix modes. The
publishable `pk_...` key is not used because Checkout and Identity sessions
are created on the server.

## 2. Droplet and firewall

Create an Ubuntu 24.04 LTS droplet in `atl1` with 8 GB RAM, 4 vCPUs, and at
least 80 GB disk. Add an SSH key, monitoring, and weekly DigitalOcean backups.
Paste `deploy/digitalocean/cloud-init.yaml` into the droplet's user-data field.

Attach a DigitalOcean Cloud Firewall:

| Direction | Protocol/port | Source |
| --- | --- | --- |
| Inbound | TCP 22 | Your current public IP only |
| Inbound | TCP 80 | Anywhere |
| Inbound | TCP 443 | Anywhere |
| Inbound | UDP 443 | Anywhere |
| Outbound | All | Anywhere |

Do not expose ports 3000, 5432, 6379, 8000, or 8025. The cloud firewall is
required because Docker-published ports can bypass UFW.

## 3. DNS and email

At the DNS provider:

1. Point one `A` record for `@` to the droplet IPv4 address.
2. Keep `www` as a CNAME to the apex domain.
3. Preserve Microsoft 365 MX/TXT records.
4. Add the SMTP provider's SPF and DKIM records without replacing existing
   Microsoft records.

Wait until this prints the droplet address:

```bash
dig +short g01denfleece.com
```

## 4. Install and configure

SSH into the droplet. Cloud-init installs Docker and Git. For the usual
`ubuntu` account, enable Docker access and reconnect once:

```bash
sudo usermod -aG docker "$USER"
exit
```

Reconnect, then clone the release:

```bash
git clone https://github.com/RMCE0000/g01denfleece.ACHE.git
cd g01denfleece.ACHE
git checkout <launch-tag-or-merged-main>
```

The configuration helper generates the database, Chatwoot, bridge, admin, and
internal webhook secrets locally. Provider secrets are prompted without echo
and are not put in shell history:

```bash
bash deploy/configure-prod-env.sh
```

The command creates a gitignored `.env` with mode `600` and runs the production
preflight. Protect `.env`; do not paste it into chat or commit it.

## 5. First start

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  logs -f rails bootstrap jane caddy
```

The first Chatwoot migration can take several minutes. Stop following logs
with `Ctrl-C`; this does not stop the containers.

Then run:

```bash
sh deploy/check-running.sh
```

The postflight requires:

- Postgres, Redis, Rails, Sidekiq, Jane, and Caddy running.
- Chatwoot account and platform tokens from bootstrap.
- Jane healthy with Gemini configured.
- Public Chatwoot health passing over HTTPS.
- The public Stripe route reaching Jane and rejecting an unsigned request.

If bootstrap fails:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs bootstrap
docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm bootstrap
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d jane
```

## 6. Launch smoke tests

Before inviting users:

1. Open `https://g01denfleece.com` and confirm the branded login page.
2. Use **Create an account** with a permitted ZIP such as `70601`.
3. Confirm the user receives a private Jane thread and Gemini answers.
4. Use **Forgot password** and confirm delivery through the production SMTP
   provider.
5. Ask Jane `poll mode`, answer the poll, and inspect it in the operator TUI.
6. Ask Jane where to find a known active sponsor product and confirm the
   locality-ranked sponsor list.
7. Create a test sponsor application and complete a Stripe test Checkout.
   Confirm the signed webhook activates that sponsor.
8. Request identity verification in Jane's thread and complete a Stripe test
   Identity session. Confirm KYC updates.
9. Create an automatic match, review it in the TUI, and verify no users are
   contacted before `match-approve`.
10. Dial another test homesteader by exact username and confirm no public
    directory is exposed.

Open the private operator console:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  exec jane python -m app.operator
```

Useful commands:

```text
dashboard
capabilities
users
chats
polls
matches pending
sponsors active
rank <username> <product-or-service>
```

The bootstrap credentials are in `.chatwoot-bootstrap/operator.txt`. Restrict
that directory and `.env` to trusted operators.

## 7. Backups

DigitalOcean backups are the machine-level recovery layer. Also take a logical
database backup before every application update:

```bash
mkdir -p backups
chmod 700 backups
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T postgres \
  pg_dump -U g01 -d chatwoot | gzip > "backups/chatwoot-$(date -u +%Y%m%dT%H%M%SZ).sql.gz"
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T rails \
  tar -C /app -czf - storage > "backups/chatwoot-storage-$(date -u +%Y%m%dT%H%M%SZ).tar.gz"
tar -czf "backups/bootstrap-$(date -u +%Y%m%dT%H%M%SZ).tar.gz" .chatwoot-bootstrap
```

Copy the encrypted backup, `.env`, and `.chatwoot-bootstrap/` to secure
off-droplet storage. Never commit them. Test a restore on a disposable
staging droplet before relying on it.

## 8. Updates and rollback

Record the current commit and back up first:

```bash
git rev-parse HEAD
git fetch origin
git checkout <new-launch-tag>
sh deploy/check-prod-env.sh
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
sh deploy/check-running.sh
```

To roll application code back, check out the recorded commit and run the same
Compose and postflight commands. Do not rotate `SECRET_KEY_BASE`,
`POSTGRES_PASSWORD`, or provider secrets during a code rollback.

## Launch gate

Do not invite real users until all are true:

- The launch changes are merged or tagged in the deployed ref.
- The DigitalOcean Cloud Firewall is attached.
- DNS and HTTPS work.
- Production SMTP reset mail arrives.
- Gemini Flash, Pro, and embeddings pass live calls.
- Stripe test Checkout and Identity webhooks pass through Caddy.
- Fictional seed sponsors remain inactive; only verified profiles are active.
- `sh deploy/check-running.sh` passes.
- A database backup has been copied off the droplet.
