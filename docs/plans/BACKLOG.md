---
document_id: "DOC-PLAN-BACKLOG-001"
title: "LARIS Engineering Task Backlog & Execution Registry"
document_type: "plan"
status: "DRAFT"
version: "0.1.0"
created_at: "2026-10-15"
updated_at: "2026-10-15"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/plans/IMPLEMENTATION_ROADMAP.md"
  - "docs/plans/MILESTONES.md"
  - "docs/specifications/MODULE_CONTRACTS.md"
decision_references:
  - "ADR-007"
  - "ADR-008"
change_summary: "Initial master task backlog for Milestone M1 (Corpus Ingestion & Data Governance)."
---

# LARIS Engineering Task Backlog & Execution Registry

This document serves as the single source of truth for active task tracking, execution status, and acceptance criteria across all LARIS engineering milestones.

## Status Legend
- `BACKLOG`: Recorded, awaiting prioritization or prerequisites.
- `READY`: Scope, contracts, and acceptance criteria defined.
- `IN_PROGRESS`: Currently under execution.
- `IN_REVIEW`: Implementation complete, undergoing quality gate and test audit.
- `BLOCKED`: Work halted due to an external blocker or missing authorization.
- `DONE`: All acceptance criteria verified by automated tests and documented.

---

## Milestone M0: Documentation & Governance Baseline
**Status:** `DONE` (Awaiting formal stakeholder freeze authorization)

| Task ID | Task Name | Scope & Deliverable | Status |
| :--- | :--- | :--- | :--- |
| `M0-AUDIT-001` | Repository Reality Check | Initial discovery, audit report, git status check. | `DONE` |
| `M0-GOV-001` | Core Governance & Standards | `DOCUMENTATION_STANDARD.md`, `DOCUMENT_LIFECYCLE.md`. | `DONE` |
| `M0-ARCH-001` | Architecture Specifications | `IDEA.md`, 12-layer specs, system overview, data flow. | `DONE` |
| `M0-ADR-001` | ADR Baseline (001–008) | Accepted architectural decision records. | `DONE` |
| `M0-SPEC-001` | Module Contracts & Schemas | `MODULE_CONTRACTS.md`, `DATA_SCHEMAS.md`, skills/tools/agents. | `DONE` |
| `M0-GATE-001` | Quality Gate Automation | `scripts/validate_docs.py`, unittest test suites. | `DONE` |
| `BOOT-DEV-001-SUB-01` | Root laris-env & canonical dependency manifest | Issue #111: `pyproject.toml`, `./laris-env/`, smoke tests. | `DONE` |
| `BOOT-DEV-001-SUB-02` | Git Flow & PR quality gates | Issue #112: Git Flow doc, coding standards. | `DONE` |
| `BOOT-DEV-001-SUB-03` | CI checks & PR review enforcement | Issue #113: GitHub Actions CI workflow, PR template. | `DONE` |

---

## Milestone M1: Corpus Ingestion & Data Governance (Layer 0)
**Status:** `DONE`

| Task ID | Task Name | Module | Status | Dependencies |
| :--- | :--- | :--- | :--- | :--- |
| `M1-DATA-001` | Corpus Manifest & Data Contract Schema | `MOD-CORPUS-001` | `DONE` | `M0-SPEC-001` |
| `M1-DATA-001-SUB-01` | Define typed schema fields and invariants | `MOD-CORPUS-001` | `DONE` | `M1-DATA-001` |
| `M1-DATA-001-SUB-02` | Validate manifest invariants and authorization | `MOD-CORPUS-001` | `DONE` | `M1-DATA-001-SUB-01` |
| `M1-DATA-002` | Deterministic Text & Math Normalizer | `MOD-CORPUS-001` | `DONE` | `M1-DATA-001` |
| `M1-DATA-002-SUB-01` | Implement deterministic Unicode and math normalization | `MOD-CORPUS-001` | `DONE` | `M1-DATA-002` |
| `M1-DATA-002-SUB-02` | Add normalization regression and idempotence tests | `MOD-CORPUS-001` | `DONE` | `M1-DATA-002-SUB-01` |
| `M1-DATA-003` | Content Hashing & Deduplication Engine | `MOD-CORPUS-001` | `DONE` | `M1-DATA-002` |
| `M1-DATA-003-SUB-01` | Implement canonical content digest and exact deduplication | `MOD-CORPUS-001` | `DONE` | `M1-DATA-003` |
| `M1-DATA-003-SUB-02` | Add exact and near-duplicate detection policy/tests | `MOD-CORPUS-001` | `DONE` | `M1-DATA-003-SUB-01` |
| `M1-DATA-004` | Leakage-Proof Dataset Partition Engine | `MOD-CORPUS-001` | `DONE` | `M1-DATA-003` |
| `M1-DATA-004-SUB-01` | Implement grouped deterministic split assignment | `MOD-CORPUS-001` | `DONE` | `M1-DATA-004` |
| `M1-DATA-004-SUB-02` | Add split manifest integrity and leakage tests | `MOD-CORPUS-001` | `DONE` | `M1-DATA-004-SUB-01` |
| `M1-DATA-005` | Ingestion Verification & Synthetic Test Fixtures | `MOD-CORPUS-001` | `DONE` | `M1-DATA-004` |
| `M1-DATA-005-SUB-01` | Implement synthetic corpus fixtures & pipeline integration | `MOD-CORPUS-001` | `DONE` | `M1-DATA-005` |
| `M1-DATA-005-SUB-02` | Implement processed directory structure & exit gates | `MOD-CORPUS-001` | `DONE` | `M1-DATA-005-SUB-01` |

---

## Milestone M2: Language Foundation & Core Representations (Layer 1)
**Status:** `DONE`

