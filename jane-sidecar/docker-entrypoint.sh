#!/bin/sh
# Load the Chatwoot account, inbox, and Jane token written by ops/bootstrap_chatwoot.rb.
set -e
if [ -f /bootstrap/chatwoot.env ]; then
  set -a
  # shellcheck disable=SC1091
  . /bootstrap/chatwoot.env
  set +a
fi
exec "$@"
