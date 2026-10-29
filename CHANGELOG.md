# LARIS Changelog

All notable changes to the LARIS project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- **Encoder initialisation (Issue #293):** the PyTorch encoder kept the `nn.Embedding` default N(0, 1) for the tied token embedding, so a fresh model produced logits with a standard deviation of 27.8 and a raw MLM cross-entropy of 542.7 instead of about ln(32000) = 10.4 (a real run logged loss 197.66 and gradient norm 259 at step 1, clipped to 1.0 every step). The model now uses GPT-2 style initialisation (normal std 0.02, zero biases, residual projections scaled by 1/sqrt(2L)) and seeds itself before creating parameters, which it did too late before. Measured on real validation data with the fitted tokenizer, the initial raw MLM loss is now 10.20. Runs started before this fix begin from the bad initialisation and should be restarted.

### Added
- **Live training display (Issue #291):** `laris train language-encoder` now shows a progress bar with elapsed time, ETA and rate, and a metrics line with the running loss of each task (exponentially smoothed, so single-task micro-batches no longer make it jump), learning rate, gradient norm, GPU memory and the accumulation position. Validation prints as a table with the best step and the early-stopping counter. When output is not a terminal (`nohup`, redirected logs) or `tqdm` is missing it falls back to one plain line per `--log-interval` steps with the ETA. `tqdm` joins the `training` extra.

### Fixed
- **Compact sequence length (Issue #288):** `--model-size compact` clamped the model config to 512 tokens even when `--max-seq-len` was larger, while the dataloader used the requested length. Evaluation and inference read the length from the saved config, so a compact model trained at 1024 tokens would have been evaluated and used at 512. `--max-seq-len` now defaults to 1024 for large and 512 for compact and is honored as given.

## [1.1.4] - 2026-10-30

Re-release of 1.1.3 under a new version: the first `v1.1.3` tag pointed at an older commit and was withdrawn. The changes are the 1.1.3 entries below.

## [1.1.3] - 2026-10-30

### Fixed
- **Review fixes before release (Issue #282):** the authorized profile now scales the loss with the trainer's `GradScaler` before backward (it crashed with `--precision fp16`), and an answer with text but no `answer_start` is rejected by the ViQuAD2 partitioner and by the loader instead of becoming a "no answer" label (the real data has no such row).

### Fixed
- **Real data only (Issue #282):** an audit against the partitioned data showed rows that were silently given fabricated labels. 4,892 HotpotQA train questions without an answer span and 154 UIT-ViQuAD2.0 rows with a wrong `answer_start` were labelled "no answer"; 2 Quora pairs had an empty question. They are now dropped at partition time and `HOTPOTQA`, `UIT-VIQUAD-V2` and `QUORA-DUPLICATES` were re-partitioned (a scan of all 7,999,454 rows now finds 0 defects). The training loader raises on unknown NLI or paraphrase labels, a missing similarity score and a mismatched answer offset instead of mapping them to neutral, 0 or 0.0; with `require_real_data` (used by training, evaluation and profiling) it also refuses a missing tokenizer, default row counts and the synthetic fallback, and asking for a task without shards no longer silently returns another task.
- **Profile on real data:** `--profile-only` now needs the fitted tokenizer and measures real tokenized train batches (random token ids are gone). With `LARIS_TRAINING_AUTHORIZED=1` it runs a real optimizer step on a discarded randomly initialised model and measures the steady-state peak, so optimizer state and the bitsandbytes kernels are measured, not estimated. The analytic VRAM figure is removed from the CLI and `verify_target_server.sh` no longer runs a toy model on synthetic input.

## [1.1.2] - 2026-10-29

### Fixed
- **Measured GPU profile and paraphrase loss crash (Issue #278):** `laris train language-encoder --profile-only` no longer prints a formula result as "feasible". It builds the real model on the GPU and measures peak memory per task (forward only; with `LARIS_TRAINING_AUTHORIZED=1` also backward, still no optimizer step or weight update), exits non-zero without CUDA, and states that training memory is not certified until backward is measured. The analytical figure is labelled as a formula. The measurement exposed that the paraphrase loss (`binary_cross_entropy`) raised under CUDA bf16 autocast, which would have crashed training at the first paraphrase batch; it now runs in fp32 outside autocast. `scripts/verify_target_server.sh` no longer hard-codes another user's virtualenv path, and the runbook lists the profile as step 5/5b.

## [1.1.1] - 2026-10-29

### Removed
- **Dataset registry narrowed from 24 to 17 (Issue #274):** the registry keeps the 14 datasets that feed the language encoder plus S2ORC-STEM, LARIS-GOLD and NATURAL-QUESTIONS (planned for fine-tuning). VI-PAWS, UIT-VIQUAD v1.1, PUBLAYNET-MINI, DOCLAYNET-BOUNDED, UD-EWT-EN, UD-VTB-VI and SCIFACT lose their acquirers, manifest entries, coverage handling and tests; the manifest now reports 17 datasets, 8,288,209 records and 12.06 GB. Their raw directories (about 48 MB) were deleted from disk; they are re-downloadable from the public sources if a consumer appears.

## [1.1.0] - 2026-10-29

### Added
- **Pairwise dataset partitioning (Issue #264):**
  - `laris data partition` now partitions All-NLI, ANLI (R1-R3), PAWS-Wiki and STSB, keeping the upstream train/dev/test splits and removing train rows that collide with held-out val/test (pair level for NLI and STSB, either-sentence level for PAWS). The NLI, paraphrase and similarity tasks read them from `data/processed`.
  - A partial run (`--datasets X`) now merges into the existing `task_splits_manifest.json` by `dataset_id` instead of overwriting it.
- **Server preparation (Issue #266):** `laris data check` verifies manifest files, per-task train/val/test coverage and `sentencepiece` before training (exit 1 when not ready); `docs/development/CLI.md` carries the step-by-step server runbook.
- **FEVER evidence and threshold calibration (Issue #262):**
  - `laris data acquire --only FEVER` now resolves evidence references against the official FEVER Wikipedia snapshot (`wiki-pages.zip`) into `evidence_sentences.parquet` (the Hugging Face parquet copy is truncated and is not used). `laris data partition` turns SUPPORTS/REFUTES claims into entailment/contradiction premise-hypothesis pairs; NOT ENOUGH INFO has no evidence and is dropped. The language encoder's NLI task now loads `fever`.
  - `laris evaluate calibrate` ratchets `configs/evaluation/language_encoder.yaml` up from passing `val` reports (never lowers; refuses `test` reports). The shipped thresholds remain baseline-relative floors until a trained checkpoint is measured.

### Changed
- **Security reporting (Issue #265):** `SECURITY.md` points to GitHub private vulnerability reporting, which is now enabled for the repository.
- **Documentation trim (Issue #267):** condensed `LAYER_ARCHITECTURE` (216 to 66 lines), `ORCHESTRATION_SPECIFICATION` (195 to 140) and `DATA_SCHEMAS` (185 to 71) into tables; every invariant, enum and required field is preserved.
- **Documentation slimmed and standardized (Issue #260):**
  - Removed redundant or historical files: `docs/archive/`, `docs/RELEASE_NOTES.md` (this changelog is the release history), `docs/DECISION_LOG.md` (the ADR index is the register), `docs/plans/BACKLOG.md` (work is tracked in GitHub issues), `SESSION.md` and `implement_plan.md`.
  - Condensed `DOCUMENTATION.md` (262 to ~110 lines) and the language encoder training specification (494 to ~330); stage 2-6 detail now lives in a gate table and the roadmap.
  - ADR index lists ADR-001 to ADR-013 and holds the FROZEN-document register used by `validate_docs.py`.
  - Added `SECURITY.md`, `.github/CODEOWNERS` and issue templates (bug, task, documentation); README and CONTRIBUTING describe the issue-to-PR workflow.

### Changed
- **Documentation consolidation (Issue #251):**
  - Merged overlapping documents: agent/skill/tool/workflow specs into `ORCHESTRATION_SPECIFICATION`; documentation standard and lifecycle into `development/DOCUMENTATION`; roadmap and milestones into `plans/ROADMAP`; training specification and staged pipeline into `LANGUAGE_ENCODER_TRAINING_SPECIFICATION`; language foundation, local model and semantic strategies into `research/LANGUAGE_AND_MODEL_STRATEGY`.
  - Moved `IDEA.md` and the delivered M1-M10 backlog task specifications to `docs/archive/` (excluded from the documentation gate); removed the duplicate ADR template.
  - Replaced machine-specific `file:///` links with relative links; rebuilt `docs/README.md`; shrank `SESSION.md`; added `docs/development/CLI.md`.

### Added
- **CLI evaluation and inference (Issue #250):**
  - `laris evaluate language-encoder` scores a checkpoint on `val`/`test` for MLM, NLI, paraphrase, similarity and QA per dataset and per language against baselines, writes a JSON report and exits non-zero when a task/language group misses `configs/evaluation/language_encoder.yaml`.
  - `laris train language-encoder` runs the same check on the best checkpoint after training (`--evaluate-after`, default on).
  - `laris infer fill-mask|nli|paraphrase|similarity|qa|embed` for single-example predictions; checkpoints and tokenizers are verified by SHA-256 before use.
  - Evaluation refuses the `train` split and requires a leakage-verified split manifest.

### Added
- **Language encoder training loop (Issue #248):**
  - Linear-warmup + cosine LR schedule (`training/schedule.py`); `--steps`, `--learning-rate`, `--warmup-steps` and loss weights now come from `configs/language_encoder/<size>.yaml` with CLI overrides.
  - Real mixed precision: `torch.autocast` for bf16/fp16 (+ `GradScaler` for fp16 on CUDA); non-finite gradients skip the update instead of corrupting weights.
  - Steps are counted per optimizer update (gradients accumulate across micro-batches and tasks); snapshots carry learning rate and gradient norm.
  - Atomic checkpoints (`training/checkpoint.py`): `model.pt`, `training_state.pt` (optimizer, scheduler, scaler, RNG, counters) and a provenance `manifest.json` (git commit, seed, config, tokenizer and dataset digests, model SHA-256); corrupt checkpoints are rejected on load.
  - `training/loop.py`: periodic validation on the held-out `val` split (never `test`), `best/` and `last/` checkpoints, early stopping and `--resume`.

### Added
- **Partitioning for the bilingual expansion datasets (Issue #249):**
  - `laris data partition` now handles ViNLI, ViSTS, HotpotQA, FEVER, UIT-ViQuAD2.0 and CC-100 VI with leakage-safe splits (per-dataset modules in `corpus.splits.partitioners`).
  - ViNLI keeps official splits and drops the 4th `other` label (the NLI head is 3-way); ViSTS is split by connected sentence components and rescaled to [0, 1]; HotpotQA is converted to extractive QA (supporting paragraphs first; yes/no answers carry no span); UIT-ViQuAD2.0 keeps its official train and sub-splits validation by article (it supersedes v1.1 on the same contexts, so v1.1 is not used as a QA source); CC-100 is hash-split with exact-duplicate removal against Wikipedia-VI; FEVER (claims only, no evidence text) is partitioned but not loaded for training.
  - Datasets whose license is not approved are skipped unless `--include-unreviewed-licenses` is given.
  - The streaming loader discovers the new directories and derives task sampling weights from Parquet footers instead of hard-coded counts.

### Changed
- **Functional package layout and `laris` CLI (Issue #247, ADR-013):**
  - `language/` split into `tokenization/`, `encoder/`, `training/`, `benchmarks/`; BM25 and the baseline comparison moved to `retrieval/`.
  - `corpus.acquisition` (common, sources, registry, runner) replaces the 1,450-line acquisition script; `corpus.splits` (ratios, physical, partitioners, coverage, runner) replaces `task_splits.py`.
  - Names no longer encode versions or stages: `LanguageEncoderTrainer`, `MultiTaskLossCalculator`, `LanguageEncoderConfig`/`LargeLanguageEncoderConfig`, `CorpusIngestionPipeline`; `--model-tier 500m` is now `--model-size large`.
  - New `laris` command (`data acquire|partition`, `train tokenizer|language-encoder`); `scripts/*.py` are thin wrappers. `train_stage1.py` is now `train_language_encoder.py`.
  - Configs organised by function (`configs/language_encoder/{compact,large}.yaml`, `configs/data/partition.yaml`); unit tests mirror the source tree under `tests/unit/<domain>/`.

### Fixed
- **Training data integrity (Issue #246):**
  - `StreamingParquetMultiTaskDataLoader` reads only the configured split (`split="train"` by default); val/test shards are never mixed into training.
  - Extractive QA labels now come from the real gold answer offsets (unanswerable or truncated answers point to `[CLS]`) instead of a fixed position.
  - Fallback tokenizer uses CRC32 so token ids are stable across processes; `scripts/train_stage1.py` now requires `--tokenizer-model` and a vocab match.
  - No silent synthetic-data fallback (`fallback_to_synthetic=False` by default); unreadable shards are logged and dropped and cannot hang the stream.
  - Trainer moves the model to its device; falling back from 8-bit AdamW emits a `RuntimeWarning`.
  - SentencePiece args reserve `[MASK]` as id 4, matching the special-token contract (previously id 4 was `[MATH]`).
  - CI installs CPU PyTorch so neural tests run instead of being skipped.

### Added
- **Bilingual expansion dataset acquisition (Issue #244):**
  - Automated, resumable acquisition for `VINLI`, `VISTS`, `HOTPOTQA`, `FEVER`, `UIT-VIQUAD-V2` and streamed `CC100-VI-CLEAN` (2.7M documents), plus `VI-PAWS` recorded as `BLOCKED` (no Vietnamese PAWS-X exists). `scripts/acquire_datasets.py --only DATASET_ID` merges into the existing manifest.
  - Manifest now tracks 24 datasets, 8,347,135 acquired records (4.23M English, 4.12M Vietnamese), 12.09 GB. `VINLI`, `UIT-VIQUAD-V2`, `CC100-VI-CLEAN` declare no license; the project owner approved their use on 2026-10-29 (`APPROVED_BY_OWNER`, a governance decision rather than a legal clearance), so they are `VERIFIED`.
  - Corrected spec sources/licenses (FEVER CC-BY-SA-3.0, ViSTS MIT) and documented that the ~16.5M projection is unreachable with real data.
  - Manifest accounting contract test now checks invariants instead of a hard-coded total.
- **Genuine Multi-Task Parameter Optimization in `Stage1LanguageTrainer` (Issue #242):**
  - Implemented real autograd forward, task loss computation (`F.cross_entropy`, `F.binary_cross_entropy`, `F.mse_loss`), `loss.backward()`, gradient accumulation, `clip_grad_norm_`, and `optimizer.step()`.
  - Supported plug-and-play 8-bit AdamW (`bitsandbytes`) with automatic fallback to standard PyTorch AdamW.
  - Telemetry tracking genuine loss values, effective batch size, and peak CUDA VRAM allocation.
  - Strict authorization enforcement raising `TrainingExecutionProhibitedError` on unauthorized runs.
- **Real Streaming Parquet Multi-Task DataLoader (`StreamingParquetMultiTaskDataLoader`) (Issue #242):**
  - Streaming reader using `pyarrow.parquet.ParquetFile.iter_batches` guaranteeing strictly bounded RAM ($\le 250\text{ MB}$).
  - Temperature-scaled task selection ($\alpha = 0.7$) interleaving MLM, NLI, Paraphrase, Similarity, and QA streams.
  - Real dynamic MLM masking at 15% rate (80% `[MASK]`, 10% random token, 10% unchanged) with `-100` target masking.
  - Multi-task sequence formatting with `[CLS]`, `[SEP]`, padding, and attention masks.
  - Infinite shard cycling across epochs and support for both PyTorch tensors (`return_tensors="pt"`) and NumPy arrays (`return_tensors="np"`).
- **Stage 1 Training CLI Integration (`scripts/train_stage1.py`) (Issue #242):**
  - Integrated `StreamingParquetMultiTaskDataLoader` and `Stage1LanguageTrainer` into CLI runner supporting `--data-dir`, `--steps`, and `--log-interval`.
- **Unit & Contract Verification (`tests/unit/test_trainer_and_streaming_dataloader.py`) (Issue #242):**
  - Verified genuine parameter optimization, loss calculation, and weight changes after `optimizer.step()`.
  - Verified gradient flow across all 5 Stage 1 multi-task objectives.
  - Verified gradient accumulation behavior across micro-batches.

## [1.0.0] - 2026-10-23

### Added
- **Full 12-Layer System Baseline (Milestones M0–M10):**
  - Layer 0: Corpus ingestion, exact SHA-256 deduplication, and non-destructive task partitioning.
  - Layer 1: From-scratch 12-layer bidirectional Transformer encoder (109.56M backbone params, 109.76M with multi-task heads), RoPE rotary positional encoding, RMSNorm pre-normalization, GELU activation, and tied MLM embeddings (`src/laris/language/neural.py`).
  - Layer 1 Tokenizer: SentencePiece 32k BPE tokenizer training pipeline with clean train-only Wikipedia extraction and Unicode preservation validation (`src/laris/language/tokenizer_trainer.py`).
  - Layer 2: 3-way scientific NLI classifier, semantic equivalence, and negation/contradiction detection (`src/laris/semantic/`).
  - Layer 3: Scientific NLP, discourse segmentation, heading-agnostic section parsing, and STEM unit normalizer (`src/laris/scinlp/`).
  - Layer 4 & 5: Embedded evidence knowledge graph on SQLite with indexed nodes, edges, and provenance metadata (`src/laris/graph/`).
  - Layer 6: Multi-channel hybrid retrieval combining BM25 and dense cosine projections with Reciprocal Rank Fusion (`src/laris/retrieval/`).
  - Layer 7: Epistemic research reasoning, 12-class research gap discovery matrix, and contradiction analysis (`src/laris/reasoning/`).
  - Layer 8: Multi-agent orchestrator with state-machine DAG execution, cycle detection, and token budget governance (`src/laris/orchestration/`).
  - Layer 9: Adaptive local execution, hardware memory headroom governor (14.5 GB ceiling), and LRU module cache (`src/laris/execution/`).
  - Layer 10: Capability evaluation suites, benchmark isolation, and feedback tracking (`src/laris/evaluation/`).
  - Layer 11: Structured report synthesis, citation attribution, and epistemic verification (`src/laris/reporting/`).
- **Data Acquisition & Scalable Inventory (Milestone M11 / M1):**
  - Acquired 14 open-access datasets totaling 5,106,491 records (3.78M English, 1.32M Vietnamese) across Wikipedia EN/VI, Universal Dependencies, All-NLI, ANLI, Quora Duplicates, PAWS-Wiki, STS-B, SQuAD v1.1, UIT-ViQuAD, SciFact, and PubLayNet.
  - Cryptographic verification via SHA-256 digests in `data/acquisition_manifest.json`.
- **High-Performance Physical Dataset Partitioning (Issues #232, #234):**
  - Streaming Parquet partitioning via `pyarrow.parquet.ParquetFile.iter_batches` guaranteeing bounded memory.
  - Multi-worker parallel processing across shards via `ProcessPoolExecutor` utilizing 14 CPU cores on target server.
  - Streaming merge engine consolidating intermediate shard parts directly on NVMe SSD with automatic temporary cleanup.
  - CLI utility `scripts/partition_datasets.py` supporting `--batch-size` and `--num-workers`.
- **Tokenizer Pipeline & Clean Extraction Runner (Issue #232):**
  - Train-only Wikipedia text extraction strictly rejecting validation and test partitions (`DataLeakageError`).
  - SentencePiece 32k BPE training runner gated by centralized authorization.
  - CLI utility `scripts/train_tokenizer.py` supporting `--authorized` execution.
- **Centralized Configuration System (Issue #215 / PR #217):**
  - 4-tier configuration architecture (`src/laris/config/`) enforcing immutable invariants (14.5 GB VRAM ceiling, zero data leakage) alongside tunable parameters.
- **Target Workstation Verification & Blackwell Support (PR #224, #229):**
  - Target server verification kịch bản `scripts/verify_target_server.sh` verifying NVIDIA GeForce RTX 5070 Ti, Blackwell `sm_100/sm_120`, CUDA $\ge 12.6$, and PyTorch $\ge 2.6.0$.
  - Bounded forward-only profiling and non-training hardware telemetry (`src/laris/language/profiling.py`).
- **Governance & Stop Condition Barrier:**
  - Mandatory authorization gate in `src/laris/core/authorization.py` ensuring zero accidental training on developer workstation.
- **Comprehensive Quality Gates:**
  - 1018 automated tests passing in `tests/`.
  - Zero `ruff` and zero `mypy` errors across 90 source files.
  - 61 formal documentation files validated by `scripts/validate_docs.py`.
  - Canonical `SESSION.md` capturing full codebase state and target server execution guide.

### Changed
- Reconciled documentation and updated `docs/specifications/NATURAL_LANGUAGE_TRAINING_SPECIFICATION.md` to serve as the single source of truth for neural architecture, hardware envelopes, and formal readiness gates.
- Resolved and closed open architecture questions OQ-001, OQ-002, OQ-003, and OQ-005 in `docs/OPEN_QUESTIONS.md`.

### Removed
- Removed resolved, one-off audit reports (`REPOSITORY_AUDIT.md`, `CONFIG_AUDIT_REPORT.md`, `MODEL_TRAINING_AUDIT.md`, `TRAINING_READINESS_AUDIT.md`) following full remediation and consolidation into core specifications.
