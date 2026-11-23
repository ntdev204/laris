#!/usr/bin/env bash
# One command for the whole server (T236):  docker/laris.sh up | down | status | key [label] [tokens]
#   up      starts Caddy, the server, the model service, the vLLM server (Qwen on the GPU, BF16) and PostgreSQL; with Tailscale HTTPS it first
#           gets a public certificate for this machine's tailnet name, so clients need no CA
#   down    stops everything (volumes, keys and the certificate authority are kept)
#   status  what runs, and the address clients use
#   key     makes an admin key (default label "full", 1000000000 tokens) and prints it once
# Settings: set in docker/laris.env (see laris.env.example) or with the defaults below; nothing is written outside docker/tls and the volumes.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
# the settings come from docker/laris.env (git-ignored) or the defaults below, never from variables left in the shell
unset LARIS_PROJECT LARIS_DOMAIN LARIS_HTTP_PORT LARIS_HTTPS_PORT LARIS_EDGE_SUBNET LARIS_EDGE_GATEWAY LARIS_SUBNET \
    LARIS_MODELS_DIR LARIS_CHAT_SNAPSHOT LARIS_SERVER_TOOLS LARIS_GPU_MEMORY_BYTES LARIS_ENGINE_PORT
if [ -f "$here/laris.env" ]; then
    set -a
    # shellcheck disable=SC1091
    . "$here/laris.env"
    set +a
fi
project=${LARIS_PROJECT:-laris-qwen}
export LARIS_HTTP_PORT=${LARIS_HTTP_PORT:-38080} LARIS_HTTPS_PORT=${LARIS_HTTPS_PORT:-38443}
export LARIS_EDGE_SUBNET=${LARIS_EDGE_SUBNET:-172.31.61.0/24} LARIS_EDGE_GATEWAY=${LARIS_EDGE_GATEWAY:-172.31.61.1}
export LARIS_SUBNET=${LARIS_SUBNET:-172.31.60.0/24}
export LARIS_CHAT_MODEL=${LARIS_CHAT_MODEL:-Qwen3.5-4B}
export LARIS_MODELS_DIR=${LARIS_MODELS_DIR:-$HOME/.cache/huggingface/hub}
if [ -z "${LARIS_CHAT_SNAPSHOT:-}" ]; then
    LARIS_CHAT_SNAPSHOT=$(ls "$LARIS_MODELS_DIR/models--Qwen--$LARIS_CHAT_MODEL/snapshots" 2>/dev/null | head -1)
fi
export LARIS_CHAT_SNAPSHOT
# the GPU queue of the model service counts the vLLM server's share of this memory (T282)
if [ -z "${LARIS_GPU_MEMORY_BYTES:-}" ] && command -v nvidia-smi >/dev/null 2>&1; then
    mib=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits -i 0 2>/dev/null | tr -d ' ' || true)
    [ -n "$mib" ] && LARIS_GPU_MEMORY_BYTES=$((mib * 1048576))
fi
export LARIS_GPU_MEMORY_BYTES
compose="docker compose -p $project -f $here/compose.yaml -f $here/compose.chat.yaml"
# the STEM benchmark runner (T275) calls the same vLLM server: LARIS_ENGINE_PORT opens it on 127.0.0.1 only
if [ -n "${LARIS_ENGINE_PORT:-}" ]; then
    compose="$compose -f $here/compose.engine-port.yaml"
fi
# server tools (T273): the server searches and reads for the web client; it alone gets a route out
if [ "${LARIS_SERVER_TOOLS:-false}" = true ]; then
    compose="$compose -f $here/compose.web-tools.yaml"
fi

tailnet_name() {
    command -v tailscale >/dev/null 2>&1 || return 0
    tailscale status --json 2>/dev/null | python3 -c \
        'import json,sys; d=json.load(sys.stdin); print((d.get("CertDomains") or [""])[0])' 2>/dev/null || true
}

domain=${LARIS_DOMAIN:-$(tailnet_name)}
domain=${domain:-localhost}
export LARIS_DOMAIN=$domain
address="https://$domain:$LARIS_HTTPS_PORT"

