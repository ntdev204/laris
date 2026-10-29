---
document_id: "DOC-DEV-CLI-001"
title: "LARIS Command-Line Interface Reference"
document_type: "specification"
status: "APPROVED"
version: "1.0.0"
created_at: "2026-10-29"
updated_at: "2026-10-29"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/specifications/LANGUAGE_ENCODER_TRAINING_SPECIFICATION.md"
  - "docs/specifications/DATASET_SPECIFICATION.md"
  - "docs/adr/ADR-013-functional-package-layout-and-cli.md"
decision_references:
  - "ADR-013"
change_summary: "Reference for the laris command-line interface, including the server runbook."
---

# LARIS Command-Line Interface Reference

The `laris` entry point (`src/laris/cli/main.py`) exposes one module per command under `src/laris/cli/commands/`. Each module defines `add_arguments(parser)` and `run(args)`. Scripts under `scripts/` are thin wrappers over the same functions. Run `laris <group> <command> --help` for the full option list.

## Commands

| Command | Purpose | Authorization |
| :--- | :--- | :--- |
| `laris data acquire [--only IDS] [--cc100-max-docs N]` | Download and verify datasets; `--only` merges into the existing manifest. Resumable. | none |
| `laris data check [--verify-sha256]` | Verify manifest files, per-task train/val/test coverage and `sentencepiece` before any training step. Exit 0 ready, 1 not ready. | none |
| `laris data partition [--datasets ...] [--num-workers N] [--include-unreviewed-licenses]` | Leakage-safe train/val/test partitioning. Datasets with `NEEDS_LICENSE_REVIEW` are skipped by default. A subset run merges into the existing manifest by `dataset_id`. | none |
| `laris train tokenizer [--extract-only] [--authorized]` | Extract train-only text and fit the SentencePiece 32k BPE tokenizer. | `--authorized` |
| `laris train language-encoder --model-size {compact,large} [--profile-only] --tokenizer-model FILE` | `--profile-only` measures real GPU memory on real tokenized train batches (forward only; with training authorized, backward plus a real optimizer step on a discarded model). Otherwise trains, validates, checkpoints and evaluates the encoder. | training needs `--authorized` and `LARIS_TRAINING_AUTHORIZED=1` |
| `laris evaluate language-encoder --checkpoint DIR --tokenizer-model FILE [--split val\|test]` | Score a checkpoint against baselines and thresholds. Exit codes: 0 passed, 1 below threshold, 2 usage or integrity error. | none |
| `laris evaluate calibrate --reports VAL_REPORT...` | Ratchet `configs/evaluation/language_encoder.yaml` up from passing `val` reports; never lowers, refuses `test` reports. | none |
| `laris infer {nli,...} --checkpoint DIR --tokenizer-model FILE` | Run a single prediction from a checkpoint. | none |

## Server Runbook

Run from the repository root with the virtual environment active. Steps 1-5 train nothing. Step 5b and steps 6-8 are frozen until the owner sets `LARIS_TRAINING_AUTHORIZED=1` ([ADR-008](../adr/ADR-008-evaluation-before-capability-claims.md)).

```bash
# 1. Environment (adds sentencepiece, torch, bitsandbytes)
pip install -e '.[training,dev]'
bash scripts/verify_target_server.sh

# 2. Data: acquire (resumable), then partition ALL datasets in one run
laris data acquire
laris data partition --num-workers 14

# 3. Gate: every task needs train, val and test; exit 0 means ready
laris data check --verify-sha256

# 4. Tokenizer text extraction (no fitting), then fitting
laris train tokenizer --extract-only
export LARIS_TOKENIZER_TRAINING_AUTHORIZED=1
laris train tokenizer --authorized

# 5. Measured GPU memory: real model, real tokenized train batches (needs the step 4 tokenizer).
#    Forward only, no authorization needed. Prints [PARTIAL]: training memory is NOT certified.
laris train language-encoder --model-size large --profile-only \
  --tokenizer-model artifacts/tokenizer/laris_spm_32k.model

# 5b. Steady-state training peak: forward, backward and a real optimizer step on the randomly
#     initialised model (discarded, nothing saved), then a second measured window with the
#     optimizer state resident. Gradients and the optimizer step count as training, so the
#     owner must set the variable. Exit 0 only if the peak is within 14.5 GB; otherwise lower
#     --micro-batch-size and raise --grad-accum-steps.
LARIS_TRAINING_AUTHORIZED=1 laris train language-encoder --model-size large --profile-only \
  --tokenizer-model artifacts/tokenizer/laris_spm_32k.model

# 6. Training (owner authorization required)
export LARIS_TRAINING_AUTHORIZED=1
laris train language-encoder --model-size large --authorized --no-evaluate-after \
  --tokenizer-model artifacts/tokenizer/laris_spm_32k.model --run-id <run-id>

# 7. Validate on val, then ratchet the thresholds
RUN=artifacts/checkpoints/language_encoder/<run-id>
laris evaluate language-encoder --checkpoint $RUN/best --split val \
  --tokenizer-model artifacts/tokenizer/laris_spm_32k.model --output $RUN/evaluation-val.json
laris evaluate calibrate --reports $RUN/evaluation-val.json --output configs/evaluation/language_encoder.yaml

# 8. Test split: score once, after the thresholds are final
laris evaluate language-encoder --checkpoint $RUN/best --split test \
  --tokenizer-model artifacts/tokenizer/laris_spm_32k.model --output $RUN/evaluation-test.json
```

Notes:

- `laris data partition --datasets ...` merges into the existing manifest, but the first run must cover every dataset. A dataset missing from `data/processed` silently drops out of its task; `laris data check` is the gate that catches it.
- Pass `--no-evaluate-after` to training: the default scores the `test` split immediately, before thresholds are calibrated on `val`.
- Add `--tokenizer-model` and `--data-dir` to `infer` and `evaluate` calls when the defaults differ.
- Resume an interrupted run with `--resume <run-dir>/last`; keep the same `--run-id`.

Checkpoints are written atomically to `artifacts/checkpoints/language_encoder/<run-id>/{best,last}` with a provenance manifest and SHA-256. Resume with `--resume <run-id>/last`.
