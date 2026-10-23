---
document_id: "DOC-INDEX-001"
title: "LARIS Documentation Directory Index & Navigation Guide"
document_type: "architecture"
status: "DRAFT"
version: "0.1.0"
created_at: "2026-10-15"
updated_at: "2026-10-15"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: false
related_documents:
  - "docs/IDEA.md"
  - "docs/DOCUMENTATION_STANDARD.md"
decision_references: []
change_summary: "Comprehensive index and navigation map for all LARIS documentation."
---

# LARIS Documentation Index & Navigation Guide

Welcome to the technical documentation repository for the **Local Agentic Research Intelligence System (LARIS)**.

> [!NOTE]
> This index serves as a navigational directory. The normative source of truth for system vision and principles is [docs/IDEA.md](file:///home/thientn204/laris/docs/IDEA.md).

---

## 1. Core Governance & Principles

- [IDEA.md](file:///home/thientn204/laris/docs/IDEA.md): Official system vision, architectural tenets, 12-layer model, and epistemic principles.
- [DOCUMENTATION_STANDARD.md](file:///home/thientn204/laris/docs/DOCUMENTATION_STANDARD.md): Metadata schemas, RFC 2119 keywords, writing standards, and source-of-truth hierarchy.
- [DOCUMENT_LIFECYCLE.md](file:///home/thientn204/laris/docs/DOCUMENT_LIFECYCLE.md): Document lifecycle states (DRAFT, IN_REVIEW, APPROVED, FROZEN, DEPRECATED), baseline freeze protocol, and Change Request procedures.
- [DECISION_LOG.md](file:///home/thientn204/laris/docs/DECISION_LOG.md): Chronological registry of all accepted architectural decisions and baseline freeze events.
- [OPEN_QUESTIONS.md](file:///home/thientn204/laris/docs/OPEN_QUESTIONS.md): Active technical trade-offs, research hypotheses, and pending decisions.
- [GLOSSARY.md](file:///home/thientn204/laris/docs/GLOSSARY.md): Canonical definitions of system terminology and concepts.

---

## 2. Architecture Specifications (`docs/architecture/`)

- [SYSTEM_OVERVIEW.md](file:///home/thientn204/laris/docs/architecture/SYSTEM_OVERVIEW.md): High-level system topology, subsystems, and physical workstation memory hierarchy.
- [LAYER_ARCHITECTURE.md](file:///home/thientn204/laris/docs/architecture/LAYER_ARCHITECTURE.md): In-depth structural specifications of all 12 architectural layers.
- [DATA_FLOW.md](file:///home/thientn204/laris/docs/architecture/DATA_FLOW.md): End-to-end data pipelines for ingestion, retrieval, synthesis, and reporting.
- [MODEL_ROUTING.md](file:///home/thientn204/laris/docs/architecture/MODEL_ROUTING.md): Multi-tier model execution, dispatch policies, and early-exit mechanisms.
- [SELECTIVE_COMPUTATION.md](file:///home/thientn204/laris/docs/architecture/SELECTIVE_COMPUTATION.md): Deep-dive into selective loading, selective computation, and selective information access.
- [EVIDENCE_AND_PROVENANCE.md](file:///home/thientn204/laris/docs/architecture/EVIDENCE_AND_PROVENANCE.md): Seven-class epistemic taxonomy, coordinate anchoring, and anti-hallucination gates.

---

## 3. Interface & Contract Specifications (`docs/specifications/`)

- [MODULE_CONTRACTS.md](file:///home/thientn204/laris/docs/specifications/MODULE_CONTRACTS.md): Formal runtime contracts for boundaries A through K.
- [DATA_SCHEMAS.md](file:///home/thientn204/laris/docs/specifications/DATA_SCHEMAS.md): JSON schemas for `EvidenceCoordinate`, `ScientificClaim`, `ResearchGap`, and `TelemetrySnapshot`.
- [SKILL_SPECIFICATION.md](file:///home/thientn204/laris/docs/specifications/SKILL_SPECIFICATION.md): High-level capability packages and schemas.
- [TOOL_SPECIFICATION.md](file:///home/thientn204/laris/docs/specifications/TOOL_SPECIFICATION.md): Catalog of deterministic actuators and error boundaries.
- [AGENT_SPECIFICATION.md](file:///home/thientn204/laris/docs/specifications/AGENT_SPECIFICATION.md): The 10 specialist agent roles, communication protocols, and safety invariants.
- [WORKFLOW_SPECIFICATION.md](file:///home/thientn204/laris/docs/specifications/WORKFLOW_SPECIFICATION.md): Core research workflows and execution DAGs.
- [REPORT_SPECIFICATION.md](file:///home/thientn204/laris/docs/specifications/REPORT_SPECIFICATION.md): Specification of default research reports and on-demand manuscripts.

---

## 4. Research Strategies (`docs/research/`)

- [LANGUAGE_FOUNDATION.md](file:///home/thientn204/laris/docs/research/LANGUAGE_FOUNDATION.md): In-house STEM tokenization and compact encoder training.
- [SEMANTIC_INTELLIGENCE.md](file:///home/thientn204/laris/docs/research/SEMANTIC_INTELLIGENCE.md): NLI, coreference, and discourse relation modeling.
- [SCIENTIFIC_NLP.md](file:///home/thientn204/laris/docs/research/SCIENTIFIC_NLP.md): Heading-agnostic limitation detection and claim extraction.
- [HYBRID_RAG.md](file:///home/thientn204/laris/docs/research/HYBRID_RAG.md): Multi-channel retrieval and depth-adaptive reranking.
- [RESEARCH_GAP_DISCOVERY.md](file:///home/thientn204/laris/docs/research/RESEARCH_GAP_DISCOVERY.md): 12-class gap taxonomy, comparative matrices, and adversarial search.
- [LOCAL_MODEL_STRATEGY.md](file:///home/thientn204/laris/docs/research/LOCAL_MODEL_STRATEGY.md): Model parameter budgets and training feasibility on RTX 5070 Ti.
- [EVALUATION_STRATEGY.md](file:///home/thientn204/laris/docs/research/EVALUATION_STRATEGY.md): Capability benchmark dimensions and policy learning.

---

## 5. Architectural Decision Records (`docs/adr/`)

- [ADR Index](file:///home/thientn204/laris/docs/adr/README.md)
- [ADR-001: Local-First System Boundary](file:///home/thientn204/laris/docs/adr/ADR-001-local-first-system-boundary.md)
- [ADR-002: Self-Built Language Foundation](file:///home/thientn204/laris/docs/adr/ADR-002-self-built-language-foundation.md)
- [ADR-003: Language-First over PDF-First](file:///home/thientn204/laris/docs/adr/ADR-003-language-first-not-pdf-first.md)
- [ADR-004: Evidence Provenance as First-Class](file:///home/thientn204/laris/docs/adr/ADR-004-evidence-provenance-first-class.md)
- [ADR-005: Selective Loading vs Computation vs Access](file:///home/thientn204/laris/docs/adr/ADR-005-selective-loading-computation-access.md)
- [ADR-006: Modular Specialist Architecture & Routing](file:///home/thientn204/laris/docs/adr/ADR-006-modular-specialist-architecture-routing.md)
- [ADR-007: Document Lifecycle & Freeze Governance](file:///home/thientn204/laris/docs/adr/ADR-007-document-lifecycle-freeze-governance.md)
- [ADR-008: Evaluation Before Capability Claims](file:///home/thientn204/laris/docs/adr/ADR-008-evaluation-before-capability-claims.md)

---

## 6. Plans & Testing (`docs/plans/`, `docs/testing/`)

- [IMPLEMENTATION_ROADMAP.md](file:///home/thientn204/laris/docs/plans/IMPLEMENTATION_ROADMAP.md): Milestones M0 through M10.
- [MILESTONES.md](file:///home/thientn204/laris/docs/plans/MILESTONES.md): Milestone artifact and exit criteria matrix.
- [TEST_STRATEGY.md](file:///home/thientn204/laris/docs/testing/TEST_STRATEGY.md): Testing pyramid and verification scopes.
- [BENCHMARK_PROTOCOL.md](file:///home/thientn204/laris/docs/testing/BENCHMARK_PROTOCOL.md): Benchmark suites and data leakage rules.
- [ACCEPTANCE_CRITERIA.md](file:///home/thientn204/laris/docs/testing/ACCEPTANCE_CRITERIA.md): Checklist for Milestone M0 and beyond.
