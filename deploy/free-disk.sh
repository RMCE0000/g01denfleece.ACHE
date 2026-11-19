#!/bin/sh
# Keep the VM disk from filling up again.
#
# This removes Docker build cache and untagged leftover images, and shortens
# container log files that have grown past 20MB. It does not remove volumes,
# running containers, or any image a container is using. Postgres data, Redis
# data, Caddy certificates, and uploaded files stay where they are.

set -eu

THRESHOLD="${G01_DISK_THRESHOLD:-70}"
MOUNT="${G01_DISK_MOUNT:-/}"
LOG="${G01_DISK_LOG:-/var/log/g01-disk-cleanup.log}"

log() {
  line="$(date -u +%Y-%m-%dT%H:%M:%SZ) $*"
  printf '%s\n' "$line" >> "$LOG" 2>/dev/null || printf '%s\n' "$line" >&2
}

if ! command -v docker >/dev/null 2>&1; then
  log "docker is not installed; nothing to clean"
  exit 0
fi

usage="$(df -P "$MOUNT" | awk 'NR==2 { gsub(/%/, "", $5); print $5 }')"
case "$usage" in
  ''|*[!0-9]*)
    log "could not read disk use for $MOUNT"
    exit 1
    ;;
esac

# Keep our own record small.
if [ -f "$LOG" ]; then
  log_bytes="$(wc -c < "$LOG" | awk '{ print $1 }')"
  if [ "$log_bytes" -gt 1048576 ]; then
    tail -n 200 "$LOG" > "$LOG.trim"
    mv "$LOG.trim" "$LOG"
  fi
fi

# Untagged images left behind by a rebuild. Tagged images, including the ones
# the running containers use, are kept.
run() {
  if "$@" >> "$LOG" 2>&1; then
    return 0
  fi
  log "command failed: $*"
}

log "disk ${usage}% on ${MOUNT}; pruning dangling images"
run docker image prune -f

if [ "$usage" -ge "$THRESHOLD" ]; then
  log "disk ${usage}% is at or above ${THRESHOLD}%; pruning all build cache"
  run docker builder prune -af
else
  log "pruning build cache older than 24h"
  run docker builder prune -af --filter until=24h
fi

# A full disk also came from container logs. Shorten a large log file in place.
# This does not remove the container or its volume.
if [ -d /var/lib/docker/containers ]; then
  find /var/lib/docker/containers -name '*-json.log' -size +20M -exec truncate -s 0 {} \; || log "could not shorten a container log"
fi

log "disk cleanup finished"
