---
document_id: "DOC-RES-SCINLP-001"
title: "Research Strategy: Scientific NLP & Heading-Agnostic Discourse Parsing"
document_type: "research"
status: "DRAFT"
version: "0.1.0"
created_at: "2026-10-15"
updated_at: "2026-10-15"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/architecture/SYSTEM_OVERVIEW.md"
  - "docs/research/LANGUAGE_AND_MODEL_STRATEGY.md"
  - "docs/architecture/EVIDENCE_AND_PROVENANCE.md"
decision_references:
  - "ADR-003"
  - "ADR-004"
change_summary: "Research strategy for fine-grained discourse unit extraction and heading-agnostic limitation detection."
---

# Research Strategy: Scientific NLP & Heading-Agnostic Discourse Parsing

## 1. Discourse Unit Extraction Beyond Section Headings

Scientific text relies on rhetorical moves rather than section titles to communicate findings. In accordance with [ADR-003](../adr/ADR-003-language-first-not-pdf-first.md), LARIS models scientific discourse using semantic sentence classification:

- **Background / Problem Formulation:** Context and existing paradigms.
- **Methodology & Protocol:** Concrete experimental setup, hardware, parameters, and algorithms.
- **Empirical Metric & Result:** Numerical measurements, standard deviations, and benchmarks.
- **Limitation & Caveat:** Sample size constraints, instrument uncalibration, environmental assumptions.
- **Theoretical Assumption:** Explicit or implicit boundary conditions (e.g. linearity, steady-state).

---

## 2. Heading-Agnostic Limitation Inference

Authors frequently bury limitations in general narrative discussion without a formal "Limitations" section:
- *Example:* "While the algorithm converged in 94% of cases, runtime scaled exponentially with graph density, and performance degraded significantly when signal-to-noise ratio fell below 6 dB."

LARIS detects these rhetorical patterns using:
1. Lexical and syntactic cue patterns (concessive markers: *although*, *nevertheless*, *restricted to*, *degraded when*).
2. Boundary condition extractors that bind performance metrics to specific operational ranges.
3. Contrastive classification trained on annotated scientific discussions.
