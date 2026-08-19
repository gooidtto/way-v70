#!/bin/sh
set -eu
umask 077
BUILD_ID="way-v70-standard-core"; SOURCE_BUILD="way-v70-standard-core"
D="${RAILWAY_VOLUME_MOUNT_PATH:-${DATA_DIR:-/data}}"; C="${XRAY_CONFIG:-${D}/config.json}"; mkdir -p "$D" "$(dirname "$C")"
secret(){ f="$1";v="$2";t="$f.tmp";printf '%s\n' "$v">"$t";chmod 600 "$t";mv -f "$t" "$f"; }
PUBLIC="${RAILWAY_PUBLIC_DOMAIN:-}"; TCP_HOST="${RAILWAY_TCP_PROXY_DOMAIN:-}"; TCP_PORT="${RAILWAY_TCP_PROXY_PORT:-}"; APP_PORT="${RAILWAY_TCP_APPLICATION_PORT:-}"
[ -n "$PUBLIC" ] || { echo "FATAL: Railway Generate Domain unavailable; enable Public Networking and redeploy" >&2; exit 1; }
BOOTSTRAP=0
if [ -z "$TCP_HOST" ] || [ -z "$TCP_PORT" ] || [ -z "$APP_PORT" ]; then BOOTSTRAP=1; echo "RAILWAY_NETWORKING_PENDING=true"; echo "RAILWAY_GENERATE_DOMAIN_DETECTED=$PUBLIC"; echo "RAILWAY_TCP_PROXY_DETECTED=false"; echo "BOOTSTRAP_MODE=node01-only"; fi
if [ "$BOOTSTRAP" = 0 ]; then
  case "$TCP_PORT" in ''|*[!0-9]*) echo "FATAL: invalid current Railway TCP proxy port" >&2; exit 1;; esac
  case "$APP_PORT" in ''|*[!0-9]*) echo "FATAL: invalid current Railway TCP application port" >&2; exit 1;; esac
  [ "$TCP_PORT" -ge 1 ] && [ "$TCP_PORT" -le 65535 ] || { echo "FATAL: invalid current Railway TCP proxy port" >&2; exit 1; }
  [ "$APP_PORT" -ge 1 ] && [ "$APP_PORT" -le 65535 ] || { echo "FATAL: invalid current Railway TCP application port" >&2; exit 1; }
else
  APP_PORT="${PORT:-${GATEWAY_PORT:-8080}}"
