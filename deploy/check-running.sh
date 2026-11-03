#!/bin/sh
# Run on the droplet after the production Compose stack is up and DNS points at it.
set -eu

dc() {
  docker compose -f docker-compose.yml -f docker-compose.prod.yml "$@"
}

tokens=.chatwoot-bootstrap/chatwoot.env
[ -f "$tokens" ] || {
  echo "missing $tokens; recreate the bootstrap service" >&2
  exit 1
}

for key in G01_CHATWOOT_API_TOKEN G01_CHATWOOT_PLATFORM_TOKEN; do
  grep -Eq "^${key}=.+$" "$tokens" || {
    echo "$key is empty; account creation is not ready" >&2
    exit 1
  }
done

for service in postgres redis rails sidekiq ollama jane caddy; do
  id=$(dc ps -q "$service")
  [ -n "$id" ] || {
    echo "$service has no container" >&2
    exit 1
  }
  running=$(docker inspect -f '{{.State.Running}}' "$id")
  [ "$running" = "true" ] || {
    echo "$service is not running" >&2
    exit 1
  }
done

curl -fsS http://127.0.0.1:8000/health |
  python3 -c 'import json,sys; data=json.load(sys.stdin); assert data["ok"] and data["showcase"] == "minimum"'
curl -fsS https://g01denfleece.com/api |
  python3 -c 'import json,sys; data=json.load(sys.stdin); assert data["queue_services"] == "ok" and data["data_services"] == "ok"'

echo "g01 production services are ready"