| Task ID | Task Name | Module | Status | Dependencies |
| :--- | :--- | :--- | :--- | :--- |
| `M2-LANG-001` | Scientific Tokenizer & Vocabulary Pipeline | `MOD-LANG-001` | `DONE` | `M1-DATA-005` |
| `M2-LANG-001-SUB-01` | Define tokenizer training data and vocabulary contracts | `MOD-LANG-001` | `DONE` | `M2-LANG-001` |
| `M2-LANG-001-SUB-02` | Implement tokenizer evaluation and STEM fertility report | `MOD-LANG-001` | `DONE` | `M2-LANG-001-SUB-01` |
| `M2-LANG-002` | Compact Sentence Encoder & Retrieval Benchmark | `MOD-LANG-002` | `DONE` | `M2-LANG-001` |
| `M2-LANG-002-SUB-01` | Implement sentence encoder interfaces and retrieval baseline | `MOD-LANG-002` | `DONE` | `M2-LANG-002` |
| `M2-LANG-002-SUB-02` | Add embedding correctness and BM25 comparison tests | `MOD-LANG-002` | `DONE` | `M2-LANG-002-SUB-01` |
| `M2-LANG-003` | Language Foundation Training Reproducibility & Artifacts | `MOD-LANG-003` | `DONE` | `M2-LANG-002` |
| `M2-LANG-003-SUB-01` | Implement reproducible language training artifacts | `MOD-LANG-003` | `DONE` | `M2-LANG-003` |
| `M2-LANG-003-SUB-02` | Add checkpoint integrity, lineage and reproducibility tests | `MOD-LANG-003` | `DONE` | `M2-LANG-003-SUB-01` |

---

## Milestone M3: Semantic Relations & NLI (Layer 2)
**Status:** `DONE`

| Task ID | Task Name | Module | Status | Dependencies |
| :--- | :--- | :--- | :--- | :--- |
| `M3-SEM-001` | Three-Way Scientific NLI | `MOD-SEM-001` | `DONE` | `M2-LANG-003` |
| `M3-SEM-001-SUB-01` | Define NLI schemas, validation and error semantics | `MOD-SEM-001` | `DONE` | `M3-SEM-001` |
| `M3-SEM-001-SUB-02` | Implement NLI inference behavior and boundary tests | `MOD-SEM-001` | `DONE` | `M3-SEM-001-SUB-01` |
| `M3-SEM-002` | Semantic Equivalence, Coreference & Discourse Relations | `MOD-SEM-001` | `DONE` | `M3-SEM-001` |
| `M3-SEM-002-SUB-01` | Define semantic relation output contracts | `MOD-SEM-001` | `DONE` | `M3-SEM-002` |
| `M3-SEM-002-SUB-02` | Test semantic relation ambiguity and provenance | `MOD-SEM-001` | `DONE` | `M3-SEM-002-SUB-01` |
| `M3-SEM-003` | NLI Calibration & Contradiction Evaluation | `MOD-SEM-001` | `DONE` | `M3-SEM-002` |
| `M3-SEM-003-SUB-01` | Build scientific NLI benchmark and calibration report | `MOD-SEM-001` | `DONE` | `M3-SEM-003` |
| `M3-SEM-003-SUB-02` | Add benchmark split isolation and failure analysis | `MOD-SEM-001` | `DONE` | `M3-SEM-003-SUB-01` |

---

## Milestone M4: Scientific NLP & Discourse Intelligence (Layer 3)
**Status:** `DONE`

| Task ID | Task Name | Module | Status | Dependencies |
| :--- | :--- | :--- | :--- | :--- |
| `M4-SCINLP-001` | Scientific Entity & Formula Extractor | `MOD-SCINLP-001` | `DONE` | `M3-SEM-003` |
| `M4-SCINLP-001-SUB-01` | Implement entity and formula extractor interfaces | `MOD-SCINLP-001` | `DONE` | `M4-SCINLP-001` |
| `M4-SCINLP-001-SUB-02` | Add entity recognition tests and LaTeX math validation | `MOD-SCINLP-001` | `DONE` | `M4-SCINLP-001-SUB-01` |
| `M4-SCINLP-002` | Heading-Aware Section Segmenter & Discourse Hierarchy | `MOD-SCINLP-002` | `DONE` | `M4-SCINLP-001` |
| `M4-SCINLP-002-SUB-01` | Implement section segmentation and discourse tree structures | `MOD-SCINLP-002` | `DONE` | `M4-SCINLP-002` |
| `M4-SCINLP-002-SUB-02` | Benchmark section parsing accuracy across document layouts | `MOD-SCINLP-002` | `DONE` | `M4-SCINLP-002-SUB-01` |
| `M4-SCINLP-003` | STEM Unit & Quantitative Relation Normalizer | `MOD-SCINLP-003` | `DONE` | `M4-SCINLP-002` |
| `M4-SCINLP-003-SUB-01` | Implement scientific unit conversion and magnitude scaling | `MOD-SCINLP-003` | `DONE` | `M4-SCINLP-003` |
| `M4-SCINLP-003-SUB-02` | Add boundary tests for numerical ranges and dimensional analysis | `MOD-SCINLP-003` | `DONE` | `M4-SCINLP-003-SUB-01` |

---

## Milestone M5: Hybrid RAG & Evidence Graph (Layer 5 & Layer 6)
**Status:** `DONE`

| Task ID | Task Name | Module | Status | Dependencies |
| :--- | :--- | :--- | :--- | :--- |
| `M5-EVID-001` | Versioned Evidence Graph Construction | `MOD-GRAPH-001` | `DONE` | `M4-SCINLP-003` |
| `M5-EVID-001-SUB-01` | Define versioned evidence graph nodes, edges and persistence interface | `MOD-GRAPH-001` | `DONE` | `M5-EVID-001` |
| `M5-EVID-001-SUB-02` | Add graph persistence, migration and edge provenance tests | `MOD-GRAPH-001` | `DONE` | `M5-EVID-001-SUB-01` |


| `M5-RETR-001` | Hybrid Lexical-Dense Retrieval Engine | `MOD-GRAPH-001` | `DONE` | `M5-EVID-001` |
| `M5-RETR-001-SUB-01` | Implement reciprocal rank fusion and dense-lexical hybrid pipeline | `MOD-GRAPH-001` | `DONE` | `M5-RETR-001` |
| `M5-RETR-001-SUB-02` | Benchmark multi-channel retrieval against single-modality baselines | `MOD-GRAPH-001` | `DONE` | `M5-RETR-001-SUB-01` |


| `M5-PROV-001` | Evidence Coordinate Validation & Provenance Tracking | `MOD-GRAPH-001` | `DONE` | `M5-RETR-001` |
| `M5-PROV-001-SUB-01` | Implement end-to-end evidence coordinate mapping & validation | `MOD-GRAPH-001` | `DONE` | `M5-PROV-001` |
| `M5-PROV-001-SUB-02` | Add coordinate corruption detection and audit trail regression tests | `MOD-GRAPH-001` | `DONE` | `M5-PROV-001-SUB-01` |


