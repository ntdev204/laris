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
  - "docs/adr/README.md"
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

## ADR Registry

On `laris-v2` only the principle ADRs remain; the decisions about the Python generation's structure (ADR-001, 005, 006, 009 to 019) are on the frozen branch `laris-v1`.

| ADR ID | Title | Status | Date Accepted | Primary Layer Impact |
| :--- | :--- | :--- | :--- | :--- |
| [ADR-002](ADR-002-self-built-language-foundation.md) | Self-Built Language Foundation & Exclusion of Mandatory Pretrained LLMs | SUPERSEDED by D48 (spec.md) | 2026-10-15 | Layer 0, Layer 1 |
| [ADR-003](ADR-003-language-first-not-pdf-first.md) | Language-First and Document-Agnostic Processing over PDF-First Design | ACCEPTED | 2026-10-15 | Layer 1, Layer 2, Layer 4 |
| [ADR-004](ADR-004-evidence-provenance-first-class.md) | Evidence Provenance & Epistemic Traceability as First-Class Citizens | ACCEPTED | 2026-10-15 | Layer 3, Layer 5, Layer 7 |
| [ADR-007](ADR-007-document-lifecycle-freeze-governance.md) | Document Lifecycle Governance, Baseline Freezing, and Scoped Control | ACCEPTED | 2026-10-15 | System-Wide Governance |
| [ADR-008](ADR-008-evaluation-before-capability-claims.md) | Empirical Evaluation and Benchmark Gates Preceding Capability Claims | ACCEPTED | 2026-10-15 | Layer 10, Testing |
| [ADR-020](ADR-020-researchllm.md) | What ResearchLLM is: stages, stage-6 advisor options, gates | SUPERSEDED by D48 (spec.md) | — | Model block |
| [ADR-021](ADR-021-rust-generation.md) | Rust generation: system, server, client; decisions D27-D43 | ACCEPTED | 2026-11-13 | System, server, client |
| [ADR-022](ADR-022-english-only-foundation.md) | English-only foundation encoder | SUPERSEDED by D48 (spec.md) | 2026-11-14 | Model block |
| [ADR-023](ADR-023-vram-ceiling-by-device.md) | VRAM ceiling by device for training and profile runs | SUPERSEDED by D48 (spec.md) | 2026-11-18 | Model block, owner runs |

## Freeze Register

Documents with `status: FROZEN` MUST be listed here by `document_id` with the freeze date and release tag (enforced by `scripts/validate_docs.py`). No document is frozen at present.
