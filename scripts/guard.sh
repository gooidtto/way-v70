#!/bin/sh
set -eu

# Keep this guard intentionally small. The deployment source of truth is the
# currently injected Railway environment; start.sh owns generation/readiness.
PUBLIC_DOMAIN="${RAILWAY_PUBLIC_DOMAIN:-}"
TCP_HOST="${RAILWAY_TCP_PROXY_DOMAIN:-}"
TCP_PORT="${RAILWAY_TCP_PROXY_PORT:-}"

[ -n "$PUBLIC_DOMAIN" ] || { echo "FATAL: RAILWAY_PUBLIC_DOMAIN unavailable" >&2; exit 1; }
[ -n "$TCP_HOST" ] && [ -n "$TCP_PORT" ] || { echo "FATAL: Railway TCP Proxy unavailable" >&2; exit 1; }
case "$TCP_PORT" in
  ''|*[!0-9]*) echo "FATAL: invalid RAILWAY_TCP_PROXY_PORT" >&2; exit 1 ;;
esac
[ "$TCP_PORT" -ge 1 ] && [ "$TCP_PORT" -le 65535 ] || { echo "FATAL: invalid RAILWAY_TCP_PROXY_PORT" >&2; exit 1; }

echo "SOURCE_REPOSITORY=gooidtto/railway-v60-four-node"
echo "SOURCE_BRANCH=main"
echo "RAILWAY_PUBLIC_DOMAIN=$PUBLIC_DOMAIN"
echo "RAILWAY_TCP_PROXY=$TCP_HOST:$TCP_PORT"
exec /opt/xray/scripts/start.sh