| `M6-GAP-001` | Cross-Paper Experimental Comparison & Conflict Detection | `MOD-GAP-001` | `DONE` | `M5-PROV-001` |
| `M6-GAP-001-SUB-01` | Implement comparative matrix and condition-aware contradiction engine | `MOD-GAP-001` | `DONE` | `M6-GAP-001` |
| `M6-GAP-001-SUB-02` | Add comparison matrix fixtures and synthetic contradiction benchmarks | `MOD-GAP-001` | `DONE` | `M6-GAP-001-SUB-01` |


| `M6-GAP-002` | Twelve-Class Research Gap Typology Classifier | `MOD-GAP-001` | `DONE` | `M6-GAP-001` |
| `M6-GAP-002-SUB-01` | Implement 12-class gap taxonomy and scoring schema | `MOD-GAP-001` | `DONE` | `M6-GAP-002` |
| `M6-GAP-002-SUB-02` | Add gap typology evaluation fixtures and gold set | `MOD-GAP-001` | `DONE` | `M6-GAP-002-SUB-01` |


| `M6-GAP-003` | Adversarial Self-Refutation and Counter-Evidence Discovery | `MOD-GAP-001` | `DONE` | `M6-GAP-002` |
| `M6-GAP-003-SUB-01` | Implement counter-evidence search and validation-plan contract | `MOD-GAP-001` | `DONE` | `M6-GAP-003` |
| `M6-GAP-003-SUB-02` | Add counter-evidence rejection and validation-plan tests | `MOD-GAP-001` | `DONE` | `M6-GAP-003-SUB-01` |


| `M7-ORCH-001` | Query Planner, DAG Runtime & Supervisor | `MOD-ORCH-001` | `DONE` | `M6-GAP-003` |
| `M7-ORCH-001-SUB-01` | Implement DAG schema and planner validation | `MOD-ORCH-001` | `DONE` | `M7-ORCH-001` |
| `M7-ORCH-001-SUB-02` | Add planner DAG scheduling and failure propagation tests | `MOD-ORCH-001` | `DONE` | `M7-ORCH-001-SUB-01` |


| `M7-ORCH-002` | Specialist Agent Contracts & Verification Gates | `MOD-ORCH-002` | `DONE` | `M7-ORCH-001` |
| `M7-ORCH-002-SUB-01` | Implement specialist contracts and verifier gate | `MOD-ORCH-002` | `DONE` | `M7-ORCH-002` |
| `M7-ORCH-002-SUB-02` | Add agent schema validation and verifier adversarial tests | `MOD-ORCH-002` | `DONE` | `M7-ORCH-002-SUB-01` |


| `M7-ORCH-003` | Cycle Detection, Recursion Ceiling & Budget Governors | `MOD-ORCH-003` | `DONE` | `M7-ORCH-002` |
| `M7-ORCH-003-SUB-01` | Enforce cycle detection and recursion/resource ceilings | `MOD-ORCH-003` | `DONE` | `M7-ORCH-003` |
| `M7-ORCH-003-SUB-02` | Add recursion ceiling and resource budget stress tests | `MOD-ORCH-003` | `DONE` | `M7-ORCH-003-SUB-01` |


---

## Milestone M8: Adaptive Local Model Execution & Resource Governor (Layer 9 & Boundary I)
**Status:** `DONE`

| Task ID | Task Name | Module | Status | Dependencies |
| :--- | :--- | :--- | :--- | :--- |
| `M8-EXEC-001` | Hardware Telemetry & Headroom Budgeting Engine | `MOD-EXEC-001` | `DONE` | `M7-ORCH-003` |
| `M8-EXEC-001-SUB-01` | Implement hardware telemetry and headroom budgeting engine | `MOD-EXEC-001` | `DONE` | `M8-EXEC-001` |
| `M8-EXEC-001-SUB-02` | Add hardware telemetry integration and allocation tests | `MOD-EXEC-001` | `DONE` | `M8-EXEC-001-SUB-01` |
| `M8-EXEC-002` | Selective Weight Offloading & Activation Swapping | `MOD-EXEC-002` | `DONE` | `M8-EXEC-001` |
| `M8-EXEC-002-SUB-01` | Implement selective weight offloading and activation swapping | `MOD-EXEC-002` | `DONE` | `M8-EXEC-002` |
| `M8-EXEC-002-SUB-02` | Add offloading latency and activation swapping benchmarks | `MOD-EXEC-002` | `DONE` | `M8-EXEC-002-SUB-01` |
| `M8-EXEC-003` | Adaptive Task Routing & Degradation Fallbacks | `MOD-EXEC-003` | `DONE` | `M8-EXEC-002` |
| `M8-EXEC-003-SUB-01` | Implement adaptive task routing and degradation fallbacks | `MOD-EXEC-003` | `DONE` | `M8-EXEC-003` |
| `M8-EXEC-003-SUB-02` | Add route selection accuracy and graceful degradation tests | `MOD-EXEC-003` | `DONE` | `M8-EXEC-003-SUB-01` |

---

## Milestone M9: Feedback, Error Taxonomy & Policy Learning
**Status:** `DONE`

| Task ID | Task Name | Module | Status | Dependencies |
| :--- | :--- | :--- | :--- | :--- |
| `M9-EVAL-001` | Benchmark Runner, Regression Gates & Error Taxonomy | `MOD-EVAL-001` | `DONE` | `M8-EXEC-003` |
| `M9-EVAL-001-SUB-01` | Implement versioned benchmark runner and regression gate | `MOD-EVAL-001` | `DONE` | `M9-EVAL-001` |
| `M9-EVAL-001-SUB-02` | Add regression thresholds and benchmark report serialization tests | `MOD-EVAL-001` | `DONE` | `M9-EVAL-001-SUB-01` |
| `M9-EVAL-002` | Expert Feedback & Hard-Negative Mining | `MOD-EVAL-002` | `DONE` | `M9-EVAL-001` |
| `M9-EVAL-002-SUB-01` | Implement review feedback and hard-negative provenance | `MOD-EVAL-002` | `DONE` | `M9-EVAL-002` |
| `M9-EVAL-002-SUB-02` | Add feedback lineage and evaluation contamination tests | `MOD-EVAL-002` | `DONE` | `M9-EVAL-002-SUB-01` |
| `M9-EVAL-003` | Contextual Bandit Routing Evaluation | `MOD-EVAL-003` | `DONE` | `M9-EVAL-002` |
| `M9-EVAL-003-SUB-01` | Implement contextual routing policy offline evaluation | `MOD-EVAL-003` | `DONE` | `M9-EVAL-003` |
| `M9-EVAL-003-SUB-02` | Add contextual policy baseline and reward-validity tests | `MOD-EVAL-003` | `DONE` | `M9-EVAL-003-SUB-01` |

