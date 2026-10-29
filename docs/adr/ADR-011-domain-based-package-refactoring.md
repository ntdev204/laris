---
document_id: "DOC-ADR-011"
title: "ADR-011: Domain-Based Package Organization and Conceptual Layer Decoupling"
document_type: "adr"
status: "ACCEPTED"
version: "1.0.0"
created_at: "2026-10-16"
updated_at: "2026-10-16"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/archive/IDEA.md"
  - "docs/architecture/LAYER_ARCHITECTURE.md"
  - "docs/architecture/SYSTEM_OVERVIEW.md"
  - "docs/specifications/MODULE_CONTRACTS.md"
decision_references:
  - "ADR-001"
  - "ADR-002"
  - "ADR-005"
  - "ADR-006"
  - "ADR-007"
  - "ADR-008"
change_summary: "Formalized domain-based source reorganization replacing numbered layer directories while preserving conceptual 12-layer architecture."
---

# ADR-011: Domain-Based Package Organization and Conceptual Layer Decoupling

## Metadata
- **ADR ID:** ADR-011
- **Status:** ACCEPTED
- **Date Decided:** 2026-10-16
- **Decision Owner:** LARIS Architecture Team
- **Target Scope:** Entire `src/laris/` package tree, system architecture documentation

---

## 1. Context and Problem Statement

Initially, LARIS source code was partitioned into numbered implementation directories matching the twelve conceptual architecture layers:
`src/laris/layers/layer0_corpus/`, `layer1_language/`, `layer2_semantic/`, `layer3_scinlp/`, `layer4_graph/`, `layer5_graph/`, `layer6_retrieval/`, `layer7_reasoning/`, `layer8_orchestration/`, `layer9_adaptive_execution/`, `layer10_evaluation/`, and `layer11_reporting/`.

While this layout mirrored the initial roadmap, numbered directories introduce several engineering friction points:
1. **Conflation of Concerns:** Conceptual architecture (system data flow and cognitive boundaries) and Python packaging (reusable modules, clean imports, separation of concerns) are distinct concerns. Numbered folder names do not represent domain responsibilities.
2. **Coupling and Refactoring Friction:** Numbered names create artificial barriers to domain evolution, cross-module cohesion, and conventional library usage.
3. **Redundancy:** Layers 4 and 5 were both assigned to the Evidence Graph, leading to artificial alias folders (`layer4_graph/__init__.py`).

In accordance with GitHub Issue #201 ([M11-ARCH-001](https://github.com/ntdev204/laris/issues/201)), LARIS requires reorganizing the codebase into cohesive, domain-driven packages while strictly preserving the conceptual 12-layer architecture in documentation.

---

## 2. Decision

1. **Domain-Based Primary Organization:**
   The primary source hierarchy in `src/laris/` SHALL be organized by functional domain:
   - `src/laris/core/`: Immutable contracts, schemas, error hierarchies, and evidence coordinates.
   - `src/laris/corpus/`: Data ingestion, normalization, cryptographic deduplication, and partitioning.
   - `src/laris/language/`: Subword tokenization, vocabulary contracts, and compact sentence embeddings.
   - `src/laris/scientific/`: Scientific NLP, discourse extraction, unit normalization, and limitation mining.
   - `src/laris/graph/`: Embedded SQLite evidence graph persistence, schemas, and graph adapters.
   - `src/laris/retrieval/`: Multi-channel hybrid retrieval, BM25, dense adapters, and Reciprocal Rank Fusion.
   - `src/laris/reasoning/`: 3-way NLI, confidence calibration, comparative experimental matrices, conflict detection, and 12-class research gap discovery.
   - `src/laris/orchestration/`: Multi-agent workflows, DAG execution engine, cycle detection, and token budget governors.
   - `src/laris/execution/`: Dynamic task routing, hardware telemetry, memory headroom governors, and weight staging.
   - `src/laris/evaluation/`: Benchmark runners, regression gates, scientific error taxonomy, and feedback mining.
   - `src/laris/reporting/`: Structured evidence reports, citation coordinates, and on-demand manuscript drafting.

2. **Decoupling of Conceptual Architecture:**
   The conceptual 12-layer architecture described in [LAYER_ARCHITECTURE.md](../architecture/LAYER_ARCHITECTURE.md) and [IDEA.md](../archive/IDEA.md) remains fully authoritative and unchanged. Documentation SHALL map each conceptual layer (Layer 0 through Layer 11) to its corresponding domain package.

3. **Transparent Backward Compatibility:**
   To prevent breaking existing scripts, test fixtures, or external consumers, `src/laris/layers/` SHALL be retained as a transparent facade. Each `src/laris/layers/layerX_*` module SHALL re-export its public interfaces directly from the new domain packages.

4. **Zero Behavior Change:**
   The migration is strictly structural. No algorithm modifications, signature mutations, or model training shall occur during this refactoring.

---

## 3. Mapping: Conceptual 12 Layers to Domain Packages

| Conceptual Layer | Layer Name | Domain Package | Primary Modules |
| :--- | :--- | :--- | :--- |
| **Layer 0** | Corpus Ingestion & Data Governance | `laris.corpus` | `pipeline`, `normalizer`, `dedup`, `partition`, `storage`, `schemas` |
| **Layer 1** | Language Foundation & Representations | `laris.language` | `tokenizer`, `encoder`, `bm25`, `artifacts`, `stem_benchmark` |
| **Layer 2** | Semantic Relations & Calibration | `laris.reasoning` | `nli_engine`, `calibration`, `relations`, `discourse` |
| **Layer 3** | Scientific NLP & Discourse Extraction | `laris.scientific` | `extractor`, `limitations`, `units`, `benchmark` |
| **Layer 4 / 5** | Heterogeneous Evidence Graph | `laris.graph` | `sqlite_adapter`, `schemas`, `interfaces`, `benchmark` |
| **Layer 6** | Hybrid Hierarchical Retrieval | `laris.retrieval` | `engine`, `fusion`, `dense_adapter`, `lexical_adapter`, `graph_adapter` |
| **Layer 7** | Research Gap Discovery Engine | `laris.reasoning` | `matrix_engine`, `gap_classifier`, `conflict_detector`, `gap_scorer` |
| **Layer 8** | Multi-Agent Orchestration Runtime | `laris.orchestration`| `runtime`, `specialists`, `budget_governor`, `cycle_detector`, `dag_validator` |
| **Layer 9** | Adaptive Local Execution & Staging | `laris.execution` | `task_router`, `telemetry`, `headroom_governor`, `weight_staging` |
| **Layer 10** | Feedback, Evaluation & Policy Learning| `laris.evaluation` | `benchmark_runner`, `error_taxonomy`, `feedback_mining`, `contextual_bandit` |
| **Layer 11** | Epistemic Reporting & Packaging | `laris.reporting` | `report_generator`, `evidence_inspector`, `lineage`, `manuscript_composer` |

---

## 4. Consequences and Invariants

- **Positive:** Intuitive import syntax (e.g. `from laris.reasoning import ScientificNLIEngine`), eliminated redundant layer folders, enhanced modular testability, and standard library organization.
- **Invariants Preserved:** All 898+ existing unit and contract tests continue to pass; all public API contracts remain identical; local-first hardware safety ($VRAM \le 15.0$ GB) is preserved.
- **Negative / Risks:** Requires updating documentation references and maintaining compatibility facades.
