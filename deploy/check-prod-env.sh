#!/bin/sh
# Refuse to boot the public stack with the local passwords.
set -eu

file=${1:-.env}
if [ ! -f "$file" ]; then
  echo "missing $file" >&2
  exit 1
fi

value() {
  # Last matching assignment, without the key. Values may contain "=".
  grep -E "^$1=" "$file" | tail -n 1 | cut -d= -f2- || true
}

fail() {
  echo "$1" >&2
  exit 1
}

secret=$(value SECRET_KEY_BASE)
postgres=$(value POSTGRES_PASSWORD)
admin=$(value G01_ADMIN_TOKEN)
bridge=$(value G01_BRIDGE_SECRET)
database_url=$(value G01_DATABASE_URL)
frontend=$(value FRONTEND_URL)
public_url=$(value G01_CHATWOOT_PUBLIC_URL)
acme=$(value ACME_EMAIL)
smtp=$(value SMTP_ADDRESS)
smtp_user=$(value SMTP_USERNAME)
smtp_password=$(value SMTP_PASSWORD)
sender=$(value MAILER_SENDER_EMAIL)
seed=$(value G01_SEED_HOMESTEADERS)
gemini=$(value G01_GEMINI_API_KEY)
chatwoot_webhook=$(value G01_CHATWOOT_WEBHOOK_SECRET)
stripe_secret=$(value G01_STRIPE_SECRET_KEY)
stripe_webhook=$(value G01_STRIPE_WEBHOOK_SECRET)
stripe_price=$(value G01_STRIPE_SPONSOR_PRICE_ID)

case "$secret" in
  ""|G01devSecretKeyBase0123456789abcdefghijklmnopqrstuvwxyzABCDEF|*replace-with*)
    fail "SECRET_KEY_BASE still has a placeholder. On the VM: openssl rand -hex 64"
    ;;
esac
case "$postgres" in
  ""|g01|*replace-with*)
    fail "POSTGRES_PASSWORD still has a placeholder. On the VM: openssl rand -hex 24"
    ;;
esac
case "$admin" in
  ""|g01-local-admin-token|*replace-with*)
    fail "G01_ADMIN_TOKEN still has a placeholder. On the VM: openssl rand -hex 32"
    ;;
esac
case "$bridge" in
  ""|g01-local-bridge-token|*replace-with*)
    fail "G01_BRIDGE_SECRET still has a placeholder. On the VM: openssl rand -hex 32"
    ;;
esac
[ "$bridge" != "$admin" ] || fail "G01_BRIDGE_SECRET must differ from G01_ADMIN_TOKEN"
case "$chatwoot_webhook" in
  ""|*replace-with*) fail "G01_CHATWOOT_WEBHOOK_SECRET needs a dedicated openssl rand -hex 32 value" ;;
esac
[ "$chatwoot_webhook" != "$admin" ] || fail "G01_CHATWOOT_WEBHOOK_SECRET must differ from G01_ADMIN_TOKEN"
[ "$chatwoot_webhook" != "$bridge" ] || fail "G01_CHATWOOT_WEBHOOK_SECRET must differ from G01_BRIDGE_SECRET"
printf '%s' "$database_url" | grep -F -q "$postgres" || fail "G01_DATABASE_URL must contain the same POSTGRES_PASSWORD"
[ "$frontend" = "https://g01denfleece.com" ] || fail "FRONTEND_URL must be https://g01denfleece.com"
[ "$public_url" = "https://g01denfleece.com" ] || fail "G01_CHATWOOT_PUBLIC_URL must be https://g01denfleece.com"
case "$acme" in
  ""|*example.com|*replace-with*) fail "ACME_EMAIL needs a real mailbox for certificate notices" ;;
esac
case "$smtp" in
  ""|mailpit|*replace-with*) fail "SMTP_ADDRESS needs a public SMTP provider" ;;
esac
case "$smtp_user" in
  ""|*replace-with*) fail "SMTP_USERNAME still has a placeholder" ;;
esac
printf '%s' "$sender" | grep -F -q "jane@g01denfleece.com" || fail "MAILER_SENDER_EMAIL must be Jane <jane@g01denfleece.com>"
case "$smtp_password" in
  ""|*replace-with*) fail "SMTP_PASSWORD still has a placeholder" ;;
esac
[ "$seed" = "0" ] || fail "G01_SEED_HOMESTEADERS must be 0 on the public machine"
case "$gemini" in
  ""|*replace-with*) fail "G01_GEMINI_API_KEY needs a Google AI Studio API key" ;;
esac
case "$stripe_secret" in
  sk_live_*|sk_test_*|rk_live_*|rk_test_*) ;;
  *) fail "G01_STRIPE_SECRET_KEY must be a Stripe sk_ or rk_ secret key" ;;
esac
case "$stripe_webhook" in
  whsec_*) ;;
  *) fail "G01_STRIPE_WEBHOOK_SECRET must be the endpoint's whsec_ signing secret" ;;
esac
case "$stripe_price" in
  price_*) ;;
  *) fail "G01_STRIPE_SPONSOR_PRICE_ID must be a Stripe price_ id" ;;
esac

echo "production env is ready"
