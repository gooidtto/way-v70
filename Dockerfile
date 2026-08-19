# syntax=docker/dockerfile:1
ARG XRAY_VERSION=26.3.27
ARG CLOUDFLARED_VERSION=2026.7.3
FROM ghcr.io/xtls/xray-core:${XRAY_VERSION} AS xray
FROM cloudflare/cloudflared:${CLOUDFLARED_VERSION} AS cloudflared
FROM python:3.12-alpine3.22
ARG XRAY_VERSION
ARG CLOUDFLARED_VERSION
ENV XRAY_VERSION=${XRAY_VERSION} CLOUDFLARED_VERSION=${CLOUDFLARED_VERSION} PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN apk add --no-cache openssl ca-certificates && mkdir -p /etc/xray /data /opt/xray/scripts /opt/xray/site
COPY --from=xray /usr/local/bin/xray /usr/local/bin/xray
COPY --from=cloudflared /usr/local/bin/cloudflared /usr/local/bin/cloudflared
COPY scripts/ /opt/xray/scripts/
COPY site/ /opt/xray/site/
RUN chmod 0755 /usr/local/bin/xray /usr/local/bin/cloudflared /opt/xray/scripts/*.sh /opt/xray/scripts/*.py && chmod 0644 /opt/xray/site/*
ENV BUILD_ID=way-v70-standard-core \
    SOURCE_BUILD=way-v70-standard-core \
    XRAY_CONFIG=/etc/xray/config.json \
    DATA_DIR=/data \
    REALITY_RAW_SNI=www.cloudflare.com \
    REALITY_RAW_TARGET=www.cloudflare.com:443 \
    REALITY_FINGERPRINT=chrome \
    REALITY_XHTTP_SNI=www.apple.com \
    REALITY_XHTTP_TARGET=www.apple.com:443 \
    XHTTP_PATH=/xhttp \
    READY_TIMEOUT=120 \
    GATEWAY_MAX_CONNECTIONS=512 \
    GATEWAY_READ_TIMEOUT=20 \
    GATEWAY_UPSTREAM_TIMEOUT=15 \
    GATEWAY_IDLE_TIMEOUT=900 \
    GATEWAY_MAX_INITIAL=131072 \
    GATEWAY_LOGLEVEL=WARNING
RUN echo "SOURCE_BUILD=${SOURCE_BUILD} BUILD_ID=${BUILD_ID}" && sha256sum /opt/xray/scripts/generate.py /opt/xray/scripts/start.sh /opt/xray/scripts/gateway.py
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=5 CMD-SHELL python3 -c "import os,urllib.request; p=os.environ.get('RAILWAY_TCP_APPLICATION_PORT') or os.environ.get('GATEWAY_PORT'); urllib.request.urlopen('http://127.0.0.1:'+p+'/ready', timeout=8).read()" || exit 1
WORKDIR /opt/xray
ENTRYPOINT ["/opt/xray/scripts/guard.sh"]