---

## Milestone M10: Reporting & Productization
**Status:** `DONE`

| Task ID | Task Name | Module | Status | Dependencies |
| :--- | :--- | :--- | :--- | :--- |
| `M10-PROD-001` | Evidence-Anchored Structured Research Report Generator | `MOD-PROD-001` | `DONE` | `M9-EVAL-003` |
| `M10-PROD-001-SUB-01` | Define structured report schema and evidence gate | `MOD-PROD-001` | `DONE` | `M10-PROD-001` |
| `M10-PROD-001-SUB-02` | Add report assertion-to-evidence coverage gate | `MOD-PROD-001` | `DONE` | `M10-PROD-001-SUB-01` |
| `M10-PROD-002` | Evidence Inspection Interface & Project History | `MOD-PROD-002` | `DONE` | `M10-PROD-001` |
| `M10-PROD-002-SUB-01` | Implement evidence inspection and version lineage | `MOD-PROD-002` | `DONE` | `M10-PROD-002` |
| `M10-PROD-002-SUB-02` | Add lineage navigation and user intervention audit tests | `MOD-PROD-002` | `DONE` | `M10-PROD-002-SUB-01` |
| `M10-PROD-003` | On-Demand Manuscript, Documentation & Release Candidate | `MOD-PROD-003` | `DONE` | `M10-PROD-002` |
| `M10-PROD-003-SUB-01` | Package release candidate and verify fresh environment install | `MOD-PROD-003` | `DONE` | `M10-PROD-003` |
| `M10-PROD-003-SUB-02` | Add fresh environment installation and end-to-end release checks | `MOD-PROD-003` | `DONE` | `M10-PROD-003-SUB-01` |

---

## Detailed Task Specifications for Milestone M1

### Task `M1-DATA-001`: Corpus Manifest & Data Contract Schema
- **Objective:** Implement typed Python schemas and validation logic for `ValidatedCorpusItem`, `CorpusManifest`, `LicenseType` enum, and dataset split metadata.
- **Why Needed:** Required boundary contract for Layer 0 (`MOD-CORPUS-001`) before any text processing logic is written.
- **In Scope:**
  - `src/laris/layers/layer0_corpus/schemas.py`: dataclasses and enums.
  - Verification of license compliance against permitted open-access licenses (`CC-BY`, `CC-BY-SA`, `Apache-2.0`, `MIT`, `arXiv non-exclusive`).
  - Unit tests in `tests/unit/test_corpus_schemas.py`.
- **Out of Scope:** External data fetching, PDF layout parsing, network requests.
- **Dependencies:** `M0-SPEC-001`.
- **Target Files:**
  - `src/laris/layers/layer0_corpus/__init__.py`
  - `src/laris/layers/layer0_corpus/schemas.py`
  - `tests/unit/test_corpus_schemas.py`
- **Acceptance Criteria:**
  1. `CorpusManifest` rejects unknown licenses or missing document checksums.
  2. All models instantiate with strict type enforcement.
  3. 100% of unit tests pass via `python3 -m unittest`.
  4. Zero new external dependencies.

---

### Task `M1-DATA-002`: Deterministic Text & Math Normalizer
- **Objective:** Implement pure Python deterministic text sanitization preserving scientific formulas, Unicode math symbols, and SI units.
- **Dependencies:** `M1-DATA-001`.
- **Acceptance Criteria:**
  1. Normalizes fullwidth characters, invisible whitespace, and broken ligatures (`fi`, `fl`, `ffi`).
  2. Preserves LaTeX math expressions (`$...$` and `$$...$$`) and Greek symbols intact.
  3. Standardizes scientific unit spacings (e.g. `14GHz` $\rightarrow$ `14 GHz`).
  4. Unit test suite passes with zero regressions on edge-case corpus samples.

---

### Task `M1-DATA-003`: Content Hashing & Deduplication Engine
- **Objective:** Implement exact SHA-256 content identity and MinHash/SimHash near-duplicate detection for preprints vs camera-ready papers.
- **Dependencies:** `M1-DATA-002`.
- **Acceptance Criteria:**
  1. Computes deterministic document SHA-256 hashes based on normalized text.
  2. Flags exact duplicates with 100% precision.
  3. Identifies near-duplicates with configurable Jaccard similarity threshold.

---

### Task `M1-DATA-004`: Leakage-Proof Dataset Partition Engine
- **Objective:** Partition ingested literature into Train/Validation/Test splits strictly grouped by document and author boundaries.
- **Dependencies:** `M1-DATA-003`.
- **Acceptance Criteria:**
  1. Verifies that zero text from the same document or author group appears in both Train and Test.
  2. Generates immutable split manifests with record counts and cryptographic hashes.

---

### Task `M1-DATA-005`: Ingestion Verification & Synthetic Test Fixtures
- **Objective:** End-to-end integration test of Layer 0 pipeline using small synthetic scientific documents.
- **Dependencies:** `M1-DATA-004`.
- **Acceptance Criteria:**
  1. Pipeline executes end-to-end on synthetic fixtures without error.
  2. Generates compliant `data/processed/` directory structure with gitkeep protection.

---

## Detailed Task Specifications for Milestone M2

### Task `M2-LANG-001`: Scientific Tokenizer & Vocabulary Pipeline
- **Objective:** Train and validate a domain-specific BPE/WordPiece tokenizer tailored for scientific text, preserving mathematical tokens, Greek letters, and SI units.
- **Module:** `MOD-LANG-001` (Boundary B).
- **Dependencies:** `M1-DATA-005`.
- **Acceptance Criteria:**
  1. Preserves LaTeX math symbols and Greek letters as atomic or consistent subwords without breaking into uninterpretable fragments.
  2. Measures token fertility on scientific text vs standard general-domain vocabularies (e.g. fertility $\le 1.35$ tokens/word on STEM benchmark).
  3. Generates immutable vocabulary artifacts with canonical hashes.

