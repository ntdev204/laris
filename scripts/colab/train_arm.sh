#!/usr/bin/env bash
# One arm of the T204 comparison on the A100 VM (T204). OWNER RUN unless the owner has said otherwise: it trains.
# Usage: LARIS_TRAINING_AUTHORIZED=1 bash scripts/colab/train_arm.sh stage2|control|long
# `long` (T216) continues english-r1-stage2/best for 15,000 steps with english_r1_stage2_long.yaml, evaluation and saving every 1,000 steps.
# Both arms start from the clean stage-1 checkpoint of T212 (`--init-from`, fresh optimizer), use micro-batch 32 x
# accumulation 1, 2 tasks per micro-step, 5,000 steps and the same warm-up, learning rate, seed and evaluation schedule;
# they differ only in the config (mixture, tasks, heads). The log goes to artifacts/profiles/<run>.log.
set -euo pipefail
arm="${1:?usage: train_arm.sh stage2|control|long}"
init=artifacts/checkpoints/language_encoder/english-r1-stage1-rerun/best
steps=5000; every=500
case "$arm" in
  stage2)  cfg=configs/language_encoder/english_r1_stage2.yaml;         run=english-r1-stage2 ;;
  control) cfg=configs/language_encoder/english_r1_stage2_control.yaml; run=english-r1-control ;;
  long)    cfg=configs/language_encoder/english_r1_stage2_long.yaml;    run=english-r1-stage2-long
           init=artifacts/checkpoints/language_encoder/english-r1-stage2/best; steps=15000; every=1000 ;;
  *) echo "[ERROR] arm must be stage2, control or long" >&2; exit 2 ;;
esac
cd "$(dirname "$0")/../.."
[ "${LARIS_TRAINING_AUTHORIZED:-}" = 1 ] || { echo "[ERROR] set LARIS_TRAINING_AUTHORIZED=1 (owner)" >&2; exit 3; }
[ -f "$init/model.pt" ] || { echo "[ERROR] $init missing: copy it from Drive runs/english-r1-stage1-rerun/best" >&2; exit 4; }
[ -f /content/COMMIT ] && export LARIS_GIT_COMMIT="$(cat /content/COMMIT)"
export LARIS_VRAM_CEILING_GB="${LARIS_VRAM_CEILING_GB:-36}"
tok=artifacts/tokenizer/english-r1-56k-nd/laris_spm_en_56k_nd.model
mkdir -p artifacts/profiles
echo "arm $arm run $run commit ${LARIS_GIT_COMMIT:-unknown} init $init"
exec python3 -m cli.model train language-encoder --authorized --model-size large --vocab-size 56000 \
  --max-seq-len 1024 --training-config "$cfg" --dataset-sampling-ablation --init-from "$init" \
  --tasks-per-step 2 --micro-batch-size 32 --grad-accum-steps 1 --steps "$steps" \
  --eval-interval "$every" --eval-batches 16 --save-interval "$every" --patience 4 --seed 42 \
  --precision bf16 --no-8bit-adam --tokenizer-model "$tok" --normalize-input --no-evaluate-after \
  --run-id "$run" > "artifacts/profiles/$run.log" 2>&1
