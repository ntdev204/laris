---
document_id: "DOC-ADR-010"
title: "ADR-010: Multi-Channel Hybrid Retrieval and Modular Adapter Architecture"
document_type: "adr"
status: "ACCEPTED"
version: "1.0.0"
created_at: "2026-10-16"
updated_at: "2026-10-16"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/IDEA.md"
  - "docs/research/HYBRID_RAG.md"
  - "docs/architecture/LAYER_ARCHITECTURE.md"
  - "docs/specifications/MODULE_CONTRACTS.md"
decision_references:
  - "ADR-001"
  - "ADR-004"
  - "ADR-005"
  - "ADR-009"
change_summary: "Adopted multi-channel hybrid retrieval with modular adapters and Reciprocal Rank Fusion."
---

# ADR-010: Multi-Channel Hybrid Retrieval and Modular Adapter Architecture

## Metadata
- **ADR ID:** ADR-010
- **Status:** ACCEPTED
- **Date Decided:** 2026-10-16
- **Decision Owner:** LARIS Architecture Team
- **Target Layers:** Layer 6 (Hybrid Hierarchical RAG), Boundary F (`MOD-GRAPH-001`)

## 1. Context and Problem Statement
Scientific literature discovery requires handling diverse query modalities:
1. Exact lexical matching for specialized terminology, gene symbols, and LaTeX mathematical notations.
2. Semantic dense vector retrieval for conceptual paraphrases, methodologies, and thematic relevance.
3. Structured graph traversal for multi-hop citations, contradiction paths, and experimental baselines.

Single-modality retrieval engines (e.g. dense-only vector search) suffer from hallucinations on
exact scientific keywords, while pure lexical BM25 misses semantic paraphrases and conceptual
relationships. Furthermore, unbounded graph traversal can trigger exponential context window
expansion and resource exhaustion under local execution limits.

To satisfy the local-first system boundary ([ADR-001](file:///home/thientn204/laris/docs/adr/ADR-001-local-first-system-boundary.md))
and selective computation guidelines ([ADR-005](file:///home/thientn204/laris/docs/adr/ADR-005-selective-loading-computation-access.md)),
Layer 6 retrieval must:
- Decouple retrieval channels behind a unified abstract interface (`BaseRetrievalAdapter`).
- Combine multi-channel ranked candidate lists deterministically without score scale discrepancies.
- Enforce strict depth boundaries ($N \le 5$) on graph exploration and query expansion.
- Retain complete provenance coordinates ([ADR-004](file:///home/thientn204/laris/docs/adr/ADR-004-evidence-provenance-first-class.md)).

## 2. Decision
1. **Modular Adapter Pattern:** All retrieval channels (Lexical BM25, Dense Vector, Graph Traversal)
   SHALL implement `BaseRetrievalAdapter` and accept structured `RetrievalQuery` requests.
2. **Reciprocal Rank Fusion (RRF):** Multi-channel candidate ranking SHALL be fused using
   parameterized Reciprocal Rank Fusion:
   $$\text{RRF}(d) = \sum_{c \in C} \frac{w_c}{k + r_c(d)}$$
   with default smoothing constant $k = 60.0$ and channel-specific weights $w_c \ge 0.0$.
   RRF eliminates score scale disparities between BM25 scores (unbounded $\ge 0$) and cosine
   similarities ($[-1, 1]$).
3. **Deterministic Tie-Breaking:** Candidate ranking order SHALL be strictly deterministic,
   breaking ties by candidate identifier string sorting.
4. **Depth Ceilings:** Traversal and hierarchical expansion depth SHALL NOT exceed $N = 5$ hops.
   Queries exceeding this ceiling SHALL raise `RetrievalDepthExceededError`.
5. **Metadata Filtering:** Adapters SHALL apply `MetadataFilter` parameters consistently across
   document identifiers, publication years, node entity types, and inference exclusion flags.

## 3. Alternatives Considered
1. **Dense-Only Vector Retrieval:**
   *Rejected because:* High failure rate on rare STEM symbols, chemical formulas, and acronyms.
2. **Score-Based Linear Combination (Weighted Sum of Raw Scores):**
   *Rejected because:* Uncalibrated distributions across BM25 and cosine metrics require complex
   score normalization that shifts dynamically with corpus size.
3. **Reciprocal Rank Fusion (RRF):**
   *Accepted:* Scale-invariant, robust against outlier scores, deterministic, and computationally
   inexpensive.

## 4. Consequences
### 4.1. Positive
- Modular extensibility: new search channels (e.g. cross-encoders, sparse neural) plug in cleanly.
- Epistemic provenance is preserved through fused candidates with verified `EvidenceCoordinate` lists.
- Deterministic behavior across test suites and regression benchmarks.

### 4.2. Negative & Trade-offs
- RRF ignores absolute score margins between consecutive ranks in a single channel.

## 5. Related Documents
- [HYBRID_RAG.md](file:///home/thientn204/laris/docs/research/HYBRID_RAG.md)
- [LAYER_ARCHITECTURE.md](file:///home/thientn204/laris/docs/architecture/LAYER_ARCHITECTURE.md)
- [ADR-001: Local-First System Boundary](file:///home/thientn204/laris/docs/adr/ADR-001-local-first-system-boundary.md)
- [ADR-004: Evidence Provenance First-Class](file:///home/thientn204/laris/docs/adr/ADR-004-evidence-provenance-first-class.md)
- [ADR-005: Selective Loading & Computation](file:///home/thientn204/laris/docs/adr/ADR-005-selective-loading-computation-access.md)
- [ADR-009: Embedded Evidence Graph Storage](file:///home/thientn204/laris/docs/adr/ADR-009-embedded-evidence-graph-storage.md)
