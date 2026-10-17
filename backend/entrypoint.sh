#!/bin/sh
# With arguments: run them (worker, migrations, a shell, ...).
# Without: serve the API on $PORT (Render sets it; 8000 locally).
set -e

if [ "$#" -gt 0 ]; then
  exec "$@"
fi

exec uvicorn vicky.api:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --ws-ping-interval 20 \
  --proxy-headers \
  --forwarded-allow-ips '*'
