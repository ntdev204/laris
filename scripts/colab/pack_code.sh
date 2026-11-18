#!/usr/bin/env bash
# Pack the tracked code and the tokenizer for a Colab run (T210). Run on the owner's machine.
# Usage: scripts/colab/pack_code.sh [OUT_DIR]   (default: artifacts/colab)
# Writes OUT_DIR/laris-code.tar.gz (git archive of HEAD: tracked files only, no data, no weights)
# and OUT_DIR/laris-tokenizer.tar.gz (the 56k tokenizer, 3 MB). Nothing is uploaded here.
set -euo pipefail
cd "$(dirname "$0")/../.."
out="${1:-artifacts/colab}"
mkdir -p "$out"
git diff --quiet HEAD -- || { echo "[ERROR] uncommitted tracked changes: commit first, the run records the commit" >&2; exit 1; }
git archive --format=tar.gz --prefix=laris/ -o "$out/laris-code.tar.gz" HEAD
tar -czf "$out/laris-tokenizer.tar.gz" artifacts/tokenizer/english-r1-56k-nd
git rev-parse HEAD > "$out/COMMIT"
ls -l "$out"; echo "commit $(cat "$out/COMMIT")"
