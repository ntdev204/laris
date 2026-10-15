---
document_id: "DOC-RES-SEM-001"
title: "Research Strategy: Semantic Intelligence & Relational Logic"
document_type: "research"
status: "DRAFT"
version: "0.1.0"
created_at: "2026-10-15"
updated_at: "2026-10-15"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/IDEA.md"
  - "docs/research/LANGUAGE_FOUNDATION.md"
  - "docs/research/SCIENTIFIC_NLP.md"
decision_references:
  - "ADR-002"
change_summary: "Research strategy for scientific NLI, coreference resolution, and discourse relations."
---

# Research Strategy: Semantic Intelligence & Relational Logic

## 1. Disentangling Topical Similarity from Semantic Equivalence

A critical failure of standard vector embeddings is treating sentences with opposite meanings as highly similar due to shared topical vocabulary:
- *Sentence A:* "The alloy exhibited high tensile strength under extreme temperature."
- *Sentence B:* "The alloy suffered brittle fracture and failed under extreme temperature."

A generic cosine similarity search assigns these sentences an overlap of $\sim 0.88$. However, in scientific discourse, they represent direct empirical contradictions.

LARIS addresses this by training a specialized **Natural Language Inference (NLI)** head operating alongside dense embeddings to verify logical entailment, neutral overlap, and contradiction.

---

## 2. Scientific Coreference & Discourse Parsing
- **Complex Technical Coreference:** Resolving multi-token nominal phrases (e.g. "the proposed deep recurrent architecture", "this model", "the network under evaluation").
- **Discourse Relation Modeling:** Parsing Penn Discourse Treebank (PDTB) relations (Causal, Concessive, Contrast, Temporal) using fine-grained classification heads on sentence pairs.
