#!/usr/bin/env bash
# Copy a finished run (checkpoints and log) from the VM to Drive and force the write (T204). Run ON THE VM.
# Usage: bash scripts/colab/save_run.sh english-r1-stage2   (Drive must be mounted)
# Do not stop the session before it prints SAVE_DONE: an earlier copy was lost when the session ended before Drive flushed.
set -euo pipefail
run="${1:?usage: save_run.sh RUN_ID}"
cd "$(dirname "$0")/../.."
dst="/content/drive/MyDrive/laris/runs/$run"
[ -d /content/drive/MyDrive/laris ] || { echo "[ERROR] Drive is not mounted (colab drivemount)" >&2; exit 1; }
mkdir -p "$dst"
rsync -a "artifacts/checkpoints/language_encoder/$run/" "$dst/"
cp "artifacts/profiles/$run.log" "$dst/"
python3 - "$dst" <<'PY'
import os, sys
for root, _, names in os.walk(sys.argv[1]):
    for name in names:
        fd = os.open(os.path.join(root, name), os.O_RDWR)
        os.fsync(fd)
        os.close(fd)
print("fsync done")
PY
sync -f /content/drive
find "$dst" -type f -printf "%s %P\n"
echo SAVE_DONE
