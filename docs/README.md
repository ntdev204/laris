---
document_id: "DOC-INDEX-001"
title: "LARIS Documentation Directory Index & Navigation Guide"
document_type: "architecture"
status: "APPROVED"
version: "0.5.0"
created_at: "2026-10-15"
updated_at: "2026-11-20"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: false
related_documents:
  - "docs/development/DOCUMENTATION.md"
decision_references: []
change_summary: "Removes documents of the dropped self-trained model (D48)."
---

# LARIS Documentation Index

Start with the repository [README](../README.md), then the sections below. Superseded material is removed; history lives in git and `CHANGELOG.md`. On `laris-v2` the documents of the Python generation's architecture, deployment and configuration are removed (they remain on `laris-v1`); the Rust generation is specified in the ledger `.claude/spec/spec.md` until its new documents exist.

| Area | Document | Purpose |
| :--- | :--- | :--- |
| Governance | [DOCUMENTATION.md](development/DOCUMENTATION.md) | Metadata schema, writing standard, document lifecycle |
| | [GIT_FLOW.md](development/GIT_FLOW.md) | Branching, PR gates, review lifecycle |
| | [GLOSSARY.md](GLOSSARY.md), [CHANGELOG.md](../CHANGELOG.md) | Terms, release history |
| Guide | [CLIENT.md](guide/CLIENT.md) | Using the terminal interface: keys, commands, approvals, input forms |
| Specifications | [DATA_SCHEMAS.md](specifications/DATA_SCHEMAS.md) | Schemas |
| | [OBSIDIAN_VAULT_FORMAT.md](specifications/OBSIDIAN_VAULT_FORMAT.md) | Vault format (old data must stay readable) |
| | [REPORT_SPECIFICATION.md](specifications/REPORT_SPECIFICATION.md) | Reports |
| Research | [RESEARCH_STRATEGY.md](research/RESEARCH_STRATEGY.md) | Evaluation, scientific NLP, hybrid retrieval and gap discovery |
| Testing | [BENCHMARK_PROTOCOL.md](testing/BENCHMARK_PROTOCOL.md), [AGENTIC_SCENARIOS.md](testing/AGENTIC_SCENARIOS.md) | Benchmarks; golden agent scenarios |
| ADRs | [ADR index](adr/README.md) | ADR-003, 004, 007, 008 (principles), ADR-021 (Rust generation); ADR-002, 020, 022, 023 are superseded by D48 |
