---
document_id: "DOC-REL-001"
title: "LARIS v0.1.0-rc1 Release Notes & Operational Boundaries"
document_type: "report"
status: "APPROVED"
version: "0.1.0"
created_at: "2026-10-16"
updated_at: "2026-10-16"
owner: "LARIS Core Architecture Team"
reviewers:
  - "LARIS Maintainer"
source_of_truth: true
related_documents:
  - "docs/DOCUMENTATION_STANDARD.md"
  - "docs/plans/IMPLEMENTATION_ROADMAP.md"
  - "docs/specifications/REPORT_SPECIFICATION.md"
  - "docs/architecture/LAYER_ARCHITECTURE.md"
decision_references:
  - "ADR-001"
  - "ADR-002"
  - "ADR-004"
  - "ADR-006"
  - "ADR-008"
  - "ADR-010"
change_summary: "Initial release notes for v0.1.0-rc1 packaging, operational boundaries, and verification."
---

# LARIS v0.1.0-rc1 Release Notes & Operational Boundaries

## 1. Executive Summary

LARIS (Local Autonomous Research Intelligence System) v0.1.0-rc1 represents the initial release candidate completing the scientific intelligence roadmap from bootstrap through productization (Milestones M0 through M10).

LARIS operates as a local-first scientific intelligence instrument designed to synthesize findings, evaluate empirical contradictions, discover calibrated research gaps, and produce auditable, evidence-anchored structured research reports.

---

## 2. Core Architectural Capabilities

### Layer 0: Corpus & Data Foundation
- Cryptographic SHA-256 deduplication and deterministic Unicode/LaTeX normalization.
- Author-isolated, leakage-proof dataset partitioning (`TRAIN`, `VAL`, `TEST`).
- Strict license validation enforcing open-access research reuse.

### Layer 1 & 2: Language Foundation & Semantic Intelligence
- In-house compact tokenization and dense sentence embeddings ($D=384$).
- Three-way Natural Language Inference (Entailment, Neutral, Contradiction).
- Calibrated uncertainty scoring with fail-closed epistemic guarantees.

### Layer 3: Scientific NLP & Discourse Intelligence
- Heading-agnostic limitation and boundary condition detection.
- STEM unit normalizer and dimensional analysis engine.
- Structured scientific entity and formula parsing.

### Layer 5 & 6: Hybrid RAG & Evidence Graph
- Heterogeneous SQLite graph persistence linking documents, methods, and claims.
- Reciprocal Rank Fusion (RRF) combining dense neural retrieval and lexical BM25.
- Bitwise evidence coordinate verification with physical page and character offsets.

### Layer 7: Research Reasoning Engine
- Comparative experimental matrix synthesis.
- Condition-aware contradiction and discrepancy analysis.
- Twelve-class canonical research gap taxonomy classifier.
- Calibrated 5-dimensional gap scoring (Novelty, Grounding, Feasibility, Significance, Uncertainty).
- Actionable empirical validation protocol generator.

### Layer 8 & 9: Agent Orchestration & Adaptive Local Execution
- Directed acyclic graph (DAG) task planner with cyclic execution prevention.
- Hard recursion depth ceiling ($N \le 10$ steps).
- Hardware telemetry monitor enforcing the $\le 14.5$ GB VRAM safety threshold on the RTX 5070 Ti.
- Dynamic task routing with graceful degradation fallbacks.

### Layer 10: Evaluation, Feedback & Learning
- Automated continuous regression benchmark runner across 8 capability dimensions.
- Cryptographic feedback lineage and hard-negative mining.
- Offline contextual bandit routing policy simulator with verified reward environments.

### Layer 11: Reporting, Inspection & Productization
- Structured Research Report generator with seven mandatory canonical sections.
- Strict and permissive evidence gates preventing unanchored factual assertions.
- Local-first Evidence Inspector with source span context extraction.
- Corpus, run, and report version lineage registry with ancestor DAG navigation.
- Append-only cryptographic SHA-256 audit log for human user interventions (accept, modify, reject).
- On-Demand Academic Manuscript Composer (IMRAD format, LaTeX & Markdown export).

---

## 3. Fresh Environment Installation & Quickstart

### Prerequisites
- Linux OS (tested on Ubuntu 22.04 LTS / 24.04 LTS).
- Python 3.10, 3.11, or 3.12.
- Local hardware: $\ge 16$ GB Host RAM; NVIDIA GPU with $\ge 16$ GB VRAM (RTX 5070 Ti recommended).

### Fresh Setup
```bash
# Clone repository
git clone https://github.com/ntdev204/laris.git
cd laris

# Create virtual environment
python3 -m venv ./laris-env
source ./laris-env/bin/activate

# Install package with development tools
pip install --upgrade pip
pip install -e ".[dev]"

# Run full test suite
pytest -v --cov=laris
```

---

## 4. Operational Boundaries & Known Limitations

1. **Hardware Ceiling:**
   Total GPU VRAM allocation is strictly governed at $\le 14.5$ GB to prevent OOM errors. Exceeding this budget triggers `HardwareBudgetExceededError` or initiates dynamic LRU offloading to host RAM.

2. **Pure Local-First Execution:**
   LARIS executes 100% locally and does not perform runtime network requests, external API calls, or cloud LLM queries.

3. **Opt-In Manuscript Drafting:**
   Academic manuscript generation is strictly an on-demand secondary deliverable. The primary and default deliverable is always the seven-section Structured Research Report.
