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
| `BOOT-DEV-001-SUB-03` | CI checks & PR review enforcement | Issue #113: GitHub Actions CI workflow, PR template. | `IN_PROGRESS` |

---

## Milestone M1: Corpus Ingestion & Data Governance (Layer 0)
**Status:** `IN_PROGRESS`

| Task ID | Task Name | Module | Status | Dependencies |
| :--- | :--- | :--- | :--- | :--- |
| `M1-DATA-001` | Corpus Manifest & Data Contract Schema | `MOD-CORPUS-001` | `IN_PROGRESS` | `M0-SPEC-001` |
| `M1-DATA-001-SUB-01` | Define typed schema fields and invariants | `MOD-CORPUS-001` | `IN_PROGRESS` | `M1-DATA-001` |
| `M1-DATA-001-SUB-02` | Validate manifest invariants and authorization | `MOD-CORPUS-001` | `READY` | `M1-DATA-001-SUB-01` |
| `M1-DATA-002` | Deterministic Text & Math Normalizer | `MOD-CORPUS-001` | `BACKLOG` | `M1-DATA-001` |
| `M1-DATA-003` | Content Hashing & Deduplication Engine | `MOD-CORPUS-001` | `BACKLOG` | `M1-DATA-002` |
| `M1-DATA-004` | Leakage-Proof Dataset Partition Engine | `MOD-CORPUS-001` | `BACKLOG` | `M1-DATA-003` |
| `M1-DATA-005` | Ingestion Verification & Synthetic Test Fixtures | `MOD-CORPUS-001` | `BACKLOG` | `M1-DATA-004` |

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
