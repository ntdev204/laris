---
document_id: "DOC-GOV-GLOSS-001"
title: "LARIS Canonical Terminology Glossary"
document_type: "specification"
status: "DRAFT"
version: "0.1.0"
created_at: "2026-10-15"
updated_at: "2026-10-15"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/development/DOCUMENTATION.md"
  - "docs/architecture/SYSTEM_OVERVIEW.md"
decision_references: []
change_summary: "Canonical definitions of architectural, epistemic, and machine learning terms."
---

# LARIS Canonical Terminology Glossary

All documentation and codebase implementations in LARIS MUST use the terms below strictly according to their canonical definitions.

---

## A–D

- **Adaptive Computation Depth:** A runtime policy in Layer 9 that halts execution when epistemic uncertainty falls below a safety threshold or escalates to deeper reasoning specialists when ambiguity remains high.
- **Agent:** A specialized software actor governed by Layer 8 with explicit roles, input/output schemas, state machines, allowed tools, and resource budgets.
- **Claim:** An assertive proposition extracted from scientific literature stating a hypothesis, methodology, empirical outcome, or theoretical conclusion.
- **DocumentTree:** The canonical hierarchical object representing a scientific document (`Document -> Section -> Subsection -> Paragraph -> Sentence -> Token/Discourse Unit`), invariant to the original file format (PDF, DOCX, HTML, TXT).

---

## E–H

- **Epistemic Classification:** The mandatory categorization of every assertion into one of seven formal states: `DIRECT_AUTHOR_CLAIM`, `EMPIRICALLY_SUPPORTED_FINDING`, `MULTI_SOURCE_SYNTHESIS`, `HYPOTHESIS`, `INSUFFICIENT_EVIDENCE`, `CONFLICTING_EVIDENCE`, or `UNVERIFIABLE_ASSERTION`.
- **EvidenceCoordinate:** An immutable reference structure defining the exact physical source coordinates of a text or data snippet (`document_id`, `document_sha256`, `page_number`, `section_identifier`, `paragraph_index`, `sentence_index`, `char_start`, `char_end`, `verbatim_snippet`).
- **Heading-Agnostic Inference:** The capability to identify discourse units (such as study limitations or theoretical assumptions) directly from natural language semantics and rhetorical markers without relying on explicit section headers.

---

## L–P

- **Local-First:** Operating entirely on dedicated local workstation hardware without mandatory external API dependencies, guaranteeing privacy, offline execution, and complete reproducibility.
- **Natural Language Inference (NLI):** The task of determining whether a premise sentence logically entails, contradicts, or is neutral towards a hypothesis sentence.
- **Provenance:** The complete, auditable lineage of data, model weights, or synthesized assertions back to its primary origin.

---

## R–Z

- **Research Gap:** A verified void, contradiction, or boundary limitation in current scientific literature, formally categorized into one of 12 classes (Knowledge, Methodological, Measurement, Dataset/Domain, Generalization, Reproducibility, Conflicting-Evidence, Assumption/Boundary, Integration/Interdisciplinary, Deployment/Resource, Temporal, or Underexplored Question).
- **Selective Computation:** Dynamically activating only the specific parameter subsets or modular specialists required for an active task.
- **Selective Information Access:** Hierarchically retrieving only the necessary sentences, claims, or sections required for an inquiry, rather than stuffing full documents into memory.
- **Selective Loading:** Managing physical presence of model weights across a 3-tier storage hierarchy (GPU VRAM $\leftrightarrow$ Host RAM $\leftrightarrow$ NVMe SSD) to prevent memory exhaustion.
- **Skill:** A high-level declarative capability package combining domain rules, specialized models, executable tools, and evaluation benchmarks.
- **Structured Research Report:** The canonical default deliverable of LARIS, containing executive synthesis, comparative matrices, ranked gaps with validation plans, limitations, and full citation indexes.
- **Tool:** A deterministic executable component with strict JSON input/output schemas, execution timeouts, and sandboxed error boundaries.
