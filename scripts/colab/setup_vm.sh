#!/usr/bin/env bash
# Prepare a Colab VM for a LARIS run (T210). Run ON THE VM, after the two archives are uploaded to /content.
# Usage: bash /content/setup_vm.sh
# Unpacks the code and tokenizer to /content/laris, installs the project with its `training` extra
# (the dependencies already declared in pyproject.toml; no new package), and prints the environment.
set -euo pipefail
cd /content
[ -f laris-code.tar.gz ] && [ -f laris-tokenizer.tar.gz ] || { echo "[ERROR] upload laris-code.tar.gz and laris-tokenizer.tar.gz to /content first" >&2; exit 1; }
tar -xzf laris-code.tar.gz
cd laris
tar -xzf ../laris-tokenizer.tar.gz
pip install -q -e '.[training]'
mkdir -p data/processed artifacts/checkpoints/language_encoder artifacts/profiles
python3 - <<'PY'
import sys, torch, sentencepiece, pyarrow
print("python", sys.version.split()[0], "| torch", torch.__version__, "| cuda", torch.version.cuda,
      "| bf16", torch.cuda.is_bf16_supported(), "| gpu", torch.cuda.get_device_name(0))
print("sentencepiece", sentencepiece.__version__, "| pyarrow", pyarrow.__version__)
PY
echo "[OK] now copy the data: bash scripts/colab/sync_data.sh"
