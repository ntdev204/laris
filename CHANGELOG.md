# LARIS Changelog

All notable changes to the LARIS project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
