# Railway Xray Gateway — way-v70

Single deployment path on `main`.

## Runtime source of truth

The running Railway environment is authoritative for:

- `RAILWAY_PUBLIC_DOMAIN`
- `RAILWAY_TCP_PROXY_DOMAIN`
- `RAILWAY_TCP_PROXY_PORT`
- `RAILWAY_TCP_APPLICATION_PORT`

The subscription is generated from those live values on every startup. Persisted state never overrides the current Railway endpoint. No Railway hostname or TCP proxy port is committed to the repository.

## Bootstrap and topology

First deployment may have a Generate Domain before Railway has provisioned the TCP Proxy. In that state the service boots in `node01-only` bootstrap mode and does not invent Node 02/03 endpoints.

Once the current Railway TCP Proxy Domain, TCP Proxy Port, and TCP Application Port are available, the next startup generates exactly three nodes:

1. Railway Public Domain → XHTTP TLS → `10086`
2. Railway TCP Proxy (live Domain + live Port) → REALITY Vision, SNI `www.cloudflare.com` → `10087`
3. Railway TCP Proxy (live Domain + live Port) → XHTTP REALITY, SNI `www.apple.com` → `10088`

Node 4 exists only when all six Cloudflare variables are present and valid:

`CLOUDFLARE_TUNNEL_TOKEN`, `CLOUDFLARE_TUNNEL_ID`, `CLOUDFLARE_PUBLIC_HOSTNAME`, `CLOUDFLARE_ORIGIN_SERVICE`, `WS_PORT`, `WS_PATH`.

Otherwise the subscription is exactly three nodes.

## Single startup path

```text
Dockerfile → guard.sh → start.sh → generate.py → Xray + gateway.py
```

No alternate startup or gateway implementation is used.

## Deployment identity

The image contains `BUILD_VERSION` and prints it at build/runtime so the deployed image can be distinguished from an older cached image. A valid deployment should show:

```text
SOURCE_REPOSITORY=gooidtto/way-v70
SOURCE_BRANCH=main
SOURCE_BUILD=way-v70-standard-core
BUILD_MARKER=way-v70-standard-core source-of-truth=main railway-networking=runtime-only node-topology=3-or-4
```

The deployment UUID is persistent in `/data/uuid.txt`; REALITY keys and subscription token are also persistent.
