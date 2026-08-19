#!/bin/sh
set -eu
PUBLIC_DOMAIN="${RAILWAY_PUBLIC_DOMAIN:-}"
TCP_HOST="${RAILWAY_TCP_PROXY_DOMAIN:-}"
TCP_PORT="${RAILWAY_TCP_PROXY_PORT:-}"
APP_PORT="${RAILWAY_TCP_APPLICATION_PORT:-}"
[ -n "$PUBLIC_DOMAIN" ] || { echo "FATAL: RAILWAY_PUBLIC_DOMAIN unavailable; enable Public Networking and redeploy" >&2; exit 1; }
echo "SOURCE_REPOSITORY=gooidtto/way-v70"
echo "SOURCE_BRANCH=main"
echo "SOURCE_BUILD=way-v70-standard-core"
echo "RAILWAY_NETWORKING_SOURCE=current-deployment-environment"
echo "RAILWAY_GENERATE_DOMAIN=$PUBLIC_DOMAIN"
if [ -n "$TCP_HOST" ] && [ -n "$TCP_PORT" ] && [ -n "$APP_PORT" ]; then
  case "$TCP_PORT" in ''|*[!0-9]*) echo "FATAL: invalid RAILWAY_TCP_PROXY_PORT" >&2; exit 1;; esac
  case "$APP_PORT" in ''|*[!0-9]*) echo "FATAL: invalid RAILWAY_TCP_APPLICATION_PORT" >&2; exit 1;; esac
  [ "$TCP_PORT" -ge 1 ] && [ "$TCP_PORT" -le 65535 ] || { echo "FATAL: invalid RAILWAY_TCP_PROXY_PORT" >&2; exit 1; }
  [ "$APP_PORT" -ge 1 ] && [ "$APP_PORT" -le 65535 ] || { echo "FATAL: invalid RAILWAY_TCP_APPLICATION_PORT" >&2; exit 1; }
  echo "RAILWAY_TCP_PROXY=$TCP_HOST:$TCP_PORT"
  echo "RAILWAY_TCP_APPLICATION_PORT=$APP_PORT"
  echo "RAILWAY_NETWORKING_READY=true"
else
  echo "RAILWAY_TCP_PROXY=provisioning"
  echo "RAILWAY_TCP_APPLICATION_PORT=provisioning"
  echo "RAILWAY_NETWORKING_READY=false"
  echo "RAILWAY_BOOTSTRAP=first-deployment"
fi
exec /opt/xray/scripts/start.sh
