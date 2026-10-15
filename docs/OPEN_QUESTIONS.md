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
- **Status:** OPEN / RESEARCH
- **Context:** Layer 1 requires a 50M–125M parameter encoder. Options include a standard bidirectional transformer encoder with RoPE embeddings, an ALiBi-based encoder for extended context, or an optimized ModernBERT-style architecture (unpadded FlashAttention).
- **Candidate Options:**
  1. *Option A:* Custom 6-layer RoPE Transformer with FlashAttention-2.
  2. *Option B:* ALiBi-based encoder for linear length extrapolation.
- **Evaluation Criteria:** Paraphrase retrieval MRR vs. VRAM footprint and training throughput on RTX 5070 Ti.

### OQ-002: Graph Storage Engine for Layer 5 Evidence Graph
- **Status:** OPEN / PROPOSED
- **Context:** Layer 5 requires a lightweight, embedded graph store capable of handling $\sim 100\text{k} - 1\text{M}$ nodes and typed edges on local disk without requiring an external database server daemon.
- **Candidate Options:**
  1. *Option A:* Embedded KùzuDB (graph-native, zero server, optimized for Cypher and disk-backed property graphs).
  2. *Option B:* Relational SQLite / DuckDB with graph adjacency tables.
- **Evaluation Criteria:** Path traversal query latency, disk footprint, and Python binding stability.

### OQ-003: Vector Indexing Backend for Layer 6 Hybrid Retrieval
- **Status:** OPEN / PROPOSED
- **Context:** Dense retrieval requires sub-50ms approximate nearest neighbor search over $\sim 500\text{k}$ sentence vectors in host RAM.
- **Candidate Options:**
  1. *Option A:* `hnswlib` (compact, C++ core, minimal memory overhead).
  2. *Option B:* `faiss-cpu` / `faiss-gpu` (feature-rich, higher dependency footprint).
- **Evaluation Criteria:** Memory consumption in host RAM, build index time, recall@10.

### OQ-004: Ingestion Strategy for Multi-Modal Tables & Figures in Layer 4
- **Status:** OPEN / RESEARCH
- **Context:** Tables in scientific papers contain critical quantitative results. Parsing options range from deterministic PDF layout boundary analysis to lightweight vision models.
- **Evaluation Criteria:** Coordinate precision, parsing speed, and absence of external heavy models.

### OQ-005: Corpus Ingestion Sourcing for Milestone M1
- **Status:** OPEN / PENDING APPROVAL
- **Context:** Need to select initial public open-access subsets for Layer 0 corpus foundation.
- **Candidate Sources:**
  - arXiv Open Access subset (cs.AI, cs.RO, eess.SP).
  - PubMed Central Open Access subset (selected STEM & biomedical domains).
- **Decision Required:** Formal stakeholder approval of corpus scope and licensing terms.
