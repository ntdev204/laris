#!/bin/sh
# Smoke test of the whole stack through Caddy, with curl only (the client is not needed):
# build, start, health, an admin key, a user key, one chat answer, an account, one trace, and
# the rule that only Caddy publishes ports.
#   docker/smoke_test.sh [--keep]
# --keep leaves the stack running (default: remove the smoke project and its own volumes; the trial
# server's project `laris` and its `caddy_data` are never touched).
# Env: LARIS_HTTPS_PORT (default 28443), LARIS_HTTP_PORT (28080), LARIS_MODELS_DIR as in compose.yaml.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
# a separate project: its own containers, network and volumes, so a running trial server is never touched
project=${LARIS_SMOKE_PROJECT:-laris-smoke}
compose="docker compose -p $project -f $here/compose.yaml"
keep=no
[ "${1:-}" = "--keep" ] && keep=yes
export LARIS_HTTP_PORT=${LARIS_HTTP_PORT:-28080} LARIS_HTTPS_PORT=${LARIS_HTTPS_PORT:-28443}
export LARIS_DOMAIN=${LARIS_DOMAIN:-localhost}
export LARIS_EDGE_SUBNET=${LARIS_EDGE_SUBNET:-172.31.41.0/24} LARIS_EDGE_GATEWAY=${LARIS_EDGE_GATEWAY:-172.31.41.1}
export LARIS_SUBNET=${LARIS_SUBNET:-172.31.40.0/24}   # must not overlap the trial network
base="https://localhost:$LARIS_HTTPS_PORT"
work=$(mktemp -d)
cleanup() { [ "$keep" = yes ] || $compose down -v >/dev/null 2>&1 || true; rm -rf "$work"; }
trap cleanup EXIT
step() { printf '\n== %s\n' "$*"; }
fail() { echo "SMOKE TEST FAILED: $*" >&2; exit 1; }
api() { curl -sk --max-time 60 "$@"; }

step "stack up"
"$here/init-secrets.sh" >/dev/null
$compose up -d --build --wait --wait-timeout 600 || fail "the stack did not become healthy"

step "only Caddy publishes ports"
published=$(docker ps --filter "label=com.docker.compose.project=$project" \
    --format '{{.Label "com.docker.compose.service"}} {{.Ports}}' | grep -- '->' | awk '{print $1}' | sort -u | tr '\n' ' ')
[ "$published" = "caddy " ] || fail "services publishing ports: $published"

step "health through Caddy"
api "$base/health" | grep -q '"ok"' || fail "/health"

step "the first admin key (written to the state volume on the first start)"
$compose cp server:/state/first_admin_key "$work/admin_key" >/dev/null 2>&1 || fail "no first admin key"
admin=$(tr -d '\n' < "$work/admin_key")
[ -n "$admin" ] || fail "empty admin key"

step "a user key"
created=$(api -X POST "$base/v1/admin/keys" -H "Authorization: Bearer $admin" -H 'X-Laris-Protocol: 2' -H 'Content-Type: application/json' \
    -d '{"label":"smoke","role":"user","token_limit":1000000}') || fail "key request"
key=$(printf '%s' "$created" | sed -n 's/.*"key":"\([^"]*\)".*/\1/p')
[ -n "$key" ] || fail "no key in the answer: $(printf %s "$created" | cut -c1-200)"

step "a chat answer from the placeholder model"
answer=$(api -X POST "$base/v1/laris/chat" -H "Authorization: Bearer $key" -H 'X-Laris-Protocol: 2' -H 'Content-Type: application/json' \
    -d '{"stream":true,"messages":[{"role":"user","content":"Hello, who are you?"}]}') || fail "chat"
printf %s "$answer" | grep -q '"error"' && fail "chat answered with an error: $(printf %s "$answer" | cut -c1-200)"
printf %s "$answer" | grep -q "data:" || fail "no streamed answer"
printf '%s\n' "$answer" | cut -c1-200

step "the account and a trace without content"
api "$base/v1/laris/account" -H "X-Laris-Protocol: 2" -H "Authorization: Bearer $key" | grep -q 'user' || fail "account"
traces=$(api "$base/v1/admin/traces" -H "X-Laris-Protocol: 2" -H "Authorization: Bearer $admin") || fail "traces"
printf '%s' "$traces" | grep -q 'chat' || fail "no chat trace"
printf '%s' "$traces" | grep -qi 'who are you' && fail "a trace holds message text"

step "the policy is read-only in the container"
$compose run --rm --no-deps --entrypoint /usr/local/bin/laris-server server policy verify >/dev/null 2>&1 \
    || fail "policy verify"
echo "smoke test passed (placeholder backend: mechanics only, no capability shown)"
