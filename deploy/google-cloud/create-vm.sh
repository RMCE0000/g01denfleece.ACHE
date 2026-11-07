#!/usr/bin/env bash
# Create the g01 production VM in a US Google Cloud region.
# Prerequisites: gcloud auth login && gcloud config set project YOUR_PROJECT
set -euo pipefail

cd "$(dirname "$0")/../.."

PROJECT="${GCP_PROJECT:?set GCP_PROJECT to your Google Cloud project id}"
REGION="${GCP_REGION:-us-central1}"
ZONE="${GCP_ZONE:-us-central1-a}"
NAME="${GCE_NAME:-g01denfleece}"
MACHINE="${GCE_MACHINE_TYPE:-e2-standard-4}"
DISK_GB="${GCE_DISK_GB:-80}"
SSH_SOURCE="${SSH_SOURCE_IP:?set SSH_SOURCE_IP to your public IPv4/32, for example 203.0.113.10/32}"

gcloud config set project "$PROJECT"

if ! gcloud compute addresses describe "$NAME-ip" --region="$REGION" >/dev/null 2>&1; then
  gcloud compute addresses create "$NAME-ip" --region="$REGION"
fi
ADDRESS=$(gcloud compute addresses describe "$NAME-ip" --region="$REGION" --format='get(address)')

gcloud compute firewall-rules describe "$NAME-ssh" >/dev/null 2>&1 || \
  gcloud compute firewall-rules create "$NAME-ssh" \
    --allow=tcp:22 \
    --target-tags=g01-web \
    --source-ranges="$SSH_SOURCE" \
    --description="g01 SSH from the operator IP only"

gcloud compute firewall-rules describe "$NAME-http" >/dev/null 2>&1 || \
  gcloud compute firewall-rules create "$NAME-http" \
    --allow=tcp:80 \
    --target-tags=g01-web \
    --description="g01 HTTP for Caddy ACME"

gcloud compute firewall-rules describe "$NAME-https" >/dev/null 2>&1 || \
  gcloud compute firewall-rules create "$NAME-https" \
    --allow=tcp:443,udp:443 \
    --target-tags=g01-web \
    --description="g01 HTTPS"

if gcloud compute instances describe "$NAME" --zone="$ZONE" >/dev/null 2>&1; then
  echo "instance $NAME already exists in $ZONE" >&2
  echo "reserved IPv4: $ADDRESS" >&2
  exit 0
fi

gcloud compute instances create "$NAME" \
  --zone="$ZONE" \
  --machine-type="$MACHINE" \
  --image-family=ubuntu-2404-lts-amd64 \
  --image-project=ubuntu-os-cloud \
  --boot-disk-size="${DISK_GB}GB" \
  --boot-disk-type=pd-balanced \
  --address="$ADDRESS" \
  --tags=g01-web \
  --metadata-from-file=user-data=deploy/google-cloud/cloud-init.yaml \
  --scopes=https://www.googleapis.com/auth/devstorage.read_only,https://www.googleapis.com/auth/logging.write,https://www.googleapis.com/auth/monitoring.write

echo "reserved IPv4: $ADDRESS"
echo "point g01denfleece.com A record at that address, then SSH:"
echo "  gcloud compute ssh $NAME --zone $ZONE"
echo "Stripe webhook https://g01denfleece.com/webhooks/stripe is created after HTTPS works."
