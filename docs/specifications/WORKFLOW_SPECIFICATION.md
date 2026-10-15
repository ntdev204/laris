---
document_id: "DOC-SPEC-WORKFLOW-001"
title: "LARIS Workflow Specification & Orchestration DAGs"
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
  - "docs/specifications/AGENT_SPECIFICATION.md"
  - "docs/specifications/REPORT_SPECIFICATION.md"
decision_references:
  - "ADR-004"
  - "ADR-006"
change_summary: "Specification of primary research workflows, execution DAGs, branching logic, and stopping criteria."
---

# LARIS Workflow Specification & Orchestration DAGs

## 1. Overview

Workflows in LARIS formalize multi-agent and multi-tool execution pipelines into repeatable, auditable Directed Acyclic Graphs (DAGs). Each workflow defines explicit entry conditions, branching thresholds, retry parameters, resource budgets, and stopping criteria.

---

## 2. Core Workflow Catalog

### 2.1. Workflow 1: Research Gap Discovery & Synthesis (Primary Default Workflow)
- **Trigger:** User submits a research topic, hypothesis, or exploratory inquiry.
- **Goal:** Synthesize literature, identify empirical contradictions, evaluate candidate research gaps, and produce a structured research report.
- **Execution DAG:**
  1. `Query Planner`: Normalize intent into 3–5 sub-questions.
  2. `Evidence Retrieval Agent`: Multi-hop hierarchical search across corpus and Layer 5 graph.
  3. `Scientific Claim Agent`: Extract claims, metrics, and limitations.
  4. `Cross-Paper Synthesis Agent`: Construct comparative experimental matrix.
  5. `Gap Discovery Agent`: Synthesize candidate gaps (12 classes) and query for adversarial counter-evidence.
  6. `Critical Reviewer`: Audit evidence coordinates and epistemic classifications.
  7. `Report Composer`: Assemble final structured research report.
- **Stopping Conditions:**
  - Success: All sub-questions answered with evidence citations $\ge 0.85$ confidence.
  - Insufficient Evidence: Bounded corpus searched completely; gaps marked as `INSUFFICIENT_CORPUS_COVERAGE`.
  - Timeout: Cumulative execution time reaches 180 seconds.

### 2.2. Workflow 2: Corpus Ingestion & Knowledge Graph Construction
- **Trigger:** New documents added to `data/raw/` or requested by user.
- **Goal:** Convert raw documents into clean `DocumentTrees` and populate the Layer 5 Evidence Graph.
- **Execution Steps:** License audit $\rightarrow$ Unicode normalization $\rightarrow$ Layout parsing $\rightarrow$ Tokenization $\rightarrow$ Discourse extraction $\rightarrow$ Graph ingestion.

### 2.3. Workflow 3: On-Demand Manuscript Drafting (Secondary Workflow)
- **Trigger:** Explicit user command requesting an academic paper or manuscript draft (e.g. "Draft an IEEE conference paper based on this report").
- **Constraint:** Strictly gated. System MUST NOT execute this workflow unless explicitly requested.
- **Execution Steps:** Load verified Research Report $\rightarrow$ Draft Introduction & Problem Statement $\rightarrow$ Synthesize Literature Review from comparative matrix $\rightarrow$ Detail Gap & Proposed Methodology $\rightarrow$ Format LaTeX/Markdown citations.
