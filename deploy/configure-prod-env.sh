#!/usr/bin/env bash
# First-time production configuration. Provider secrets are read without echo
# and never placed on the command line or in shell history.
set -euo pipefail
umask 077

cd "$(dirname "$0")/.."

if [[ -e .env ]]; then
  echo ".env already exists; refusing to overwrite it" >&2
  exit 1
fi

command -v openssl >/dev/null || {
  echo "openssl is required" >&2
  exit 1
}
command -v python3 >/dev/null || {
  echo "python3 is required" >&2
  exit 1
}

read -r -p "Let's Encrypt notice email: " ACME_EMAIL
read -r -p "SMTP host: " SMTP_ADDRESS
read -r -p "SMTP port [587]: " SMTP_PORT
SMTP_PORT=${SMTP_PORT:-587}
read -r -p "SMTP username: " SMTP_USERNAME
read -r -s -p "SMTP password: " SMTP_PASSWORD
printf '\n'
read -r -p "SMTP domain [g01denfleece.com]: " SMTP_DOMAIN
SMTP_DOMAIN=${SMTP_DOMAIN:-g01denfleece.com}
read -r -s -p "Gemini API key: " G01_GEMINI_API_KEY
printf '\n'
read -r -s -p "Stripe secret key (sk_test_/sk_live_ or rk_test_/rk_live_): " G01_STRIPE_SECRET_KEY
printf '\n'
read -r -s -p "Stripe webhook signing secret (whsec_...): " G01_STRIPE_WEBHOOK_SECRET
printf '\n'
read -r -p "Stripe sponsor Price ID (price_...): " G01_STRIPE_SPONSOR_PRICE_ID

SECRET_KEY_BASE=$(openssl rand -hex 64)
POSTGRES_PASSWORD=$(openssl rand -hex 24)
G01_ADMIN_TOKEN=$(openssl rand -hex 32)
G01_BRIDGE_SECRET=$(openssl rand -hex 32)
G01_CHATWOOT_WEBHOOK_SECRET=$(openssl rand -hex 32)

export ACME_EMAIL SMTP_ADDRESS SMTP_PORT SMTP_USERNAME SMTP_PASSWORD SMTP_DOMAIN
export G01_GEMINI_API_KEY G01_STRIPE_SECRET_KEY G01_STRIPE_WEBHOOK_SECRET
export G01_STRIPE_SPONSOR_PRICE_ID SECRET_KEY_BASE POSTGRES_PASSWORD
export G01_ADMIN_TOKEN G01_BRIDGE_SECRET G01_CHATWOOT_WEBHOOK_SECRET

python3 <<'PY'
import os
from pathlib import Path

values = {
    key: os.environ[key]
    for key in (
        "ACME_EMAIL",
        "SMTP_ADDRESS",
        "SMTP_PORT",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
        "SMTP_DOMAIN",
        "G01_GEMINI_API_KEY",
        "G01_STRIPE_SECRET_KEY",
        "G01_STRIPE_WEBHOOK_SECRET",
        "G01_STRIPE_SPONSOR_PRICE_ID",
        "SECRET_KEY_BASE",
        "POSTGRES_PASSWORD",
        "G01_ADMIN_TOKEN",
        "G01_BRIDGE_SECRET",
        "G01_CHATWOOT_WEBHOOK_SECRET",
    )
}
values["G01_DATABASE_URL"] = (
    "postgresql+asyncpg://g01:"
    + values["POSTGRES_PASSWORD"]
    + "@postgres:5432/chatwoot"
)

template = Path(".env.production.example").read_text(encoding="utf-8")
output = []
seen = set()
for line in template.splitlines():
    key = line.split("=", 1)[0] if "=" in line else ""
    if key in values:
        output.append(f"{key}={values[key]}")
        seen.add(key)
    else:
        output.append(line)
for key, value in values.items():
    if key not in seen:
        output.append(f"{key}={value}")

path = Path(".env")
path.write_text("\n".join(output) + "\n", encoding="utf-8")
path.chmod(0o600)
PY

sh deploy/check-prod-env.sh
echo "Production .env is ready with mode 600."
