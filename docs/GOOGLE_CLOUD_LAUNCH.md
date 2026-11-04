# Google Cloud launch runbook

This runbook launches the production Compose stack at
`https://g01denfleece.com` on one Google Compute Engine VM. Run it from a
release ref that contains `docker-compose.prod.yml` and `deploy/Caddyfile`.
Do not deploy an older default branch that lacks those files.

Keep the app on a VM. Cloud Run and GKE would split Postgres, Redis, Rails,
Sidekiq, Jane, and Caddy across services this Compose file is not written for.

Use `us-central1` (Iowa) unless that zone is out of capacity. It is a US
region on Central Time and usually has the machine type below. `us-south1`
(Dallas) is closer to Lake Charles and Rogers if that SKU is available.

## 1. Provider preparation

Have these ready before creating `.env`:

- A Google Cloud project with billing enabled and the Compute Engine API on.
- A Google AI Studio API key with access to the configured Gemini models.
- A transactional SMTP account authorized to send as
  `jane@g01denfleece.com`.
- A Stripe secret key. Start with test mode, complete the smoke tests, and
  then replace all Stripe values with values from live mode.
- A recurring Stripe Product/Price for sponsorship. Record its `price_...`
  ID.
- Stripe Identity enabled on the account.

Do **not** create the Stripe webhook yet. Stripe must POST to
`https://g01denfleece.com/webhooks/stripe` after Caddy has a certificate.
Create that endpoint in section 6.

## 2. VM and firewall

Install the `gcloud` CLI, then:

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
export GCP_PROJECT=YOUR_PROJECT_ID
export SSH_SOURCE_IP='YOUR.PUBLIC.IP/32'
bash deploy/google-cloud/create-vm.sh
```

That creates:

- A reserved regional IPv4 address so DNS does not change if the VM restarts.
- An Ubuntu 24.04 LTS VM, `e2-standard-4` (4 vCPUs, 16 GB RAM), 80 GB disk.
- VPC rules: SSH from your IP only; TCP 80; TCP/UDP 443. Target tag `g01-web`.

Do not expose ports 3000, 5432, 6379, 8000, or 8025. The VPC firewall is
required because Docker-published ports can bypass UFW.

Optional weekly disk snapshots:

```bash
gcloud compute resource-policies create snapshot-schedule g01-weekly \
  --region=us-central1 \
  --max-retention-days=28 \
  --weekly-schedule=sunday \
  --start-time=06:00
gcloud compute disks add-resource-policies g01denfleece \
  --zone=us-central1-a \
  --resource-policies=g01-weekly
```

## 3. DNS and email

At the DNS provider:

1. Point one `A` record for `@` to the reserved VM IPv4 address.
2. Keep `www` as a CNAME to the apex domain.
3. Preserve Microsoft 365 MX/TXT records.
4. Add the SMTP provider's SPF and DKIM records without replacing existing
   Microsoft records.

Wait until this prints the VM address:

```bash
dig +short g01denfleece.com
```

## 4. Install and configure

SSH after cloud-init finishes Docker (a few minutes):

```bash
gcloud compute ssh g01denfleece --zone us-central1-a
```

If your account is not already in the Docker group:

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
and are not put in shell history. For the Stripe webhook signing secret, enter
a temporary placeholder such as `whsec_pending` if the public site is not up
yet; replace it in section 6.

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

Confirm the webhook path exists before telling Stripe about it:

```bash
curl -sS -o /dev/null -w '%{http_code}\n' -X POST https://g01denfleece.com/webhooks/stripe
```

That must print `400`. `000`, `404`, or a TLS error means HTTPS is not ready.

## 6. Stripe webhook

Create the endpoint only after the curl above returns `400`:

```bash
python3 - <<'PY'
import os, stripe
stripe.api_key = os.environ["G01_STRIPE_SECRET_KEY"]
endpoint = stripe.WebhookEndpoint.create(
    url="https://g01denfleece.com/webhooks/stripe",
    enabled_events=[
        "checkout.session.completed",
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "invoice.payment_failed",
        "invoice.paid",
        "identity.verification_session.verified",
    ],
)
print(endpoint.id)
print(endpoint.secret)
PY
```

Put the printed `whsec_...` in `.env` as `G01_STRIPE_WEBHOOK_SECRET`, then:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d jane
```

Test and live modes have different keys, Price IDs, and webhook secrets; never
mix modes. The publishable `pk_...` key is not used because Checkout and
Identity sessions are created on the server.

## 7. Launch smoke tests

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

## 8. Backups

GCE snapshot schedules are the machine-level recovery layer. Also take a
logical database backup before every application update:

```bash
mkdir -p backups
chmod 700 backups
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T postgres \
  pg_dump -U g01 -d chatwoot | gzip > "backups/chatwoot-$(date -u +%Y%m%dT%H%M%SZ).sql.gz"
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T rails \
  tar -C /app -czf - storage > "backups/chatwoot-storage-$(date -u +%Y%m%dT%H%M%SZ).tar.gz"
tar -czf "backups/bootstrap-$(date -u +%Y%m%dT%H%M%SZ).tar.gz" .chatwoot-bootstrap
```

Copy the encrypted backup, `.env`, and `.chatwoot-bootstrap/` to a GCS bucket
or other off-VM storage. Never commit them. Test a restore on a disposable
staging VM before relying on it.

## 9. Updates and rollback

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
- The VPC firewall is attached to the VM.
- DNS and HTTPS work.
- Production SMTP reset mail arrives.
- Gemini Flash, Pro, and embeddings pass live calls.
- Stripe test Checkout and Identity webhooks pass through Caddy.
- Fictional seed sponsors remain inactive; only verified profiles are active.
- `sh deploy/check-running.sh` passes.
- A database backup has been copied off the VM.
