---
document_id: "DOC-ADR-INDEX-001"
title: "LARIS Architecture Decision Records (ADR) Index"
document_type: "adr"
status: "DRAFT"
version: "0.1.0"
created_at: "2026-10-15"
updated_at: "2026-10-15"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/IDEA.md"
  - "docs/DECISION_LOG.md"
decision_references: []
change_summary: "Index of all Architecture Decision Records (ADRs) in LARIS."
---

# Architecture Decision Records (ADRs)

Architecture Decision Records (ADRs) capture significant architectural decisions made within the LARIS project, including their context, rationale, evaluated alternatives, consequences, and validation criteria.

## ADR Status Lifecycle
- **PROPOSED:** Under review and evaluation. Not binding.
- **ACCEPTED:** Formally authorized and locked into project specifications.
- **REJECTED:** Evaluated and formally dismissed.
- **DEPRECATED:** Replaced or invalidated by a subsequent decision.
- **SUPERSEDED:** Replaced by a newer ADR (must reference replacing ADR).

## Active Accepted ADR Registry

| ADR ID | Title | Status | Date Accepted | Primary Layer Impact |
| :--- | :--- | :--- | :--- | :--- |
| [ADR-001](file:///home/thientn204/laris/docs/adr/ADR-001-local-first-system-boundary.md) | Local-First System Boundary & Zero Mandatory Cloud Inference | ACCEPTED | 2026-10-15 | System-Wide, Layer 9 |
| [ADR-002](file:///home/thientn204/laris/docs/adr/ADR-002-self-built-language-foundation.md) | Self-Built Language Foundation & Exclusion of Mandatory Pretrained LLMs | ACCEPTED | 2026-10-15 | Layer 0, Layer 1 |
| [ADR-003](file:///home/thientn204/laris/docs/adr/ADR-003-language-first-not-pdf-first.md) | Language-First and Document-Agnostic Processing over PDF-First Design | ACCEPTED | 2026-10-15 | Layer 1, Layer 2, Layer 4 |
| [ADR-004](file:///home/thientn204/laris/docs/adr/ADR-004-evidence-provenance-first-class.md) | Evidence Provenance & Epistemic Traceability as First-Class Citizens | ACCEPTED | 2026-10-15 | Layer 3, Layer 5, Layer 7 |
| [ADR-005](file:///home/thientn204/laris/docs/adr/ADR-005-selective-loading-computation-access.md) | Strict Separation of Selective Loading, Computation, and Information Access | ACCEPTED | 2026-10-15 | Layer 6, Layer 9 |
| [ADR-006](file:///home/thientn204/laris/docs/adr/ADR-006-modular-specialist-architecture-routing.md) | Modular Specialist Architecture with Learned Task Routing | ACCEPTED | 2026-10-15 | Layer 8, Layer 9 |
| [ADR-007](file:///home/thientn204/laris/docs/adr/ADR-007-document-lifecycle-freeze-governance.md) | Document Lifecycle Governance, Baseline Freezing, and Scoped Control | ACCEPTED | 2026-10-15 | System-Wide Governance |
| [ADR-008](file:///home/thientn204/laris/docs/adr/ADR-008-evaluation-before-capability-claims.md) | Empirical Evaluation and Benchmark Gates Preceding Capability Claims | ACCEPTED | 2026-10-15 | Layer 10, Testing |
| [ADR-013](docs/adr/ADR-013-functional-package-layout-and-cli.md) | Functional Sub-Package Layout, Function-Based Naming and the laris CLI | ACCEPTED | 2026-10-29 | System-Wide |
