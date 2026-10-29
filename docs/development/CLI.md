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
change_summary: "Initial reference for the laris command-line interface."
---

# LARIS Command-Line Interface Reference

The `laris` entry point (`src/laris/cli/main.py`) exposes one module per command under `src/laris/cli/commands/`. Each module defines `add_arguments(parser)` and `run(args)`. Scripts under `scripts/` are thin wrappers over the same functions. Run `laris <group> <command> --help` for the full option list.

## Commands

| Command | Purpose | Authorization |
| :--- | :--- | :--- |
| `laris data acquire [--only IDS] [--cc100-max-docs N]` | Download and verify datasets; `--only` merges into the existing manifest. Resumable. | none |
| `laris data partition [--datasets ...] [--num-workers N] [--include-unreviewed-licenses]` | Leakage-safe train/val/test partitioning. Datasets with `NEEDS_LICENSE_REVIEW` are skipped by default. | none |
| `laris train tokenizer [--extract-only] [--authorized]` | Extract train-only text and fit the SentencePiece 32k BPE tokenizer. | `--authorized` |
| `laris train language-encoder --model-size {compact,large} [--profile-only]` | Profile VRAM, or train, validate, checkpoint and evaluate the encoder. | `--authorized` and `LARIS_TRAINING_AUTHORIZED=1` |
| `laris evaluate language-encoder --checkpoint DIR --tokenizer-model FILE [--split val\|test]` | Score a checkpoint against baselines and thresholds. Exit codes: 0 passed, 1 below threshold, 2 usage or integrity error. | none |
| `laris evaluate calibrate --reports VAL_REPORT...` | Ratchet `configs/evaluation/language_encoder.yaml` up from passing `val` reports; never lowers, refuses `test` reports. | none |
| `laris infer {nli,...} --checkpoint DIR --tokenizer-model FILE` | Run a single prediction from a checkpoint. | none |

## Typical Sequence

```bash
laris data acquire
laris data partition --num-workers 14
laris train tokenizer --authorized
laris train language-encoder --model-size large --profile-only
export LARIS_TRAINING_AUTHORIZED=1
laris train language-encoder --model-size large --authorized \
  --tokenizer-model artifacts/tokenizer/laris_spm_32k.model
laris evaluate language-encoder --checkpoint artifacts/checkpoints/language_encoder/<run-id>/best \
  --tokenizer-model artifacts/tokenizer/laris_spm_32k.model --split test
```

Checkpoints are written atomically to `artifacts/checkpoints/language_encoder/<run-id>/{best,last}` with a provenance manifest and SHA-256. Resume with `--resume <run-id>/last`.
