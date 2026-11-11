#!/bin/sh
# Build the client-only wheel that the npm package carries (run by `npm pack` via prepack).
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/.." && pwd)"
out="$here/npm/vendor"
rm -rf "$out"
"$repo/.venv/bin/python" "$here/build_client.py" "$out"
ls "$out"
