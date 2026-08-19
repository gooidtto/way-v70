# Railway Xray Gateway — way-v70

Single deployment path on `main`.

## Runtime source of truth

The running Railway environment is authoritative for:

- `RAILWAY_PUBLIC_DOMAIN`
- `RAILWAY_TCP_PROXY_DOMAIN`
- `RAILWAY_TCP_PROXY_PORT`
- `RAILWAY_TCP_APPLICATION_PORT`

The subscription is generated from those live values on every startup. Persisted state never overrides the current Railway endpoint.

## Topology

Base deployment is exactly three nodes:

1. Railway Public Domain → XHTTP TLS → `10086`
2. Railway TCP Proxy → REALITY Vision, SNI `www.cloudflare.com` → `10087`
3. Railway TCP Proxy → XHTTP REALITY, SNI `www.apple.com` → `10088`

Node 4 exists only when all six Cloudflare variables are present and valid:

`CLOUDFLARE_TUNNEL_TOKEN`, `CLOUDFLARE_TUNNEL_ID`, `CLOUDFLARE_PUBLIC_HOSTNAME`, `CLOUDFLARE_ORIGIN_SERVICE`, `WS_PORT`, `WS_PATH`.

Otherwise the subscription is exactly three nodes.

## Single startup path

```text
Dockerfile → guard.sh → start.sh → generate.py → Xray + gateway.py
```

No alternate startup or gateway implementation is used.

## Deployment identity

The container prints:

```text
SOURCE_REPOSITORY=gooidtto/way-v70
SOURCE_BRANCH=main
SOURCE_BUILD=way-v70-standard-core
```

The deployment UUID is persistent in `/data/uuid.txt`; REALITY keys and subscription token are also persistent.