---

### Task `M2-LANG-002`: Compact Sentence Encoder & Retrieval Benchmark
- **Objective:** Provide a lightweight, local scientific embedding model fitting comfortably within the $\le 1.0$ GB VRAM memory envelope for semantic retrieval.
- **Module:** `MOD-LANG-002` (Boundary B).
- **Dependencies:** `M2-LANG-001`.
- **Acceptance Criteria:**
  1. Runs entirely offline with zero external network calls.
  2. Peak GPU allocation stays strictly $\le 1.0$ GB VRAM.
  3. Demonstrates superior retrieval accuracy over exact-match lexical BM25 baseline on scientific query benchmarks.

---

### Task `M2-LANG-003`: Language Foundation Training Reproducibility & Artifacts
- **Objective:** Ensure end-to-end training and serialization reproducibility for Layer 1 language representations.
- **Module:** `MOD-LANG-003` (Boundary B).
- **Dependencies:** `M2-LANG-002`.
- **Acceptance Criteria:**
  1. Checkpoint integrity and lineage recorded in machine-readable manifests.
  2. Deterministic execution produces bitwise identical evaluation scores across runs given the same seed.
  3. Complies with hardware budget safety constraints ($\le 14.5$ GB VRAM global headroom).

---

## Detailed Task Specifications for Milestone M3

### Task `M3-SEM-001`: Three-Way Scientific NLI
- **Objective:** Implement 3-way Natural Language Inference (Entailment, Contradiction, Neutral) engine tailored for scientific literature.
- **Module:** `MOD-SEM-001` (Boundary C).
- **Dependencies:** `M2-LANG-003`.
- **Acceptance Criteria:**
  1. Class probabilities sum to $1.0 \pm 10^{-5}$ and uncertainty lies in $[0.0, 1.0]$.
  2. Invariant preserved: high topical/lexical similarity cannot override logical contradiction.
  3. Strict input validation rejecting empty or malformed inputs with canonical error semantics.

---

### Task `M3-SEM-002`: Semantic Equivalence, Coreference & Discourse Relations
- **Objective:** Resolve scientific coreference and parse inter-sentential discourse relations (e.g. causal, contrast, concessive).
- **Module:** `MOD-SEM-001` (Boundary C).
- **Dependencies:** `M3-SEM-001`.
- **Acceptance Criteria:**
  1. Coreference chains trace entity mentions to source document coordinates.
  2. Discourse relations parse with verified provenance and uncertainty calibration.

---

### Task `M3-SEM-003`: NLI Calibration & Contradiction Evaluation
- **Objective:** Construct versioned scientific NLI benchmarks and evaluate probability calibration (ECE) and contradiction detection.
- **Module:** `MOD-SEM-001` (Boundary C).
- **Dependencies:** `M3-SEM-002`.
- **Acceptance Criteria:**
  1. Strict train/val/test split isolation with zero entity/author leakage.
  2. Diagnostic failure analysis and calibration metrics reported reproducible across runs.

---

## Detailed Task Specifications for Milestone M4

### Task `M4-SCINLP-001`: Scientific Entity & Formula Extractor
- **Objective:** Extract domain-specific scientific entities and LaTeX mathematical formulas with precise character offsets and document coordinates.
- **Module:** `MOD-SCINLP-001` (Boundary D).
- **Dependencies:** `M3-SEM-003`.
- **Acceptance Criteria:**
  1. Identifies scientific entities (genes, compounds, materials, metrics, constants).
  2. Preserves and validates LaTeX formulas without syntax distortion.
  3. Every extracted entity includes verified character coordinate offsets.

---

### Task `M4-SCINLP-002`: Heading-Aware Section Segmenter & Discourse Hierarchy
- **Objective:** Parse scientific literature into structured section hierarchies with heading awareness.
- **Module:** `MOD-SCINLP-002` (Boundary D).
- **Dependencies:** `M4-SCINLP-001`.
- **Acceptance Criteria:**
  1. Reconstructs document outline hierarchy (H1-H4, Abstract, Methods, Results, Discussion).
  2. Maps inter-section discourse relationships and cross-references.

---

### Task `M4-SCINLP-003`: STEM Unit & Quantitative Relation Normalizer
- **Objective:** Normalize STEM quantities, dimensional units, and numerical relations into standardized representations.
- **Module:** `MOD-SCINLP-003` (Boundary D).
- **Dependencies:** `M4-SCINLP-002`.
- **Acceptance Criteria:**
  1. Standardizes SI units and compound dimensional units with zero precision loss.
  2. Parses numerical intervals, uncertainties, and quantitative comparisons.

---

## Detailed Task Specifications for Milestone M5

### Task `M5-EVID-001`: Versioned Evidence Graph Construction
- **Objective:** Define and implement the persistent, heterogeneous evidence knowledge graph linking documents, authors, methods, datasets, metrics, results, claims, and limitations.
- **Module:** `MOD-GRAPH-001` (Boundary F).
- **Dependencies:** `M4-SCINLP-003`.
- **Subtasks:**
  - `M5-EVID-001-SUB-01`: Define versioned evidence graph nodes, edges and persistence interface.
  - `M5-EVID-001-SUB-02`: Add graph persistence, migration and edge provenance tests.
- **Acceptance Criteria:**
  1. Author-asserted and machine-inferred edges remain strictly distinct via mandatory `is_inferred` flag and provenance anchoring.
  2. Abstract persistence interface (`BaseGraphPersistenceAdapter`) decoupled from concrete storage engine.
  3. Schema migration and version contracts supported with deterministic serialization.
  4. Embedded architecture with zero external database server dependency.

---

### Task `M5-RETR-001`: Hybrid Lexical-Dense Retrieval Engine
- **Objective:** Implement modular multi-channel retrieval combining lexical BM25, dense vector,
  and graph traversal adapters with Reciprocal Rank Fusion (RRF).
- **Module:** `MOD-GRAPH-001` (Boundary F / Layer 6).
- **Dependencies:** `M5-EVID-001`.
- **Subtasks:**
  - `M5-RETR-001-SUB-01`: Implement lexical retrieval and modular dense/graph adapters.
  - `M5-RETR-001-SUB-02`: Benchmark multi-channel retrieval against single-modality baselines.
