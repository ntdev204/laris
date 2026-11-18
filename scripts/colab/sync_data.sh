#!/usr/bin/env bash
# Copy the training data from the mounted Google Drive to the VM disk and verify it (T210). Run ON THE VM.
# Usage: bash scripts/colab/sync_data.sh [DRIVE_DIR]   (default: /content/drive/MyDrive/laris/data/processed)
# Reading parquet straight from Drive is slow and unreliable: always copy to /content first.
# Needs files.sha256 next to the data (written by scripts/colab/data_manifest.py --sha256 on the owner's machine).
set -euo pipefail
src="${1:-/content/drive/MyDrive/laris/data/processed}"
dst=/content/laris/data/processed
[ -d "$src" ] || { echo "[ERROR] $src not found: mount Drive first (colab drivemount /content/drive)" >&2; exit 1; }
mkdir -p "$dst"
rsync -a --info=progress2 --exclude='files.sha256' "$src"/ "$dst"/
cd "$dst"
if [ -f "$src/files.sha256" ]; then
  sha256sum -c --quiet "$src/files.sha256" && echo "[OK] all checksums match"
else
  echo "[WARN] no files.sha256 in $src: copy not verified"
fi
find . -name '*.parquet' | wc -l
du -sh .
