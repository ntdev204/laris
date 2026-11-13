#!/bin/sh
# End-to-end smoke test of the server stack from a clean client: empty folder, fresh HOME, login,
# chat with the placeholder model, dense search through the server.
#   docker/smoke_test.sh [--cpu] [--keep]
# --cpu   no GPU: adds docker/compose.cpu.yaml (the model service runs on CPU, placeholder backend)
# --keep  leave the stack running afterwards (default: remove it and its volumes)
# Needs: docker compose, openssl, python3, and the `laris` command (LARIS_BIN, default laris).
set -eu
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/.." && pwd)
files="-f $here/compose.yaml"
keep=no
for arg in "$@"; do
    case "$arg" in
        --cpu) files="$files -f $here/compose.cpu.yaml" ;;
        --keep) keep=yes ;;
        *) echo "unknown option $arg" >&2; exit 2 ;;
    esac
done
compose="docker compose $files"
export LARIS_HTTP_PORT=${LARIS_HTTP_PORT:-18080} LARIS_HTTPS_PORT=${LARIS_HTTPS_PORT:-18443}
export LARIS_DOMAIN=localhost
bin=${LARIS_BIN:-laris}
work=$(mktemp -d)
cleanup() {
    [ "$keep" = yes ] || $compose down -v >/dev/null 2>&1 || true
    rm -rf "$work"
}
trap cleanup EXIT
step() { printf '\n== %s\n' "$*"; }
fail() { echo "SMOKE TEST FAILED: $*" >&2; exit 1; }

step "stack up"
"$here/init-secrets.sh" >/dev/null
$compose up -d --build --wait --wait-timeout 300 || fail "the stack did not become healthy"

step "a key for the test user"
created=$($compose exec -T api laris-server keys create --label smoke --role user --tokens 1000000)
key=$(printf '%s\n' "$created" | sed -n 's/^API key (shown once, give it to the user): //p')
[ -n "$key" ] || fail "no key was created"

step "the certificate authority Caddy publishes"
# the authority, not the server certificate: Caddy renews that one every few hours
fingerprint=""
n=0
while [ -z "$fingerprint" ] && [ $n -lt 30 ]; do
    fingerprint=$(curl -sk "https://localhost:$LARIS_HTTPS_PORT/.well-known/laris/ca.crt" 2>/dev/null \
        | openssl x509 -noout -fingerprint -sha256 2>/dev/null | sed 's/^.*=//' || true)
    [ -n "$fingerprint" ] || { n=$((n + 1)); sleep 1; }
done
[ -n "$fingerprint" ] || fail "no certificate authority on port $LARIS_HTTPS_PORT"
echo "SHA256:$fingerprint"

step "a clean client: empty folder, fresh home"
mkdir "$work/home" "$work/project"
cd "$work/project"
export HOME="$work/home"
unset LARIS_API_KEY LARIS_SERVER_KEYS
server="https://localhost:$LARIS_HTTPS_PORT/v1"
printf '%s\n' "$key" | $bin login --server "$server" --trust-fingerprint "SHA256:$fingerprint" \
    || fail "login"
$bin whoami || fail "whoami"

step "chat with the placeholder model"
answer=$($bin -p "Xin chào, bạn là ai?") || fail "chat"
[ -n "$answer" ] || fail "empty chat answer"
printf '%s\n' "$answer" | head -5

step "keyword search over a document (runs locally)"
printf 'Perovskite solar cells reach high efficiency.\n\nGraphene conducts electricity.\n' > notes.txt
$bin app ingest notes.txt >/dev/null || fail "ingest"
hits=$($bin app search --query "solar efficiency" --mode bm25) || fail "keyword search"
printf '%s\n' "$hits" | grep -qi "perovskite" || fail "keyword search did not return the passage"

step "dense search through the server"
if [ -n "${LARIS_MODEL_CHECKPOINT:-}" ]; then
    $bin app index || fail "dense index (the server must answer /v1/laris/embed)"
    hits=$($bin app search --query "solar efficiency" --mode dense) || fail "dense search"
    printf '%s\n' "$hits" | grep -qi "perovskite" || fail "dense search did not return the passage"
else
    # No encoder checkpoint exists yet (the foundation model is not trained or qualified), so the
    # server must say so plainly instead of inventing vectors.
    out=$($bin app index 2>&1 || true)
    printf '%s\n' "$out" | grep -qi "no embedding model" \
        || fail "without a checkpoint the server should answer 'no embedding model loaded', got: $out"
    echo "SKIPPED dense search: no LARIS_MODEL_CHECKPOINT (the server refused clearly: no embedding model)"
fi

step "the API refuses an unknown key"
code=$(curl -ks -o /dev/null -w '%{http_code}' -H "Authorization: Bearer wrong-key" \
    -H "X-Laris-Protocol: 1" "$server/laris/account")
[ "$code" = 401 ] || fail "expected 401 for a wrong key, got $code"
echo "401 as expected"

echo
echo "SMOKE TEST PASSED"
