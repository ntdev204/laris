---
document_id: "DOC-ADR-013"
title: "ADR-013: Functional Sub-Package Layout, Function-Based Naming and the laris CLI"
document_type: "adr"
status: "ACCEPTED"
version: "1.0.0"
created_at: "2026-10-29"
updated_at: "2026-10-29"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/adr/ADR-011-domain-based-package-refactoring.md"
  - "docs/adr/ADR-012-elimination-of-parallel-layer-hierarchies.md"
  - "docs/development/CODING_STANDARDS.md"
decision_references:
  - "ADR-011"
  - "ADR-012"
change_summary: "Splits large domain modules into functional sub-packages, forbids version/stage-based names, and introduces the laris CLI as the single entry point."
---

# ADR-013: Functional Sub-Package Layout, Function-Based Naming and the laris CLI

## Metadata
- **ADR ID:** ADR-013
- **Status:** ACCEPTED
- **Date Decided:** 2026-10-29
- **Decision Owner:** LARIS Architecture Team
- **Target Scope:** `src/laris/`, `scripts/`, `configs/`, `tests/`

---

## 1. Context and Problem Statement

ADR-011/012 established one package per domain, but inside a domain files accumulated flat:
`language/` mixed tokenizer, encoder, trainer, data loading and retrieval baselines;
`corpus/task_splits.py` held 1,200 lines covering four datasets plus the coverage audit;
`scripts/acquire_datasets.py` held 1,450 lines of acquisition logic outside the importable package.
Names encoded versions and training stages (`Stage1LanguageTrainer`, `TransformerEncoder500MConfig`,
`train_stage1.py`, `Layer0Pipeline`, `model1_foundation.yaml`), which become wrong the moment the
model size or curriculum changes.

## 2. Decision

1. **Functional sub-packages inside a domain.** `language/` is split into `tokenization/`, `encoder/`,
   `training/`, `benchmarks/`; BM25 and the baseline comparison move to `retrieval/`;
   `corpus/` gains `acquisition/` (common, sources, registry, runner) and `splits/` (ratios, physical,
   partitioners, coverage, runner).
2. **Name by function, never by version, stage or size.** Sizes are configuration presets
   (`compact`, `large`), not class or file names. Examples: `LanguageEncoderTrainer`,
   `MultiTaskLossCalculator`, `LanguageEncoderConfig` / `LargeLanguageEncoderConfig`,
   `CorpusIngestionPipeline`. The only exception is the official name of an external dataset.
3. **One CLI entry point.** `laris data acquire|partition` and `laris train tokenizer|language-encoder`
   live in `laris.cli`; each command module exposes `add_arguments(parser)` and `run(args)`.
   Files in `scripts/` are thin compatibility wrappers (documentation tooling such as
   `validate_docs.py` stays a script).
4. **Configuration by function** under `configs/` (`language_encoder/`, `data/`); tests mirror the
   source tree under `tests/unit/<domain>/`.
5. **No import shims** for the old flat paths; the change is internal and enforced by
   `tests/contract/test_domain_packages.py`.

## 3. Consequences

### Positive
- Each module has one reason to change; adding a dataset means adding one acquirer/partitioner file.
- Names stay correct when model size or curriculum changes.
- All operational entry points are discoverable through `laris --help`.

### Negative / Trade-offs
- Branches written against the old flat paths must be rebased.
- Importers of `laris.language.bm25` / `laris.language.retrieval_benchmark` now use `laris.retrieval`.

## 4. Validation
- Contract tests assert that new sub-package modules import and that legacy flat modules are gone.
- `tests/cli/` exercises the command tree and the compatibility wrappers.