- **Acceptance Criteria:**
  1. Lexical, dense, and graph adapters adhere to `BaseRetrievalAdapter` and output `RetrievalCandidate`.
  2. RRF rank combiner produces deterministic unified rankings across differing score scales.
  3. Depth limits enforced on traversal and query expansion ($N \le 5$).
  4. 100% of retrieved items retain valid `EvidenceCoordinate` provenance records.

---

### Task `M5-PROV-001`: Evidence Coordinate Validation & Provenance Tracking
- **Objective:** Verify end-to-end evidence coordinate mapping, audit trail generation, and
  corruption detection across pipeline transformations.
- **Module:** `MOD-GRAPH-001` (Boundary F).
- **Dependencies:** `M5-RETR-001`.
- **Subtasks:**
  - `M5-PROV-001-SUB-01`: Implement end-to-end evidence coordinate mapping & validation.
  - `M5-PROV-001-SUB-02`: Add coordinate corruption detection and audit trail regression tests.
- **Acceptance Criteria:**
  1. 100% of retrieved evidence items retain verifiable character offsets down to sentence index.
  2. Coordinate tampering or corruption triggers `ProvenanceViolationError`.

---

## Detailed Task Specifications for Milestone M6

### Task `M6-GAP-001`: Cross-Paper Experimental Comparison & Conflict Detection
- **Objective:** Align methods, conditions, metrics and findings across studies; identify contradictions without conflating incomparable experiments.
- **Module:** `MOD-GAP-001` (Boundary G / Layer 7).
- **Dependencies:** Milestone M5 Exit Gate (`M5-PROV-001`).
- **Subtasks:**
  - `M6-GAP-001-SUB-01`: Implement comparative matrix and condition-aware contradiction engine.
  - `M6-GAP-001-SUB-02`: Add comparison matrix fixtures and synthetic contradiction benchmarks.
- **Acceptance Criteria:**
  1. Comparative matrix records comparability caveats across dataset, split, baseline, and metric bounds.
  2. Conflict detection citations anchor 100% to verified `EvidenceCoordinate` records.
  3. Synthetic benchmark accurately distinguishes genuine empirical contradictions from incomparable experimental setups.

---

### Task `M6-GAP-002`: Twelve-Class Research Gap Typology Classifier
- **Objective:** Implement gap categories and multidimensional scoring for novelty, grounding, feasibility, significance, and uncertainty.
- **Module:** `MOD-GAP-001` (Boundary G / Layer 7).
- **Dependencies:** `M6-GAP-001`.
- **Subtasks:**
  - `M6-GAP-002-SUB-01`: Implement 12-class gap taxonomy and scoring schema.
  - `M6-GAP-002-SUB-02`: Add gap typology evaluation fixtures and gold set.
- **Acceptance Criteria:**
  1. Every score has explicit inputs and [0.0, 1.0] scale.
  2. Bounded corpus strictly prevents global novelty claims.
  3. Taxonomy fixtures and calibration evaluation report exist.

---

### Task `M6-GAP-003`: Adversarial Self-Refutation and Counter-Evidence Discovery
- **Objective:** Search counter-evidence for candidate gaps and produce testable hypotheses with empirical validation protocols.
- **Module:** `MOD-GAP-001` (Boundary G / Layer 7).
- **Dependencies:** `M6-GAP-002`.
- **Subtasks:**
  - `M6-GAP-003-SUB-01`: Implement counter-evidence search and validation-plan contract.
  - `M6-GAP-003-SUB-02`: Add counter-evidence rejection and validation-plan tests.
- **Acceptance Criteria:**
  1. Refuted candidates are rejected from active gap recommendations.
  2. Unresolved counter-evidence elevates epistemic uncertainty.
  3. Formulated validation plans contain measurable variables, datasets, baselines, and falsification criteria.

---

## Detailed Task Specifications for Milestone M7

### Task `M7-ORCH-001`: Query Planner, DAG Runtime & Supervisor
- **Objective:** Plan research goals into dependency DAGs, supervise execution, and record execution trace/resource telemetry.
- **Module:** `MOD-ORCH-001` (Boundary H / Layer 8).
- **Dependencies:** Milestone M6 Exit Gate (`M6-GAP-003`).
- **Subtasks:**
  - `M7-ORCH-001-SUB-01`: Implement DAG schema and planner validation.
  - `M7-ORCH-001-SUB-02`: Add planner DAG scheduling and failure propagation tests.
- **Acceptance Criteria:**
  1. DAG schema validates acyclicity, node dependencies, and parameter bindings.
  2. Planner schedules independent nodes concurrently and propagates node failure and cancellation cleanly.
  3. Supervisor logs deterministic execution traces with step-level duration and token budget tracking.

---

### Task `M7-ORCH-002`: Specialist Agent Contracts & Verification Gates
- **Objective:** Define isolated specialist agent execution contracts and verifier validation gates.
- **Module:** `MOD-ORCH-002` (Boundary H / Layer 8).
- **Dependencies:** `M7-ORCH-001`.
- **Subtasks:**
  - `M7-ORCH-002-SUB-01`: Implement specialist contracts and verifier gate.
  - `M7-ORCH-002-SUB-02`: Add agent schema validation and verifier adversarial tests.
- **Acceptance Criteria:**
  1. Specialist agents adhere to typed input/output schemas with isolated context windows.
  2. Verification gate validates agent outputs against schema invariants and rejects invalid state transitions.

---

### Task `M7-ORCH-003`: Cycle Detection, Recursion Ceiling & Budget Governors
- **Objective:** Enforce cyclic loop prevention, hard recursion ceiling ($N \le 10$), and budget governors across multi-agent execution.
- **Module:** `MOD-ORCH-003` (Boundary H / Layer 8).
- **Dependencies:** `M7-ORCH-002`.
- **Subtasks:**
  - `M7-ORCH-003-SUB-01`: Enforce cycle detection and recursion/resource ceilings.
  - `M7-ORCH-003-SUB-02`: Add recursion ceiling and resource budget stress tests.
- **Acceptance Criteria:**
  1. Cycle detector catches repeating agent sequences and terminates execution with `CycleDetectedError`.
  2. Hard recursion ceiling enforces $N \le 10$ steps maximum per sub-goal.
  3. Budget governors track token and step usage, preemptively aborting runaway agent execution.

---

## Detailed Task Specifications for Milestone M8