fi
if [ -s "$D/uuid.txt" ]; then UUID=$(tr -d '[:space:]'<"$D/uuid.txt"); else UUID=$(xray uuid); secret "$D/uuid.txt" "$UUID"; fi
if [ -s "$D/reality_private_key.txt" ] && [ -s "$D/reality_public_key.txt" ]; then PRIV=$(tr -d '[:space:]'<"$D/reality_private_key.txt"); PUB=$(tr -d '[:space:]'<"$D/reality_public_key.txt"); else OUT=$(xray x25519 2>&1); PRIV=$(printf '%s\n' "$OUT"|awk -F': ' '/^PrivateKey/{print $2;exit}'); PUB=$(printf '%s\n' "$OUT"|awk -F': ' '/^Password/{print $2;exit}'); [ -n "$PRIV" ] && [ -n "$PUB" ] || exit 1; secret "$D/reality_private_key.txt" "$PRIV"; secret "$D/reality_public_key.txt" "$PUB"; fi
if [ -s "$D/subscription_token.txt" ]; then TOKEN=$(tr -d '[:space:]'<"$D/subscription_token.txt"); else TOKEN=$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))'); secret "$D/subscription_token.txt" "$TOKEN"; fi
CF_TOKEN="${CLOUDFLARE_TUNNEL_TOKEN:-}"; CF_ID="${CLOUDFLARE_TUNNEL_ID:-}"; CF_HOST="${CLOUDFLARE_PUBLIC_HOSTNAME:-}"; CF_ORIGIN="${CLOUDFLARE_ORIGIN_SERVICE:-}"; CF_PORT="${WS_PORT:-}"; CF_PATH="${WS_PATH:-}"
export DATA_DIR="$D" XRAY_CONFIG="$C" UUID PRIVATE_KEY="$PRIV" PUBLIC_KEY="$PUB" GATEWAY_PORT="$APP_PORT" RAILWAY_PUBLIC_DOMAIN="$PUBLIC" RAILWAY_TCP_PROXY_DOMAIN="$TCP_HOST" RAILWAY_TCP_PROXY_PORT="$TCP_PORT" RAILWAY_TCP_APPLICATION_PORT="$APP_PORT" XHTTP_PATH="${XHTTP_PATH:-/xhttp}" REALITY_RAW_SNI="${REALITY_RAW_SNI:-www.cloudflare.com}" REALITY_RAW_TARGET="${REALITY_RAW_TARGET:-www.cloudflare.com:443}" REALITY_FINGERPRINT="${REALITY_FINGERPRINT:-chrome}" REALITY_XHTTP_SNI="${REALITY_XHTTP_SNI:-www.apple.com}" REALITY_XHTTP_TARGET="${REALITY_XHTTP_TARGET:-www.apple.com:443}" CLOUDFLARE_TUNNEL_TOKEN="$CF_TOKEN" CLOUDFLARE_TUNNEL_ID="$CF_ID" CLOUDFLARE_PUBLIC_HOSTNAME="$CF_HOST" CLOUDFLARE_ORIGIN_SERVICE="$CF_ORIGIN" WS_PORT="$CF_PORT" WS_PATH="$CF_PATH"
python3 /opt/xray/scripts/generate.py
R="$D/runtime.json"; [ -s "$R" ] || exit 1
python3 - "$C" "$D/subscription.txt" "$UUID" "$R" "$PUBLIC" "$TCP_HOST" "$TCP_PORT" <<'PY'
import json,re,sys
from pathlib import Path
cfg=json.loads(Path(sys.argv[1]).read_text()); sub=[x for x in Path(sys.argv[2]).read_text().splitlines() if x.strip()]; u,rt,public,tcp_host,tcp_port=sys.argv[3],json.loads(Path(sys.argv[4]).read_text()),sys.argv[5],sys.argv[6],sys.argv[7]
bootstrap=bool(rt.get('bootstrap')); cf=bool(rt['cloudflare']['enabled']); expected=1 if bootstrap else (4 if cf else 3); n=int(rt['nodes']['count']); app=rt.get('application_port')
if n!=expected or len(sub)!=expected or len(cfg['inbounds'])!=expected: raise SystemExit(f'FATAL: topology mismatch runtime={n} xray={len(cfg["inbounds"])} subscription={len(sub)} expected={expected}')
ids=[x.get('id') for i in cfg['inbounds'] for x in i.get('settings',{}).get('clients',[])];
if not ids or any(x!=u for x in ids): raise SystemExit('FATAL: UUID invariant failed')
for i,line in enumerate(sub,1):
    m=re.match(r'vless://([^@]+)@([^:/?#]+):([0-9]+)\?(.*)',line)
    if not m or m.group(1)!=u: raise SystemExit(f'FATAL: node {i} syntax/UUID mismatch')
    host,port,q=m.group(2),m.group(3),m.group(4)
    if i==1 and (host!=public or port!='443'): raise SystemExit('FATAL: node1 Railway Generate Domain mismatch')
    if not bootstrap and i in (2,3) and (host!=tcp_host or port!=tcp_port): raise SystemExit(f'FATAL: node{i} Railway TCP endpoint mismatch')
    if not bootstrap and i==2 and 'sni=www.cloudflare.com' not in q: raise SystemExit('FATAL: node2 REALITY SNI mismatch')
    if not bootstrap and i==3 and 'sni=www.apple.com' not in q: raise SystemExit('FATAL: node3 XHTTP REALITY SNI mismatch')
    if i==4 and (not cf or host!=rt['cloudflare']['public_hostname'] or port!='443'): raise SystemExit('FATAL: node4 Cloudflare endpoint mismatch')
