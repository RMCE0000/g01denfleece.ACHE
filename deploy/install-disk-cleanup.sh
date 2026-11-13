#!/bin/sh
# Install a root cron job that runs deploy/free-disk.sh every 15 minutes.
# The cron line points at this checkout, so a later git pull updates the cleanup.

set -eu

if [ "$(id -u)" -ne 0 ]; then
  printf 'Run this with sudo from the checkout: sudo sh deploy/install-disk-cleanup.sh\n' >&2
  exit 1
fi

ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
SCRIPT="$ROOT/deploy/free-disk.sh"
chmod 0755 "$SCRIPT"

cat > /etc/cron.d/g01-disk-cleanup << EOF
SHELL=/bin/sh
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
*/15 * * * * root $SCRIPT
EOF
chmod 0644 /etc/cron.d/g01-disk-cleanup

"$SCRIPT"
printf 'Disk cleanup is scheduled every 15 minutes from %s\n' "$SCRIPT"
