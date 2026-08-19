# Railway Xray Gateway

This repository uses `railway-four-node-standard` as the core implementation and keeps one deployment path only.

## Deployment source of truth

Railway's live Public Networking values are authoritative at runtime:

- `RAILWAY_PUBLIC_DOMAIN`
- `RAILWAY_TCP_PROXY_DOMAIN`
- `RAILWAY_TCP_PROXY_PORT`

The repository does not reuse a persisted domain or TCP port as the current public endpoint. `start.sh` passes the live Railway values to `generate.py`, and the subscription is generated from those values.

## Topology

Base deployment:

1. Railway Public Domain → XHTTP TLS → `10086`
2. Railway TCP Proxy → REALITY Vision / `www.cloudflare.com` → `10087`
3. Railway TCP Proxy → XHTTP REALITY / `www.apple.com` → `10088`

Optional Cloudflare configuration adds node 4:

4. Cloudflare Tunnel → WS → configured `WS_PORT`

Cloudflare node 4 is enabled only when the complete Cloudflare configuration is present.

## Single startup path

```text
Dockerfile
  ↓
guard.sh
  ↓
start.sh
  ↓
generate.py
  ↓
Xray + gateway.py
  ↓
/ready
```

There is no `start-v2.sh`, `gateway-v2.py`, or separate runtime-manifest startup authority.

## Runtime identity

The deployment UUID is generated for the current deployment. REALITY keys and the subscription token remain persistent in `/data`.

## Railway deployment

Connect this repository directly to Railway and deploy the `main` branch. The container prints the source repository and branch at startup so the deployed build can be identified from logs.

Expected startup markers:

```text
SOURCE_REPOSITORY=gooidtto/railway-v60-four-node
SOURCE_BRANCH=main
SOURCE_BUILD=railway-four-node-standard-core
RELEASE=standard-core-runtime-networking
RAILWAY_NETWORKING_SOURCE=current-deployment-environment
```

The application does not hard-code the Railway project name, service ID, Public Domain, or TCP Proxy endpoint.