case "${1:-}" in
up)
    [ -n "$LARIS_CHAT_SNAPSHOT" ] || { echo "no $LARIS_CHAT_MODEL snapshot under $LARIS_MODELS_DIR (set LARIS_MODELS_DIR / LARIS_CHAT_SNAPSHOT)" >&2; exit 1; }
    [ -n "${LARIS_GPU_MEMORY_BYTES:-}" ] || { echo "GPU memory unknown: nvidia-smi failed (set LARIS_GPU_MEMORY_BYTES)" >&2; exit 1; }
    "$here/init-secrets.sh" >/dev/null
    mkdir -p "$here/tls"
    rm -f "$here/tls/tailscale.caddy"
    if [ "$domain" != localhost ] && command -v tailscale >/dev/null 2>&1; then
        if tailscale cert --cert-file "$here/tls/ts.crt" --key-file "$here/tls/ts.key" "$domain" >/dev/null 2>&1; then
            printf 'tls /etc/caddy/tls/ts.crt /etc/caddy/tls/ts.key\n' > "$here/tls/tailscale.caddy"
            echo "certificate for $domain from Tailscale (publicly trusted: clients need no CA)"
        else
            echo "tailscale cert failed: once, run  sudo tailscale set --operator=\$USER  (and enable HTTPS in the tailnet admin)." >&2
            echo "continuing with Caddy's own authority: clients must trust it." >&2
        fi
    fi
    $compose up -d --build --wait --wait-timeout 900
    echo "server up: $address"
    ;;
down)
    export LARIS_CHAT_SNAPSHOT=${LARIS_CHAT_SNAPSHOT:-none} LARIS_GPU_MEMORY_BYTES=${LARIS_GPU_MEMORY_BYTES:-0} # stopping needs no weights
    $compose stop
    echo "server stopped (volumes kept)"
    ;;
status)
    export LARIS_CHAT_SNAPSHOT=${LARIS_CHAT_SNAPSHOT:-none} LARIS_GPU_MEMORY_BYTES=${LARIS_GPU_MEMORY_BYTES:-0}
    $compose ps --format 'table {{.Service}}\t{{.Status}}'
    echo "address: $address"
    ;;
key)
    export LARIS_CHAT_SNAPSHOT=${LARIS_CHAT_SNAPSHOT:-none} LARIS_GPU_MEMORY_BYTES=${LARIS_GPU_MEMORY_BYTES:-0}
    work=$(mktemp -d)
    trap 'rm -rf "$work"' EXIT
    $compose cp server:/state/first_admin_key "$work/admin_key" >/dev/null
    $compose cp caddy:/data/caddy/pki/authorities/local/root.crt "$work/root.crt" >/dev/null 2>&1 || true
    cacert=""
    [ -f "$here/tls/tailscale.caddy" ] || cacert="--cacert $work/root.crt"
    # shellcheck disable=SC2086
    # the built-in admin key works only from this machine: connect through 127.0.0.1, keep the name for TLS
    answer=$(curl -sS --max-time 30 $cacert --resolve "$domain:$LARIS_HTTPS_PORT:127.0.0.1" -X POST "$address/v1/admin/keys" \
        -H "Authorization: Bearer $(tr -d '\n' < "$work/admin_key")" -H 'X-Laris-Protocol: 2' -H 'Content-Type: application/json' \
        -d "{\"label\":\"${2:-full}\",\"role\":\"admin\",\"token_limit\":${3:-1000000000}}" 2>&1) || true
    key=$(printf '%s' "$answer" | sed -n 's/.*"key":"\([^"]*\)".*/\1/p')
    if [ -n "$key" ]; then
        echo "$key"
    else
        echo "no key was made. Server said: $answer" >&2
        echo "address used: $address (start the stack with 'docker/laris.sh up' so that it serves this name)" >&2
        exit 1
    fi
    ;;
*)
    echo "usage: docker/laris.sh up | down | status | key [label] [tokens]" >&2
    exit 2
    ;;
esac
