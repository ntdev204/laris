#!/bin/sh
# Proves the built images hold no policy, no weights and no secrets (SR-S8). Needs the images (compose build).
#   docker/verify-images.sh
set -eu
fail() { echo "IMAGE CHECK FAILED: $*" >&2; exit 1; }
tag=${LARIS_TAG:-dev}
for image in laris-server:$tag laris-model:$tag; do
    docker image inspect "$image" >/dev/null 2>&1 || fail "$image is not built"
    id=$(docker create "$image")
    files=$(docker export "$id" | tar -t)
    docker rm "$id" >/dev/null
    printf '%s\n' "$files" | grep -E '(^|/)\.laris(/|$)|integrity\.toml|policy\.toml|LARIS\.md' \
        && fail "$image holds policy files"
    printf '%s\n' "$files" | grep -Ei '\.(pt|pth|safetensors|ckpt|onnx|gguf)$|tokenizer\.model|/secrets/|master\.secret' \
        && fail "$image holds weights or secrets"
    echo "ok  $image"
done
user=$(docker image inspect "laris-server:$tag" --format '{{.Config.User}}')
[ "$user" = "65532:65532" ] || fail "laris-server does not run as the non-root user ($user)"
user=$(docker image inspect "laris-model:$tag" --format '{{.Config.User}}')
[ "$user" = "10001:10001" ] || fail "laris-model does not run as the non-root user ($user)"
echo "images hold no policy, weights or secrets; both run as non-root"
