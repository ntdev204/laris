---
document_id: "DOC-GOV-OPEN-001"
title: "LARIS Open Architecture Questions & Research Inquiries"
document_type: "architecture"
status: "DRAFT"
version: "0.1.0"
created_at: "2026-10-15"
updated_at: "2026-10-15"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/IDEA.md"
  - "docs/DECISION_LOG.md"
decision_references: []
change_summary: "Registry of unresolved architectural decisions, technical trade-offs, and research questions."
---

# LARIS Open Architecture Questions & Research Inquiries

This registry tracks open technical questions, unverified hypotheses, and pending decisions requiring empirical evaluation or project owner approval. In accordance with [docs/DOCUMENTATION_STANDARD.md](file:///home/thientn204/laris/docs/DOCUMENTATION_STANDARD.md), unapproved technical choices MUST NOT be documented as accepted decisions.

---

## Active Open Questions Registry

### OQ-001: Neural Architecture for Layer 1 Sentence Encoder
- **Status:** DECIDED / RESOLVED (ADR-002, DOC-SPEC-TRAIN-001)
- **Resolution:** 12-layer bidirectional Transformer encoder ($d_{\text{model}}=768$, 12 heads, $d_{\text{ff}}=3072$, RoPE positional encoding, RMSNorm pre-norm, GELU, tied MLM embeddings, 109.56M backbone params, 109.76M with multi-task heads). Implemented in `src/laris/language/neural.py`.

### OQ-002: Graph Storage Engine for Layer 5 Evidence Graph
- **Status:** DECIDED / RESOLVED (ADR-009)
- **Resolution:** Embedded SQLite with indexed node/edge schema (`src/laris/graph/evidence_graph.py`). Provides deterministic relational transactions, zero daemon overhead, and complete graph integrity.

### OQ-003: Vector Indexing Backend for Layer 6 Hybrid Retrieval
- **Status:** DECIDED / RESOLVED (ADR-010)
- **Resolution:** Reciprocal Rank Fusion (RRF) combining lexical BM25 and dense cosine projections with numpy vectorization (`src/laris/retrieval/hybrid.py`). Multi-channel fusion operates within host RAM budget.

### OQ-004: Ingestion Strategy for Multi-Modal Tables & Figures in Layer 4
- **Status:** OPEN / RESEARCH
- **Context:** Tables in scientific papers contain critical quantitative results. Parsing options range from deterministic PDF layout boundary analysis to lightweight vision models.
- **Evaluation Criteria:** Coordinate precision, parsing speed, and absence of external heavy models.

### OQ-005: Corpus Ingestion Sourcing for Milestone M1
- **Status:** DECIDED / RESOLVED (DOC-SPEC-DATA-001, Issue #205)
- **Resolution:** Acquired 14 verified open-access datasets (5,106,491 records) across Wikipedia EN/VI, Universal Dependencies, All-NLI, ANLI, Quora, PAWS, STS-B, SQuAD, ViQuAD, SciFact, PubLayNet.
