#!/usr/bin/env bash
# Speed profile of the training step on a large GPU (T211). OWNER RUN: it performs real forward/backward/optimizer
# steps on a discarded randomly initialised model, so it needs LARIS_TRAINING_AUTHORIZED=1 from the owner. Run ON THE VM.
# Usage: LARIS_TRAINING_AUTHORIZED=1 bash scripts/colab/speed_profile.sh [CONFIG] [TASKS_PER_STEP]
#   CONFIG default: configs/language_encoder/english_r1_stage2.yaml ; TASKS_PER_STEP default: 2
# The large model checkpoints by default (`--no-gradient-checkpointing` turns it off, T211; before that the flag had no effect on it).
# For micro-batch 8, 16, 32 (accumulation 4, 2, 1: effective batch 32 in all) and gradient checkpointing on and off it runs
# `--profile-only` and keeps one log per combination in artifacts/profiles/. Peak and latency are printed at the end of each log.
set -uo pipefail
cd "$(dirname "$0")/../.."
config="${1:-configs/language_encoder/english_r1_stage2.yaml}"
tasks="${2:-2}"
tok=artifacts/tokenizer/english-r1-56k-nd/laris_spm_en_56k_nd.model
export LARIS_VRAM_CEILING_GB="${LARIS_VRAM_CEILING_GB:-36}"
mkdir -p artifacts/profiles
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv | tee artifacts/profiles/speed-gpu.txt
for mb in 8 16 32; do
  acc=$((32 / mb))
  for ckpt in on off; do
    flag=""; [ "$ckpt" = off ] && flag="--no-gradient-checkpointing"
    log="artifacts/profiles/speed-t${tasks}-mb${mb}-ckpt${ckpt}.log"
    echo "== micro-batch $mb, accumulation $acc, checkpointing $ckpt -> $log"
    timeout -s KILL 1500s python3 -m cli.model train language-encoder \
      --profile-only --model-size large --vocab-size 56000 --max-seq-len 1024 \
      --training-config "$config" --tasks-per-step "$tasks" \
      --micro-batch-size "$mb" --grad-accum-steps "$acc" $flag --precision bf16 --no-8bit-adam \
      --tokenizer-model "$tok" --normalize-input > "$log" 2>&1
    echo "exit $?"; grep -E "Worst mixed step|Latency per mixed step|Measured peak|\[SUCCESS\]|\[FAIL\]|out of memory" "$log" | tail -5
  done
done
