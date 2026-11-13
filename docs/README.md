---
document_id: "DOC-INDEX-001"
title: "LARIS Documentation Directory Index & Navigation Guide"
document_type: "architecture"
status: "APPROVED"
version: "0.4.0"
created_at: "2026-10-15"
updated_at: "2026-11-10"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: false
related_documents:
  - "docs/development/DOCUMENTATION.md"
decision_references: []
change_summary: "Adds the empirical checkpoint and real-paper pilot report."
---

# LARIS Documentation Index

Start with the repository [README](../README.md), then the sections below. Superseded material is removed; history lives in git and `CHANGELOG.md`. On `laris-v2` the documents of the Python generation's architecture, deployment and configuration are removed (they remain on `laris-v1`); the Rust generation is described in `idea.md` until its new documents exist.

| Area | Document | Purpose |
| :--- | :--- | :--- |
| Governance | [DOCUMENTATION.md](development/DOCUMENTATION.md) | Metadata schema, writing standard, document lifecycle |
| | [GIT_FLOW.md](development/GIT_FLOW.md) | Branching, PR gates, review lifecycle |
| | [GLOSSARY.md](GLOSSARY.md), [CHANGELOG.md](../CHANGELOG.md) | Terms, release history |
| Specifications | [DATA_SCHEMAS.md](specifications/DATA_SCHEMAS.md) | Schemas |
| | [OBSIDIAN_VAULT_FORMAT.md](specifications/OBSIDIAN_VAULT_FORMAT.md) | Vault format (old data must stay readable) |
| | [LANGUAGE_ENCODER_TRAINING_SPECIFICATION.md](specifications/LANGUAGE_ENCODER_TRAINING_SPECIFICATION.md) | Training readiness gates and staged pipeline |
| | [DATASET_SPECIFICATION.md](specifications/DATASET_SPECIFICATION.md), [LARIS_GOLD_SPECIFICATION.md](specifications/LARIS_GOLD_SPECIFICATION.md), [REPORT_SPECIFICATION.md](specifications/REPORT_SPECIFICATION.md) | Datasets, gold set, reports |
| Research | [LANGUAGE_AND_MODEL_STRATEGY.md](research/LANGUAGE_AND_MODEL_STRATEGY.md) | Language foundation, semantics, local model budgets |
| | [RESEARCH_STRATEGY.md](research/RESEARCH_STRATEGY.md) | Evaluation, scientific NLP, hybrid retrieval and gap discovery |
| Training order | [Training index](training/README.md) | Model 01 qualification precedes model 02; owner alone trains |
| Measured status | [EMPIRICAL_STATUS.md](research/EMPIRICAL_STATUS.md) | Checkpoint validation, real-paper pilot failures and next experiment gates |
| Testing | [BENCHMARK_PROTOCOL.md](testing/BENCHMARK_PROTOCOL.md), [AGENTIC_SCENARIOS.md](testing/AGENTIC_SCENARIOS.md) | Benchmarks; golden agent scenarios |
| ADRs | [ADR index](adr/README.md) | ADR-002, 003, 004, 007, 008 (principles) |
