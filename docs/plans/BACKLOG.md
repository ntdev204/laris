---
document_id: "DOC-PLAN-BACKLOG-001"
title: "LARIS Engineering Task Backlog & Execution Registry"
document_type: "plan"
status: "DRAFT"
version: "0.2.1"
created_at: "2026-10-15"
updated_at: "2026-10-29"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/plans/ROADMAP.md"
  - "docs/specifications/MODULE_CONTRACTS.md"
decision_references:
  - "ADR-007"
  - "ADR-008"
change_summary: "Moved delivered M1-M10 task specifications to docs/archive; backlog keeps milestone tables and open work."
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
| `M0-GOV-001` | Core Governance & Standards | `DOCUMENTATION.md`, `DOCUMENTATION.md`. | `DONE` |
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
| `M2-LANG-004` | Natural Language Foundation Training Readiness Audit & Curriculum Specification | `MOD-LANG-004` | `DONE` | `M2-LANG-003` |
| `M2-LANG-004-SUB-01` | Ubuntu environment verification and 17-dataset inventory reconciliation | `MOD-LANG-004` | `DONE` | `M2-LANG-004` |
| `M2-LANG-004-SUB-02` | Staged curriculum, from-scratch Transformer spec and #19 artifact lifecycle | `MOD-LANG-004` | `DONE` | `M2-LANG-004-SUB-01` |
| `M2-LANG-005` | Resolve Training Readiness Blockers Before First Training Run | `MOD-LANG-005` | `DONE` | `M2-LANG-004` |
| `M2-LANG-005-SUB-01` | Task-specific dataset partitioners & zero-leakage validation | `MOD-CORPUS-001` | `DONE` | `M2-LANG-005` |
| `M2-LANG-005-SUB-02` | From-scratch bilingual tokenizer pipeline as code | `MOD-LANG-001` | `DONE` | `M2-LANG-005-SUB-01` |
| `M2-LANG-005-SUB-03` | Real randomly initialized neural model & multi-task heads | `MOD-LANG-002` | `DONE` | `M2-LANG-005-SUB-02` |
| `M2-LANG-005-SUB-04` | Bounded profiling, hardware telemetry & #215 config handoff | `MOD-LANG-005` | `DONE` | `M2-LANG-005-SUB-03` |
| `M2-LANG-006` | Centralized Configuration System & Hardcoded-Parameter Audit | `MOD-CONFIG-001` | `DONE` | `M2-LANG-005` |
| `M2-LANG-007-PREP` | Physical Dataset Partitioning and Tokenizer Training Readiness | `MOD-LANG-004` | `DONE` | `M2-LANG-006` |
| `M2-PERF-001` | Optimize Physical Dataset Partitioning for Server Hardware | `MOD-CORPUS-001` | `DONE` | `M2-LANG-007-PREP` |
| `M2-LANG-008` | 512M Architecture Scaling, 14GB VRAM Optimization & Bilingual Dataset Expansion | `MOD-LANG-004` | `DONE` | `M2-PERF-001` |
| `M2-LANG-007` | Natural Language Foundation Training Execution & Benchmark Evaluation | `MOD-LANG-004` | `BLOCKED_ON_APPROVAL` | `M2-LANG-008` |

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

> Detailed per-task specifications for M1–M10 (all delivered) are kept in [docs/archive/BACKLOG_TASK_SPECIFICATIONS.md](../archive/BACKLOG_TASK_SPECIFICATIONS.md).
