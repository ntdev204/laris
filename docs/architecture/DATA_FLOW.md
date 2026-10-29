---
document_id: "DOC-ARCH-FLOW-001"
title: "LARIS End-to-End Data Flow and Pipeline Architecture"
document_type: "architecture"
status: "DRAFT"
version: "0.1.0"
created_at: "2026-10-15"
updated_at: "2026-10-15"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/architecture/SYSTEM_OVERVIEW.md"
  - "docs/architecture/SYSTEM_OVERVIEW.md"
  - "docs/architecture/LAYER_ARCHITECTURE.md"
  - "docs/specifications/DATA_SCHEMAS.md"
decision_references:
  - "ADR-003"
  - "ADR-004"
  - "ADR-005"
change_summary: "Detailed specification of the 4 core end-to-end data pipelines across all 12 layers."
---

# LARIS End-to-End Data Flow and Pipeline Architecture

This document maps the flow of data through LARIS, tracing data transformations, intermediate schemas, validation checkpoints, and failure recovery pathways across four core operational pipelines.

---

## 1. Pipeline 1: Document Ingestion and Knowledge Construction

The Ingestion Pipeline transforms raw, multi-format scientific literature into structured, queryable knowledge graph representations anchored to source coordinates.

```mermaid
sequenceDiagram
    autonumber
    participant Raw as Raw Document (PDF/HTML/TXT)
    participant L0 as Layer 0: Corpus Foundation
    participant L4 as Layer 4: Document Intelligence
    participant L1 as Layer 1: Language Foundation
    participant L2 as Layer 2: Semantic Intelligence
    participant L3 as Layer 3: Scientific NLP
    participant L5 as Layer 5: Evidence Graph

    Raw->>L0: Submit raw document file
    L0->>L0: Audit license, sanitize Unicode, compute SHA-256
    L0->>L4: Validated document buffer
    L4->>L4: Parse layout, reconstruct reading order, map coordinates
    L4->>L1: Emit canonical DocumentTree
    L1->>L1: Tokenize sentences, extract syntactic dependency trees
    L1->>L2: Tokens & Sentence embeddings
    L2->>L2: Parse coreference chains & discourse connectives
    L2->>L3: Discourse-annotated sentence graph
    L3->>L3: Extract claims, methods, results, limitations, assumptions
    L3->>L5: Structured Entities (Claims, Evidence, Methods)
    L5->>L5: Update Knowledge Graph with verified provenance links
```

### Intermediate Data Formats in Pipeline 1:
- **L0 $\rightarrow$ L4:** `CleanCorpusItem` (raw text, license tag, document SHA-256).
- **L4 $\rightarrow$ L1:** `DocumentTree` (hierarchical sections, paragraphs, sentences, exact bounding boxes).
- **L1 $\rightarrow$ L2:** `TokenizedSentence` with dense vector embeddings and dependency tags.
- **L2 $\rightarrow$ L3:** `DiscourseRelationSpan` with NLI and coreference links.
- **L3 $\rightarrow$ L5:** `ClaimRecord`, `EvidenceCoordinate`, `LimitationRecord`, `MethodRecord`.

---

## 2. Pipeline 2: Research Query & Hierarchical Evidence Retrieval

When a user submits a complex research question, Pipeline 2 decomposes the query and executes depth-adaptive retrieval across textual, semantic, and graph indexes.

```mermaid
flowchart TD
    UserQuery["User Research Question"] --> L11["Layer 11: UI Ingestion"]
    L11 --> L8["Layer 8: Supervisor / Query Planner"]
    L8 --> Subqueries["Atomic Research Intents & Sub-questions"]
    
    Subqueries --> L6["Layer 6: Hybrid Hierarchical RAG"]
    
    subgraph MultiChannel["Multi-Channel Retrieval Engine"]
        L6 --> BM25["Lexical Search (BM25)"]
        L6 --> Dense["Dense Semantic Retrieval (L1 Encoders)"]
        L6 --> GraphQ["Graph Traversal (L5 Evidence Graph)"]
    end
    
    BM25 --> Reranker["Multi-Stage Reranker"]
    Dense --> Reranker
    GraphQ --> Reranker
    
    Reranker --> DepthCheck{"Evidence Sufficient & Consistent?"}
    DepthCheck -- "No (Uncertainty High)" --> Expand["Expand Retrieval: Sentence -> Paragraph -> Document"]
    Expand --> MultiChannel
    DepthCheck -- "Yes" --> EvidencePkg["Calibrated Evidence Package with Coordinates"]
    EvidencePkg --> L7["Layer 7: Research Reasoning Engine"]
```

---

## 3. Pipeline 3: Cross-Paper Synthesis & Research Gap Discovery

Pipeline 3 executes scientific reasoning over retrieved evidence packages to compare methodologies, detect empirical contradictions, and discover verifiable research gaps.

```mermaid
flowchart TD
    EP["Calibrated Evidence Packages"] --> S1["1. Align Studies by Method & Experimental Setup"]
    S1 --> S2["2. Build Comparative Outcome Matrix"]
    S2 --> S3["3. Categorize Epistemic Status (Facts vs Speculations)"]
    S3 --> S4["4. Identify Inconsistencies & Latent Boundary Limitations"]
    
    S4 --> G1["5. Generate Candidate Gaps (12-Class Taxonomy)"]
    G1 --> G2["6. Adversarial Counter-Evidence Query (Layer 6 Search)"]
    
    G2 --> G3{"Counter-Evidence Found in Corpus?"}
    G3 -- "Yes (Already Solved)" --> Reject["Discard Candidate Gap / Record Known Finding"]
    G3 -- "No (Genuine Unexplored Area)" --> Score["7. Compute Calibrated Gap Score (Novelty, Grounding, Feasibility)"]
    
    Score --> Plan["8. Formulate Concrete Empirical Validation Plan"]
    Plan --> L8Out["Layer 8: Critical Reviewer Verification"]
```

---

## 4. Pipeline 4: Synthesis, Verification, and Report Generation

Pipeline 4 converts reasoned conclusions into a structured research report with zero tolerance for unreferenced assertions.

```mermaid
flowchart TD
    L8Out["Verified Synthesis & Ranked Gaps"] --> L8Comp["Layer 8: Report Composer Agent"]
    L8Comp --> DraftReport["Draft Structured Research Report"]
    
    DraftReport --> L8Crit["Layer 8: Critical Reviewer / Adversarial Verifier"]
    
    subgraph VerificationGate["Automated Quality & Provenance Gate"]
        L8Crit --> Chk1["Verify 100% Claims have valid EvidenceCoordinate"]
        L8Crit --> Chk2["Verify no Epistemic Overreach (Correlation != Causation)"]
        L8Crit --> Chk3["Verify Hardware Telemetry within Limits"]
    end
    
    Chk1 & Chk2 & Chk3 --> GatePass{"All Verification Checks Pass?"}
    GatePass -- "Fail" --> Remediation["Remediate: Flag missing evidence / Downgrade claim status"]
    Remediation --> DraftReport
    
    GatePass -- "Pass" --> FinalReport["Official Structured Research Report"]
    FinalReport --> L11UI["Layer 11: Interactive User Interface"]
```
