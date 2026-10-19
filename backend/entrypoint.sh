#!/bin/sh
# With arguments: run them (worker, migrations, a shell, ...).
# Without: serve the API on $PORT (Render sets it; 8000 locally).
#
# --no-proxy-headers: uvicorn must not rewrite the client address from X-Forwarded-For. With
# --forwarded-allow-ips '*' it took the leftmost entry, which any client can set. The app reads the
# header itself, only from peers in TRUSTED_PROXY_CIDRS (vik/auth.py client_ip).
set -e

if [ "$#" -gt 0 ]; then
  exec "$@"
fi

exec uvicorn vik.api:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --ws-ping-interval 20 \
  --no-proxy-headers
