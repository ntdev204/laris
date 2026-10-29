# LARIS Active Session Context & Architecture Guide

This document captures the canonical, up-to-date context of the **Local Autonomous Research & Intelligence System (LARIS)** codebase, development rules, hardware profiles, and operational procedures.

---

## 1. System Vision & Foundational Tenets

LARIS is a local-first, epistemic AI research platform designed to ingest scientific literature, maintain an auditable evidence knowledge graph, synthesize multi-paper findings, and discover verifiable research gaps without relying on external cloud APIs or black-box foundation LLMs.

### Inviolable Architectural Principles
1. **Local-First System Boundary ([ADR-001](docs/adr/ADR-001-local-first-system-boundary.md)):** All computation, representations, and storage reside on local workstation hardware.
2. **Self-Built Language Foundation ([ADR-002](docs/adr/ADR-002-self-built-language-foundation.md)):** Core tokenization, sentence embeddings, NLI, and discourse comprehension are trained from raw corpora under local control.
3. **Language-First, Not PDF-First ([ADR-003](docs/adr/ADR-003-language-first-not-pdf-first.md)):** High-level linguistic reasoning is established before document vision or OCR processing.
4. **Evidence-First Epistemic Provenance ([ADR-004](docs/adr/ADR-004-evidence-provenance-first-class.md)):** Every claim and conclusion is anchored to immutable source coordinates (document, page, sentence span).
5. **Three-Tier Selective Execution ([ADR-005](docs/adr/ADR-005-selective-loading-computation-access.md)):** Strict separation of Selective Loading, Selective Computation, and Selective Information Access within the 14.5 GB VRAM ceiling.
6. **Empirical Evaluation Before Capability Claims ([ADR-008](docs/adr/ADR-008-evaluation-before-capability-claims.md)):** No capability claim is valid without isolated, reproducible benchmark results.

---

## 2. Environments & Hardware Dual-Track

### A. Development Machine (Local WSL2)
- **Role:** Code authoring, refactoring, unit/contract testing, documentation, and quality gate verification.
- **Hardware:** Intel Core i5-10300H (4 cores / 8 threads), 3.7 GiB allocated host RAM, NVIDIA GeForce GTX 1650 (4 GB VRAM, Turing `sm_75`).
- **MANDATORY POLICY: ZERO NEURAL TRAINING (ABSOLUTE STOP CONDITION)**
  - No gradient descent, no backpropagation, no optimizer steps, no weight updates.
  - All unit tests run either on CPU or with synthetic forward-only passes.
  - Guarded by `TrainingExecutionProhibitedError` in `src/laris/core/authorization.py`.

### B. Target Production Workstation (Server)
- **Role:** Physical dataset partitioning, tokenizer fitting, and neural pretraining execution.
- **Hardware:**
  - **GPU:** NVIDIA GeForce RTX 5070 Ti (16 GB VRAM, Blackwell architecture `sm_100` / `sm_120`, CUDA $\ge 12.6$).
  - **CPU:** Intel Core i5-14600KF (14 cores / 20 threads).
  - **RAM:** 32 GB DDR5 RAM.
  - **Storage:** High-throughput NVMe SSD ($\ge 200$ GB free).
- **Software:** Ubuntu 22.04/24.04 LTS, Python 3.10+, PyTorch $\ge 2.6.0$ with Blackwell CUDA binary support (`torch>=2.6.0`).

---

## 3. Codebase State & Implementation Inventory

| Dimension | Metric / Status |
| :--- | :--- |
| **Source Modules** | 92 Python source files under `src/laris/` across 12 layers |
| **Automated Tests** | 1030 passing unit, contract, and integration tests under `tests/` |
| **Linters & Typers** | 100% clean: `ruff` 0 errors, `mypy` 0 errors across all 92 source files |
| **Documentation** | 61 formal Markdown documents under `docs/`, 100% compliant with `scripts/validate_docs.py` |
| **Acquired Datasets** | 8,347,135 records across 20 datasets (17 verified, 3 pending license review) in `data/raw/` (4.23M English, 4.12M Vietnamese; 12.09 GB) |

