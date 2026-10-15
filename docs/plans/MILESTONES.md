---
document_id: "DOC-PLAN-MILE-001"
title: "LARIS Milestone Specifications & Exit Criteria Matrix"
document_type: "plan"
status: "DRAFT"
version: "0.1.0"
created_at: "2026-10-15"
updated_at: "2026-10-15"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/plans/IMPLEMENTATION_ROADMAP.md"
  - "docs/testing/ACCEPTANCE_CRITERIA.md"
decision_references:
  - "ADR-007"
  - "ADR-008"
change_summary: "Detailed matrix of milestones M0-M10, artifacts, dependencies, and gating criteria."
---

# LARIS Milestone Specifications & Exit Criteria Matrix

| Milestone | Target State | Key Deliverable Artifacts | Primary Entry Gate | Empirical Exit Gate |
| :--- | :--- | :--- | :--- | :--- |
| **M0** | Documentation & Governance Baseline | `docs/` complete suite, ADR-001–008, `validate_docs.py`, skeleton tests. | Greenfield workspace initialized. | `scripts/validate_docs.py` passes 100% clean; project owner review. |
| **M1** | Corpus Ingestion & Data Governance | Partitioned datasets in `data/`, deduplication manifests, provenance records. | M0 Approved. | Zero train-test leakage; 100% license compliance verified. |
| **M2** | Language Foundation & Encoders | Tokenizer checkpoint, vocab file, sentence encoder weights. | M1 Exit Passed. | Tokenizer fertility $\le 1.4$ on STEM; retrieval MRR baseline surpassed. |
| **M3** | Semantic Relations & NLI | 3-way NLI model weights, coreference resolver, discourse parser. | M2 Exit Passed. | NLI macro F1 $\ge 0.82$; zero topical similarity conflation. |
| **M4** | Scientific NLP & Discourse | Claim/Limitation extractor, SI unit normalizer. | M3 Exit Passed. | Heading-agnostic limitation detection recall $\ge 80\%$. |
| **M5** | Hybrid RAG & Evidence Graph | Layer 5 Graph database, Layer 6 hybrid retriever. | M4 Exit Passed. | 100% retrieved items anchor to verified `EvidenceCoordinate`. |
| **M6** | Research Gap Engine | Comparative matrix engine, 12-class gap scorer, adversarial search. | M5 Exit Passed. | Benchmark gap discovery validated; false gaps refuted by search. |
| **M7** | Multi-Agent Orchestration | 10 Specialist Agents, Supervisor, DAG Planner. | M6 Exit Passed. | Zero cyclic loops; recursion ceiling ($N \le 10$) enforced. |
| **M8** | Adaptive Local Execution | Layer 9 Router, LRU Specialist Cache, VRAM monitor. | M7 Exit Passed. | Peak VRAM $\le 15.0$ GB on RTX 5070 Ti; zero OOM errors. |
| **M9** | Feedback & Policy Learning | Benchmark runner, error taxonomy logger, bandit policy. | M8 Exit Passed. | Automated regression detection operational; routing latency reduced. |
| **M10**| Reporting & Productization | Structured Report generator, citation viewer, release candidate. | M9 Exit Passed. | Zero unanchored claims in reports; full system integration test passed. |
