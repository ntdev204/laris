---
document_id: "DOC-SPEC-REP-001"
title: "LARIS Research Report & Output Deliverables Specification"
document_type: "specification"
status: "DRAFT"
version: "0.1.0"
created_at: "2026-10-15"
updated_at: "2026-10-15"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/IDEA.md"
  - "docs/specifications/DATA_SCHEMAS.md"
  - "docs/architecture/EVIDENCE_AND_PROVENANCE.md"
decision_references:
  - "ADR-004"
change_summary: "Formal specification of the default structured research report and on-demand manuscript format."
---

# LARIS Research Report & Output Deliverables Specification

## 1. Executive Deliverable Philosophy

The default, canonical output of LARIS is a **Structured Research Report**. LARIS is engineered to be a rigorous scientific intelligence instrument, not a ghostwriting engine.

Academic manuscripts, conference papers, or journal drafts are **secondary, on-demand outputs** generated strictly when explicitly commanded by the human researcher.

---

## 2. Default Deliverable: Structured Research Report

Every generated research report MUST adhere to the seven mandatory sections below:

### Section 1: Executive Summary & Inquiry Scope
- Clear definition of the user's research inquiry and normalized sub-questions.
- Corpus boundary statement: total documents analyzed, publication year range, and specific domains covered.
- High-level executive synthesis of key findings.

### Section 2: Corpus Evidence & Provenance Manifest
- Table of all primary sources ingested, including document IDs, publication venues, peer-review status, and cryptographic SHA-256 hashes.
- Ingestion extraction confidence ratings and OCR quality indicators.

### Section 3: Comparative Synthesis & Methodological Analysis
- Structured comparative matrix aligning studies across identical or divergent experimental conditions, baselines, and evaluation metrics.
- Explicit notation of empirical consensus vs. observed variances.

### Section 4: Conflicting Evidence & Contradiction Analysis
- Dedicated breakdown of direct empirical contradictions detected across studies.
- Analysis of potential root causes for discrepancies (e.g., differing sample sizes, unstated calibration differences, temperature variations).

### Section 5: Ranked Research Gaps & Validation Protocols
- Detailed breakdown of identified gaps categorized according to the 12-class gap taxonomy.
- Calibrated multi-dimensional scores for each gap:
  $$\text{Novelty}, \quad \text{Grounding}, \quad \text{Feasibility}, \quad \text{Significance}, \quad \text{Uncertainty}, \quad \text{Composite Score}$$
- Concrete, actionable experimental validation plan for top-ranked gaps (proposed experimental design, required datasets, baseline models, target metrics).

### Section 6: Limitations & Boundary Conditions
- Heading-agnostic limitations discovered across the literature.
- Inherent boundary conditions under which existing findings hold or break down.
- Explicit statement of what remains unknown or unverifiable within the current corpus bounds.

### Section 7: Auditable Evidence Citation Index
- Complete, clickable index of all evidence coordinates cited throughout the report.
- Every factual claim in Sections 1–6 MUST reference an entry in this index.

---

## 3. Secondary Deliverable: On-Demand Academic Manuscript

When the user explicitly commands:
> "Draft an academic manuscript / conference paper based on this report."

LARIS activates the `Manuscript Composer` agent to produce a standard academic paper draft (Markdown or LaTeX) following IMRAD format:
- Title & Abstract
- Introduction & Problem Formulation
- Related Work (derived directly from the comparative synthesis matrix)
- Methodology & Theoretical Formulation
- Experimental Design & Expected Results (derived from the gap validation protocol)
- Discussion, Limitations & Epistemic Boundaries
- References (formatted in IEEE/ACM style with full DOIs)

> [!WARNING]
> Generating a manuscript draft does not relax evidence provenance rules. All citations in the manuscript must remain traceable to primary coordinates.
