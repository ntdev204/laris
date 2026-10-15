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


| `M6-GAP-001` | Cross-Paper Experimental Comparison & Conflict Detection | `MOD-GAP-001` | `IN_PROGRESS` | `M5-PROV-001` |
| `M6-GAP-001-SUB-01` | Implement comparative matrix and condition-aware contradiction engine | `MOD-GAP-001` | `DONE` | `M6-GAP-001` |
| `M6-GAP-001-SUB-02` | Add comparison matrix fixtures and synthetic contradiction benchmarks | `MOD-GAP-001` | `IN_REVIEW` | `M6-GAP-001-SUB-01` |


| `M6-GAP-002` | Twelve-Class Research Gap Typology Classifier | `MOD-GAP-001` | `READY` | `M6-GAP-001` |


| `M6-GAP-003` | Adversarial Self-Refutation and Counter-Evidence Discovery | `MOD-GAP-001` | `BLOCKED` | `M6-GAP-002` |

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