### Key Modules Implemented
- **Centralized Configuration (`src/laris/config/`):** 4-tier configuration system (CLI, YAML, Defaults, Invariants) with cryptographic SHA-256 state tracking and safety ceilings.
- **Physical Dataset Partitioning (`src/laris/corpus/task_splits.py`):**
  - Streaming Parquet partitioner using `pyarrow.parquet.ParquetFile.iter_batches`.
  - Multi-worker parallel processing via `concurrent.futures.ProcessPoolExecutor` utilizing 14 CPU cores.
  - Streaming merge and automatic temporary cleanup on NVMe SSD.
  - Memory-safe under bounded allocations.
- **Clean Tokenizer Extraction & Runner (`src/laris/language/tokenizer_trainer.py`):**
  - Train-only Wikipedia text extraction strictly rejecting validation/test splits (`DataLeakageError`).
  - SentencePiece 32k BPE training runner gated by `assert_tokenizer_training_authorized()`.
- **Neural Model Architecture (`src/laris/language/neural.py`):**
  - **110M Baseline:** 12-layer bidirectional Transformer encoder ($d_{\text{model}}=768$, 12 heads, $d_{\text{ff}}=3072$, RoPE, RMSNorm, GELU, tied MLM embeddings, 109.56M/109.76M params).
  - **512M Scaled Foundation:** 24-layer bidirectional Transformer encoder ($d_{\text{model}}=1280$, 20 heads, $d_{\text{ff}}=5120$, $S=1024$, RoPE, RMSNorm, GELU, tied MLM embeddings, 512.91M/513.25M params).
  - Multi-task capability heads: MLM, 3-way NLI, Paraphrase binary classification, STS-B continuous similarity, QA span logits.
  - Native FlashAttention-2 / SDPA and Activation Checkpointing for 14GB VRAM target optimization.
- **Real Multi-Task Streaming DataLoader & Trainer (`src/laris/language/dataloader.py`, `src/laris/language/trainer.py`):**
  - `StreamingParquetMultiTaskDataLoader`: True streaming PyArrow Parquet loader with bounded buffer (`ParquetFile.iter_batches`), strictly preserving the $\le 250\text{ MB}$ RAM ceiling, 15% dynamic MLM masking (80% MASK, 10% random, 10% keep), and temperature sampling ($\alpha = 0.7$).
  - `LanguageEncoderTrainer`: Genuine optimization steps executing autograd forward, task loss computation (`F.cross_entropy`, `F.binary_cross_entropy`, `F.mse_loss`), scaled backward, gradient accumulation, `clip_grad_norm_`, and `optimizer.step()` with 8-bit AdamW / PyTorch AdamW.
  - Strict authorization barrier (`assert_training_authorized`) strictly enforced.
- **Artifact Governance (`src/laris/language/artifacts.py`):**
  - `LanguageArtifactBundle`, `VocabularyContract`, `LanguageTrainingRunManifest`.

---

## 4. CLI Utilities Quick Reference

```bash
# 1. Validate Target Server Hardware (Run on Server)
bash scripts/verify_target_server.sh

# 2. Partition Datasets with 14 Cores and 100k Batch Size (Run on Server)
python3 scripts/partition_datasets.py --num-workers 14 --batch-size 100000

# 3. Fit 32k SentencePiece Tokenizer from Clean Train Split (Run on Server)
python3 scripts/train_tokenizer.py --authorized

# 4. Profile 500M Model VRAM Feasibility (Zero Training, Local or Server)
python3 scripts/train_stage1.py --model-tier 500m --profile-only

# 5. Execute Stage 1 Training on Target Server (Requires Authorization)
export LARIS_TRAINING_AUTHORIZED=1
python3 scripts/train_stage1.py --model-tier 500m --authorized

# 6. Run Documentation Quality Gate (Local / CI)
python3 scripts/validate_docs.py

# 5. Run All Quality Gates (Local WSL2)
laris-env/bin/pytest tests/
laris-env/bin/ruff check .
laris-env/bin/mypy src
```

---

## 5. Development Workflow (Git Flow Mandate)

All contributors and AI agents MUST adhere strictly to Git Flow:
1. Every task or fix starts from an active GitHub Issue.
2. Cut a feature branch from `develop`: `feature/<issue-id>-<description>`.
3. Implement code, write unit/contract tests, and update documentation.
4. Verify all quality gates pass: `pytest`, `ruff`, `mypy`, `validate_docs.py`.
5. Open PR targeting `develop`, squash & merge upon approval.
6. **Immediately delete the feature branch** locally and on remote.
7. Merge `develop` into `main` only for releases with version tags (`vX.Y.Z`).