print('TOPOLOGY_INVARIANT=OK');print('UUID_INVARIANT=OK');print('RAILWAY_NETWORKING_INVARIANT='+('BOOTSTRAP_PENDING' if bootstrap else 'OK'));print('SUBSCRIPTION_COUNT='+str(n));print('NODE_ORDER=01:RAILWAY_XHTTP'+('' if bootstrap else ',02:RAW_REALITY,03:XHTTP_REALITY'+(',04:CLOUDFLARE_WS' if cf else '')))
PY
xray run -test -config "$C"; xray run -config "$C" & XP=$!; GP=""; CFP=""
trap 'kill "$XP" "$GP" "$CFP" 2>/dev/null || true; wait "$XP" 2>/dev/null || true; wait "$GP" 2>/dev/null || true; wait "$CFP" 2>/dev/null || true' INT TERM EXIT
waitp(){ p="$1";l="$2";i=0; while ! python3 -c 'import socket,sys;s=socket.create_connection(("127.0.0.1",int(sys.argv[1])),1);s.close()' "$p" 2>/dev/null; do kill -0 "$XP" 2>/dev/null || exit 1; i=$((i+1)); [ "$i" -lt "${READY_TIMEOUT:-120}" ] || { echo "FATAL: readiness timeout $l:$p" >&2; exit 1; }; sleep 1; done; echo "READY_CHECK=$l:$p"; }
for spec in $(python3 - "$R" <<'PY'
import json,sys
r=json.load(open(sys.argv[1]))
for name,node in r['routes'].items(): print(f'{name}:{node["port"]}')
PY
); do waitp "${spec#*:}" "${spec%:*}"; done
CF=$(python3 - "$R" <<'PY'
import json,sys;print('1' if json.load(open(sys.argv[1]))['cloudflare']['enabled'] else '0')
PY
)
python3 /opt/xray/scripts/gateway.py & GP=$!; waitp "$APP_PORT" gateway
if [ "$CF" = 1 ]; then CFPPORT=$(python3 - "$R" <<'PY'
import json,sys;print(json.load(open(sys.argv[1]))['cloudflare']['ws_port'])
PY
); secret "$D/cloudflare_tunnel_token.txt" "$CF_TOKEN"; cloudflared --no-autoupdate tunnel --metrics 127.0.0.1:2000 run --token-file "$D/cloudflare_tunnel_token.txt" >"$D/cloudflared.log" 2>&1 & CFP=$!; sleep 1; kill -0 "$CFP" 2>/dev/null || { tail -n 80 "$D/cloudflared.log" >&2 || true; exit 1; }; fi
printf 'https://%s/sub/%s\n' "$PUBLIC" "$TOKEN">"$D/subscription_url.txt";chmod 600 "$D/subscription_url.txt"
N=$(python3 - "$R" <<'PY'
import json,sys;print(json.load(open(sys.argv[1]))['nodes']['count'])
PY
)
echo "SOURCE_REPOSITORY=gooidtto/way-v70";echo "SOURCE_BRANCH=main";echo "RELEASE=$BUILD_ID";echo "SOURCE_BUILD=$SOURCE_BUILD";echo "RAILWAY_CURRENT_PUBLIC=$PUBLIC";echo "RAILWAY_CURRENT_TCP=${TCP_HOST:-pending}:${TCP_PORT:-pending}";echo "RAILWAY_CURRENT_APP_PORT=$APP_PORT";echo "TOPOLOGY=$N";echo "NODE4_ENABLED=$( [ "$CF" = 1 ] && echo true || echo false )";echo "CLOUDFLARE=$( [ "$CF" = 1 ] && echo enabled || echo disabled )";echo "SUBSCRIPTION_COUNT=$N";echo "TOPOLOGY_INVARIANT=OK";echo "RAILWAY_NETWORKING_SOURCE=current-deployment-environment";echo "NODE_ORDER=01:RAILWAY_XHTTP$( [ "$BOOTSTRAP" = 1 ] && echo '' || echo ',02:RAW_REALITY,03:XHTTP_REALITY'$( [ "$CF" = 1 ] && echo ',04:CLOUDFLARE_WS' || true ) )"
while kill -0 "$XP" 2>/dev/null && kill -0 "$GP" 2>/dev/null; do if [ "$CF" = 1 ]; then kill -0 "$CFP" 2>/dev/null || exit 1; fi; sleep 5; done
exit 1