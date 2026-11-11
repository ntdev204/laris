---
document_id: "DOC-DEV-CLI-001"
title: "LARIS Command-Line Interface Reference"
document_type: "specification"
status: "APPROVED"
version: "1.1.0"
created_at: "2026-10-29"
updated_at: "2026-11-10"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/specifications/LANGUAGE_ENCODER_TRAINING_SPECIFICATION.md"
  - "docs/specifications/DATASET_SPECIFICATION.md"
  - "docs/adr/ADR-013-functional-package-layout-and-cli.md"
decision_references:
  - "ADR-013"
change_summary: "Adds offline formal readiness, links the owner-only runbook and documents citation-ID verification versus source-backed extractive certification."
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
| `laris evaluate readiness --reports REPORT...` | Offline formal foundation audit; requires matching test evidence and protocols. No model loaded. Exit 0 qualified, 1 not qualified, 2 invalid input. | none |
| `laris evaluate calibrate --reports VAL_REPORT...` | Ratchet `configs/evaluation/language_encoder.yaml` up from passing `val` reports; never lowers, refuses `test` reports. | none |
| `laris infer {nli,...} --checkpoint DIR --tokenizer-model FILE` | Run a single prediction from a checkpoint. | none |

## Owner training and evaluation

The [owner runbook](../training/OWNER_RUNBOOK.md) is the execution reference.
Agents must not execute training, tokenizer fitting, backward/optimizer steps or
optimizer-bearing profiling/tests under the current instruction. `--profile-only`
can run real optimizer steps when `LARIS_TRAINING_AUTHORIZED=1`; its name alone
is not a no-training guarantee.

Baseline-relative `evaluate language-encoder` results do not qualify model 01.
`evaluate readiness` reads existing report files against
`configs/evaluation/foundation.yaml` without running a model. Missing official
metrics, incompatible QA protocols, mixed artifact identities or validation-only
reports block qualification. Model 02 remains unimplemented and must follow the
foundation exit gate.

Training progress and checkpoints remain under
`artifacts/checkpoints/language_encoder/<run-id>/{best,last}`. Resuming requires
matching recorded settings and does not restore the exact streaming data position.

## Report verification scope

`EvidenceGate` checks registered assertion citation IDs only. Its `verification_scope`
metadata is `citation_ids_only`; a passing coverage ratio is not evidence of source
integrity or entailment.

For source-backed extractive reports, use `SourceEvidenceGate(source_documents)`
with `StructuredReportGenerator(evidence_gate=gate)`. Supply canonical UTF-8 source
texts keyed by document ID, and corpus hashes computed from those texts. Every
assertion must equal its cited excerpt; each section's Markdown must equal its
assertion statements joined by blank lines. Empty sections are allowed, but reports
without assertions are rejected. Sources, hashes, coordinate IDs and character spans
are checked. Synthesis and paraphrases remain uncertified: this gate does not infer
semantic support or establish research-gap novelty.
