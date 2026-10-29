---
document_id: "DOC-INDEX-001"
title: "LARIS Documentation Directory Index & Navigation Guide"
document_type: "architecture"
status: "APPROVED"
version: "0.2.0"
created_at: "2026-10-15"
updated_at: "2026-10-29"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: false
related_documents:
  - "docs/architecture/SYSTEM_OVERVIEW.md"
  - "docs/development/DOCUMENTATION.md"
decision_references: []
change_summary: "Rebuilt index after documentation consolidation; relative links only."
---

# LARIS Documentation Index

Start with the repository [README](../README.md), then the sections below. Superseded material is removed; history lives in git and `CHANGELOG.md`.

| Area | Document | Purpose |
| :--- | :--- | :--- |
| Governance | [DOCUMENTATION.md](development/DOCUMENTATION.md) | Metadata schema, writing standard, document lifecycle |
| | [GIT_FLOW.md](development/GIT_FLOW.md) | Branching, PR gates, review lifecycle |
| | [CODING_STANDARDS.md](development/CODING_STANDARDS.md) | Code conventions and layout rules |
| | [CLI.md](development/CLI.md) | `laris` command reference |
| | [OPEN_QUESTIONS.md](OPEN_QUESTIONS.md), [GLOSSARY.md](GLOSSARY.md), [CHANGELOG.md](../CHANGELOG.md) | Open items, terms, release history |
| Architecture | [SYSTEM_OVERVIEW.md](architecture/SYSTEM_OVERVIEW.md) | Topology and memory hierarchy |
| | [LAYER_ARCHITECTURE.md](architecture/LAYER_ARCHITECTURE.md) | The 12 layers |
| | [DATA_FLOW.md](architecture/DATA_FLOW.md) | Ingestion, retrieval, synthesis, reporting |
| | [MODEL_ROUTING.md](architecture/MODEL_ROUTING.md) | Tiered execution and early exit |
| | [SELECTIVE_COMPUTATION.md](architecture/SELECTIVE_COMPUTATION.md) | Selective loading, computation, access |
| | [EVIDENCE_AND_PROVENANCE.md](architecture/EVIDENCE_AND_PROVENANCE.md) | Epistemic taxonomy and anchoring |
| Specifications | [MODULE_CONTRACTS.md](specifications/MODULE_CONTRACTS.md), [DATA_SCHEMAS.md](specifications/DATA_SCHEMAS.md) | Boundaries and schemas |
| | [ORCHESTRATION_SPECIFICATION.md](specifications/ORCHESTRATION_SPECIFICATION.md) | Agents, skills, tools, workflows |
| | [LANGUAGE_ENCODER_TRAINING_SPECIFICATION.md](specifications/LANGUAGE_ENCODER_TRAINING_SPECIFICATION.md) | Training readiness gates and staged pipeline |
| | [DATASET_SPECIFICATION.md](specifications/DATASET_SPECIFICATION.md), [CONFIGURATION_SPECIFICATION.md](specifications/CONFIGURATION_SPECIFICATION.md), [LARIS_GOLD_SPECIFICATION.md](specifications/LARIS_GOLD_SPECIFICATION.md), [REPORT_SPECIFICATION.md](specifications/REPORT_SPECIFICATION.md) | Datasets, configuration, gold set, reports |
| Research | [LANGUAGE_AND_MODEL_STRATEGY.md](research/LANGUAGE_AND_MODEL_STRATEGY.md) | Language foundation, semantics, local model budgets |
| | [SCIENTIFIC_NLP.md](research/SCIENTIFIC_NLP.md), [HYBRID_RAG.md](research/HYBRID_RAG.md), [RESEARCH_GAP_DISCOVERY.md](research/RESEARCH_GAP_DISCOVERY.md), [EVALUATION_STRATEGY.md](research/EVALUATION_STRATEGY.md), [S2ORC_SUBSET_SELECTION.md](research/S2ORC_SUBSET_SELECTION.md) | Scientific NLP, retrieval, gaps, evaluation, corpus subset |
| Plans | [ROADMAP.md](plans/ROADMAP.md) | Milestones and status; open work is tracked in GitHub issues |
| Testing | [TEST_STRATEGY.md](testing/TEST_STRATEGY.md), [BENCHMARK_PROTOCOL.md](testing/BENCHMARK_PROTOCOL.md), [ACCEPTANCE_CRITERIA.md](testing/ACCEPTANCE_CRITERIA.md) | Verification scope and benchmarks |
| ADRs | [ADR index](adr/README.md) | ADR-001 to ADR-013 |
| Templates | [templates/](templates/) | Document, ADR, spec, experiment, benchmark templates |