### Task `M8-EXEC-001`: Hardware Telemetry & Headroom Budgeting Engine
- **Objective:** Implement real-time GPU/CPU memory and compute headroom monitoring for the RTX 5070 Ti (16 GB total, $\le 14.5$ GB allocation limit).
- **Module:** `MOD-EXEC-001` (Boundary I / Layer 9).
- **Dependencies:** Milestone M7 Exit Gate (`M7-ORCH-003`).
- **Subtasks:**
  - `M8-EXEC-001-SUB-01`: Implement hardware telemetry and headroom budgeting engine.
  - `M8-EXEC-001-SUB-02`: Add hardware telemetry integration and allocation tests.
- **Acceptance Criteria:**
  1. Telemetry engine samples VRAM and system memory with sub-millisecond overhead.
  2. Headroom governor raises `HardwareBudgetExceededError` if projected allocation exceeds 14.5 GB VRAM ceiling.
  3. Memory reservations dynamically adjust based on active batch size and context window length.

---

### Task `M8-EXEC-002`: Selective Weight Offloading & Activation Swapping
- **Objective:** Implement selective layer/weight offloading between GPU VRAM and host RAM to fit multi-model ensembles within 16 GB hardware budget.
- **Module:** `MOD-EXEC-002` (Boundary I / Layer 9).
- **Dependencies:** `M8-EXEC-001`.
- **Subtasks:**
  - `M8-EXEC-002-SUB-01`: Implement selective weight offloading and activation swapping.
  - `M8-EXEC-002-SUB-02`: Add offloading latency and activation swapping benchmarks.
- **Acceptance Criteria:**
  1. Inactive model weights offloaded asynchronously to host RAM without blocking active stream.
  2. Activation checkpointing swaps intermediate activations when VRAM headroom drops below 1.5 GB safety threshold.

---

### Task `M8-EXEC-003`: Adaptive Task Routing & Degradation Fallbacks
- **Objective:** Implement dynamic model and specialist routing with graceful quality degradation when memory or latency ceilings are reached.
- **Module:** `MOD-EXEC-003` (Boundary I / Layer 9).
- **Dependencies:** `M8-EXEC-002`.
- **Subtasks:**
  - `M8-EXEC-003-SUB-01`: Implement adaptive task routing and degradation fallbacks.
  - `M8-EXEC-003-SUB-02`: Add route selection accuracy and graceful degradation tests.
- **Acceptance Criteria:**
  1. Router selects optimal model/heuristic based on prompt complexity and telemetry headroom.
  2. Graceful degradation cascade falls back from dense neural encoders to BM25/lexical matching on memory pressure.

---

## Detailed Task Specifications for Milestone M9

### Task `M9-EVAL-001`: Benchmark Runner, Regression Gates & Error Taxonomy
- **Objective:** Implement versioned capability benchmark execution, regression comparisons and structured scientific error records.
- **Module:** `MOD-EVAL-001` (Boundary J / Layer 10).
- **Dependencies:** Milestone M8 Exit Gate (`M8-EXEC-003`).
- **Subtasks:**
  - `M9-EVAL-001-SUB-01`: Implement versioned benchmark runner and regression gate.
  - `M9-EVAL-001-SUB-02`: Add regression thresholds and benchmark report serialization tests.
- **Acceptance Criteria:**
  1. Frozen evaluation sets remain isolated from training data.
  2. Reproducible pass/fail regression comparison against previous release baselines.
  3. Structured error records distinguish provenance, epistemic, and extraction failures.

---

### Task `M9-EVAL-002`: Expert Feedback & Hard-Negative Mining
- **Objective:** Capture reviewed annotations and mine hard negatives without contaminating evaluation/test sets.
- **Module:** `MOD-EVAL-002` (Boundary J / Layer 10).
- **Dependencies:** `M9-EVAL-001`.
- **Subtasks:**
  - `M9-EVAL-002-SUB-01`: Implement review feedback and hard-negative provenance.
  - `M9-EVAL-002-SUB-02`: Add feedback lineage and evaluation contamination tests.
- **Acceptance Criteria:**
  1. Feedback lineage is recorded with immutable cryptographic provenance.
  2. Evaluation/test splits are strictly protected against contamination during hard-negative mining.
  3. Data, weight, and policy update paths remain isolated.

---

### Task `M9-EVAL-003`: Contextual Bandit Routing Evaluation
- **Objective:** Prototype and evaluate contextual routing policies against heuristic and deterministic baselines.
- **Module:** `MOD-EVAL-003` (Boundary J / Layer 10).
- **Dependencies:** `M9-EVAL-002`.
- **Subtasks:**
  - `M9-EVAL-003-SUB-01`: Implement contextual routing policy offline evaluation.
  - `M9-EVAL-003-SUB-02`: Add contextual policy baseline and reward-validity tests.
- **Acceptance Criteria:**
  1. Baseline comparisons measure trade-offs between latency and output quality.
  2. Pure offline simulation; no uncontrolled online self-training.
  3. Verified reward validity before policy activation.

---

## Detailed Task Specifications for Milestone M10

### Task `M10-PROD-001`: Evidence-Anchored Structured Research Report Generator
- **Objective:** Generate default structured reports with claims, evidence, confidence, limitations, and source coordinates.
- **Module:** `MOD-PROD-001` (Layer 11 / Productization).
- **Dependencies:** Milestone M9 exit gate.
- **Subtasks:**
  - `M10-PROD-001-SUB-01`: Define structured report schema and evidence gate.
  - `M10-PROD-001-SUB-02`: Add report assertion-to-evidence coverage gate.
- **Acceptance Criteria:**
  1. Every factual assertion is traceable to valid evidence coordinates.
  2. Missing evidence is explicitly reported with zero hallucination.
  3. Schema validation and integration tests pass.

---

### Task `M10-PROD-002`: Evidence Inspection Interface & Project History
- **Objective:** Provide inspection of source spans, evidence lineage, corpus/run/report versions, and user accept/modify/reject controls.
- **Module:** `MOD-PROD-002` (Layer 11 / Productization).
- **Dependencies:** `M10-PROD-001`.
- **Subtasks:**
  - `M10-PROD-002-SUB-01`: Implement evidence inspection and version lineage.
  - `M10-PROD-002-SUB-02`: Add lineage navigation and user intervention audit tests.
- **Acceptance Criteria:**
  1. Inspection interface/API is local-first.
  2. Lineage navigation resolves source spans across report versions.
  3. User interventions are fully versioned and auditable.

