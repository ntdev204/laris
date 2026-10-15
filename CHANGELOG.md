# LARIS Changelog

All notable changes to the LARIS project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] - Milestone M0 Baseline

### Added
- Greenfield repository discovery and initial audit (`docs/architecture/REPOSITORY_AUDIT.md`).
- Official system vision, architectural tenets, and 12-layer model in `docs/IDEA.md`.
- Documentation standards and YAML metadata specification (`docs/DOCUMENTATION_STANDARD.md`).
- Document lifecycle states, freeze workflow, and Change Request protocol (`docs/DOCUMENT_LIFECYCLE.md`).
- Architectural Decision Records baseline:
  - `ADR-001`: Local-First System Boundary.
  - `ADR-002`: Self-Built Language Foundation.
  - `ADR-003`: Language-First rather than PDF-First.
  - `ADR-004`: Evidence Provenance as a First-Class Requirement.
  - `ADR-005`: Separation of Selective Loading, Computation, and Information Access.
  - `ADR-006`: Modular Specialist Architecture and Task Routing.
  - `ADR-007`: Document Lifecycle Governance and Baseline Freezing.
  - `ADR-008`: Empirical Evaluation Before Capability Claims.
- Architecture specifications: `SYSTEM_OVERVIEW.md`, `LAYER_ARCHITECTURE.md`, `DATA_FLOW.md`, `MODEL_ROUTING.md`, `SELECTIVE_COMPUTATION.md`, `EVIDENCE_AND_PROVENANCE.md`.
- Formal module contracts for boundaries A through K (`docs/specifications/MODULE_CONTRACTS.md`).
- Canonical data schemas for coordinates, claims, gaps, reports, and telemetry (`docs/specifications/DATA_SCHEMAS.md`).
- Skill, tool, agent, workflow, and report specifications.
- Research strategies for language foundation, semantics, scientific NLP, hybrid RAG, research gaps, local models, and evaluation.
- Implementation roadmap (M0–M10) and milestone exit criteria matrix.
- Test strategy, empirical benchmark protocol, and acceptance criteria.
- Templates for documents, specifications, ADRs, experiments, and benchmark reports.
- Python package skeleton (`src/laris/`) and test suites (`tests/`).
- Automated documentation validation tool (`scripts/validate_docs.py`).
