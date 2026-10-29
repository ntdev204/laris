---
document_id: "DOC-ADR-012"
title: "ADR-012: Elimination of Parallel Layer Hierarchies and Source-Tree Consolidation"
document_type: "adr"
status: "ACCEPTED"
version: "1.0.0"
created_at: "2026-10-17"
updated_at: "2026-10-17"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/archive/IDEA.md"
  - "docs/architecture/LAYER_ARCHITECTURE.md"
  - "docs/architecture/SYSTEM_OVERVIEW.md"
  - "docs/adr/ADR-011-domain-based-package-refactoring.md"
decision_references:
  - "ADR-001"
  - "ADR-007"
  - "ADR-011"
change_summary: "Complete retirement and elimination of parallel numbered layer hierarchies, establishing single canonical domain packages."
---

# ADR-012: Elimination of Parallel Layer Hierarchies and Source-Tree Consolidation

## Metadata
- **ADR ID:** ADR-012
- **Status:** ACCEPTED
- **Date Decided:** 2026-10-17
- **Decision Owner:** LARIS Architecture Team
- **Target Scope:** Entire `src/laris/` package tree, test suites, and system architecture documentation

---

## 1. Context and Problem Statement

Following the completion of Issue #201 ([M11-ARCH-001](https://github.com/ntdev204/laris/issues/201)) and the ratification of [ADR-011](ADR-011-domain-based-package-refactoring.md), ten domain packages were introduced in `src/laris/`: `corpus`, `language`, `scientific`, `graph`, `retrieval`, `reasoning`, `orchestration`, `execution`, `evaluation`, and `reporting`.

However, as audited in GitHub Issue #206 ([M11-ARCH-002](https://github.com/ntdev204/laris/issues/206)):
1. **Parallel Source Hierarchies:** The temporary compatibility shims in `src/laris/layers/layerX_*` constituted a second, parallel package hierarchy coexisting with the domain packages.
2. **Maintenance Overhead and Ambiguity:** Maintaining duplicate import paths creates developer confusion regarding the canonical source of truth and risks circular dependencies.
3. **No External Dependency on Legacy Paths:** LARIS is currently an internal, active-development framework (`v0.1.0-rc1` / `v0.1.0`); external library clients do not require backwards compatibility shims.

---

## 2. Decision

1. **Complete Removal of Numbered Layer Hierarchies:**
   - The entire `src/laris/layers/` hierarchy is permanently deleted.
   - There SHALL be exactly one canonical source implementation for each responsibility.

2. **Repository-Wide Migration of Test and Internal Imports:**
   - All 73 test modules previously importing from `laris.layers.layerX_*` are migrated to direct imports from canonical domain packages (`laris.corpus`, `laris.language`, `laris.scientific`, `laris.graph`, `laris.retrieval`, `laris.reasoning`, `laris.orchestration`, `laris.execution`, `laris.evaluation`, `laris.reporting`).
   - Zero occurrences of `laris.layers` remain in `src/` or `tests/`.

3. **Automated Structural Enforcement:**
   - An automated contract test (`tests/contract/test_domain_packages.py::test_no_numbered_layer_directories_exist`) asserts that no directory named `layers` or starting with `layer` exists in `src/laris/`.
   - Any attempt to reintroduce numbered layer directories will immediately fail the CI quality gate.

4. **Conceptual Architecture Continuity:**
   - The conceptual 12-layer architecture remains fully documented and preserved in [docs/architecture/LAYER_ARCHITECTURE.md](../architecture/LAYER_ARCHITECTURE.md) and [docs/architecture/SYSTEM_OVERVIEW.md](../architecture/SYSTEM_OVERVIEW.md).
   - System documentation explicitly distinguishes between cognitive/functional architecture layers and physical Python package organization.

---

## 3. Consequences

### Positive
- **Single Canonical Implementation:** Zero duplication, shadow facades, or competing package roots.
- **Clear Dependency Graph:** Direct imports reduce module loading overhead and eliminate indirection.
- **Automated Regression Prevention:** CI automatically fails if legacy layer folders are committed.

### Negative / Trade-offs
- Legacy branch merges targeting old layer paths will experience conflicts, requiring rebase to canonical domain paths.