---

### Task `M10-PROD-003`: On-Demand Manuscript, Documentation & Release Candidate
- **Objective:** Add explicitly requested manuscript composition, user docs, packaging, and end-to-end release verification.
- **Module:** `MOD-PROD-003` (Layer 11 / Packaging).
- **Dependencies:** `M10-PROD-001`, `M10-PROD-002`.
- **Subtasks:**
  - `M10-PROD-003-SUB-01`: Package release candidate and verify fresh environment install.
  - `M10-PROD-003-SUB-02`: Add fresh environment installation and end-to-end release checks.
- **Acceptance Criteria:**
  1. Manuscript composition is strictly opt-in.
  2. Full integration and regression test suite passes.
  3. Installation and build instructions work in clean environment.
  4. Release notes and operational boundaries are documented.

---

## Milestone M11: Staged Learning Pipeline Governance, Dataset Acquisition & Domain Refactoring
**Status:** `IN_PROGRESS`

| Task ID | Task Name | Module | Status | Dependencies |
| :--- | :--- | :--- | :--- | :--- |
| `M11-TRAIN-000` | Staged Model Learning Pipeline Governance | System / Gov | `DONE` | Milestone M10 Exit Gate |
| `M11-TRAIN-000-SUB-01` | Model training vs deterministic baseline audit | Gov | `DONE` | `M11-TRAIN-000` |
| `M11-TRAIN-000-SUB-02` | Staged learning specification, gates & scalable sample floors | Gov | `DONE` | `M11-TRAIN-000-SUB-01` |
| `M11-DATA-001` | Dataset Inventory, Licensing, Eligible Acquisition & S2ORC Plan | Corpus / Data | `DONE` | `M11-TRAIN-000` |
| `M11-DATA-001-SUB-01` | Dataset inventory, license matrix, En/Vi separation & LARIS-GOLD spec | Corpus | `DONE` | `M11-DATA-001` |
| `M11-DATA-001-SUB-02` | Eligible dataset acquisition, checksum/schema verification & S2ORC bounded audit | Corpus | `DONE` | `M11-DATA-001-SUB-01` |
| `M11-ARCH-001` | Refactor Numbered Layers into Domain-Based Packages | Architecture | `DONE` | `M11-TRAIN-000` |
| `M11-ARCH-001-SUB-01` | Target domain layout design, migration plan & ADR-011 | Architecture | `DONE` | `M11-ARCH-001` |
| `M11-ARCH-001-SUB-02` | Package migration, compatibility shims, import updates & test suite pass | Core | `DONE` | `M11-ARCH-001-SUB-01` |

---

### Task `M11-TRAIN-000`: Staged Model Learning Pipeline Governance
- **Objective:** Establish the authoritative 6-stage model learning sequence, stage boundaries, English/Vietnamese separate tracks, model responsibilities (Model 1, Model 2, Model 3), scalable sample floors ($\ge 1\text{M}$ each), and strict non-training governance.
- **Module:** Governance & System Planning.
- **Dependencies:** Milestone M10 Exit Gate (`M10-PROD-003`).
- **Subtasks:**
  - `M11-TRAIN-000-SUB-01`: Model training vs deterministic baseline audit and reality check (`DOC-RES-AUDIT-001`).
  - `M11-TRAIN-000-SUB-02`: Staged learning pipeline specification, model separation, and scalable sample floors (`DOC-PLAN-TRAIN-001`).
- **Acceptance Criteria:**
  1. Implementation audit explicitly demonstrates that zero neural training has been run and distinguishes deterministic baselines from trained models.
  2. Learning sequence strictly enforces: Natural Language $\rightarrow$ Scientific Language $\rightarrow$ Scientific OCR $\rightarrow$ OCR-Coupled Manuscript $\rightarrow$ LARIS Integration.
  3. Minimum floor of 1,000,000 samples for Model 1 and Model 2 defined by granular units (not caps or adequacy guarantees).
  4. English and Vietnamese tracked as independent curricula and evaluation benchmarks.
  5. Zero model training executed during this milestone.

---

### Task `M11-DATA-001`: Dataset Inventory, Licensing, Eligible Acquisition & S2ORC Plan
- **Objective:** Inventory priority datasets, verify licensing and redistribution terms, acquire eligible sources, verify checksums and schemas, perform S2ORC bounded STEM subset audit ($<20$ GB, $<20\text{M}$ samples), and define LARIS-GOLD specification.
- **Module:** `MOD-CORPUS-001` / Data Governance.
- **Dependencies:** `M11-TRAIN-000`.
- **Subtasks:**
  - `M11-DATA-001-SUB-01`: Dataset inventory, license matrix, En/Vi separation & LARIS-GOLD spec.
  - `M11-DATA-001-SUB-02`: Eligible dataset acquisition, checksum/schema verification & S2ORC bounded audit.
- **Acceptance Criteria:**
  1. Inventory covers all priority candidates with canonical sources, versions, and verified licenses.
  2. Eligible datasets acquired responsibly and verified for integrity, checksums, and schema.
  3. S2ORC evaluated with strict hard caps ($<20$ GB payload, $<20\text{M}$ samples) or skipped if compliant STEM subset is blocked.
  4. LARIS-GOLD specification established without fabricating annotations.
  5. Zero model training run on acquired data.

---

### Task `M11-ARCH-001`: Refactor Numbered Layers into Domain-Based Packages
- **Objective:** Reorganize `src/laris/layers/layerX_*` into clean domain packages (`corpus`, `language`, `scientific`, `retrieval`, `reasoning`, `orchestration`, `execution`, `evaluation`, `reporting`) while preserving the conceptual 12-layer architecture in documentation.
- **Module:** Architecture & Package Structure.
- **Dependencies:** `M11-TRAIN-000`.
- **Subtasks:**
  - `M11-ARCH-001-SUB-01`: Target domain layout design, migration plan & ADR-011.
  - `M11-ARCH-001-SUB-02`: Package migration, compatibility shims, import updates & test suite pass.
- **Acceptance Criteria:**
  1. Numbered layer folders replaced by domain packages as primary source organization.
  2. Transparent compatibility shims provided in `src/laris/layers/`.
  3. All 898+ unit and contract tests pass with zero regressions.
  4. Ruff, mypy, and docs validation pass with zero errors.
  5. 12-layer conceptual architecture remains documented and preserved.










