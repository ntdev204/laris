---
document_id: "DOC-ARCH-SYS-001"
title: "LARIS System Overview and Topological Architecture"
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
  - "docs/architecture/LAYER_ARCHITECTURE.md"
  - "docs/architecture/DATA_FLOW.md"
  - "docs/architecture/MODEL_ROUTING.md"
  - "docs/architecture/SELECTIVE_COMPUTATION.md"
  - "docs/architecture/EVIDENCE_AND_PROVENANCE.md"
decision_references:
  - "ADR-001"
  - "ADR-002"
  - "ADR-005"
  - "ADR-006"
change_summary: "Comprehensive architectural topology, component boundaries, and hardware execution model."
---

# LARIS System Overview and Topological Architecture

## 1. Executive Architecture Summary

The **Local Agentic Research Intelligence System (LARIS)** is a modular, local-first artificial intelligence platform designed to ingest scientific literature, comprehend complex domain-specific discourse, maintain an auditable evidence graph, synthesize findings across multiple papers, and identify verifiable research gaps.

Unlike standard RAG pipelines or conversational wrappers around monolithic foundation LLMs, LARIS is constructed on three non-negotiable architectural tenets:
1. **Self-Built Language & Specialist Foundations:** Core language representations, NLI, discourse parsers, and claim extractors are trained in-house without mandatory dependencies on external pretrained foundation models ([ADR-002](../adr/ADR-002-self-built-language-foundation.md)).
2. **Three-Tier Selective Execution:** Memory and computation are conserved through strict separation of *Selective Loading*, *Selective Computation*, and *Selective Information Access* ([ADR-005](../adr/ADR-005-selective-loading-computation-access.md)).
3. **Evidence-First Epistemic Provenance:** Every claim, conclusion, and research gap is anchored to immutable source coordinates down to page and sentence spans ([ADR-004](../adr/ADR-004-evidence-provenance-first-class.md)).

---

## 2. High-Level Subsystem Topology

LARIS is structured into four primary operational subsystems encompassing 12 distinct functional layers:

```mermaid
flowchart TB
    subgraph S1["Subsystem I: Linguistic & Ingestion Foundation"]
        direction TB
        L0["Layer 0: Corpus Foundation & Governance"]
        L1["Layer 1: Language Foundation & Encoders"]
        L4["Layer 4: Document Intelligence (PDF/HTML/TXT)"]
        L2["Layer 2: Semantic Intelligence (NLI/Coreference)"]
        L3["Layer 3: Scientific NLP & Discourse"]
        L0 --> L1
        L1 --> L2
        L4 --> L3
        L2 --> L3
    end

    subgraph S2["Subsystem II: Knowledge & Retrieval Core"]
        direction TB
        L5["Layer 5: Evidence & Knowledge Graph"]
        L6["Layer 6: Hybrid Hierarchical RAG"]
        L3 --> L5
        L5 --> L6
    end

    subgraph S3["Subsystem III: Reasoning & Agent Orchestration"]
        direction TB
        L7["Layer 7: Research Reasoning & Gap Engine"]
        L8["Layer 8: Multi-Agent Orchestrator"]
        L6 --> L7
        L7 <--> L8
    end

    subgraph S4["Subsystem IV: Runtime Execution, Learning & Delivery"]
        direction TB
        L9["Layer 9: Adaptive Model Execution (VRAM/Cache Router)"]
        L10["Layer 10: Evaluation, Feedback & Learning"]
        L11["Layer 11: Reporting & User Interface"]
        L8 --> L9
        L9 --> L10
        L8 --> L11
    end
```

---

## 3. Physical Hardware & Storage Topology

LARIS operates within a strict local hardware budget:
- **Processor:** Intel Core i5-14600KF (14 cores, 20 threads).
- **GPU Accelerator:** NVIDIA GeForce RTX 5070 Ti (16 GB GDDR7 VRAM).
- **System Memory:** 32 GB DDR5 RAM.
- **Persistent Storage:** NVMe PCIe Gen4 SSD.

To execute deep research workflows without crashing this workstation, LARIS enforces a **Three-Tier Storage and Memory Hierarchy**:

| Tier | Physical Medium | Typical Content | Transfer Latency Target |
| :--- | :--- | :--- | :--- |
| **Tier 1 (GPU VRAM)** | 16 GB GDDR7 | Active specialist weights (e.g. active NLI or embedding model), current batch activations, KV cache. | Sub-millisecond |
| **Tier 2 (Host RAM)** | 32 GB DDR5 | Inactive specialist weights ready for dispatch, vector indexes, document tree cache, working memory graph. | $\sim 10 - 50$ ms |
| **Tier 3 (NVMe SSD)** | NVMe PCIe Gen4 | Complete corpus text, full Layer 5 Evidence Graph, model checkpoints, persistent project memory, report archives. | $\sim 100 - 500$ ms |

---

## 4. Architectural Boundaries and Cross-Cutting Concerns

### 4.1. The Epistemic Boundary
No component in LARIS is permitted to pass an ungrounded assertion as a factual input to another component. Layer 5 (Evidence Graph) acts as the epistemic firewall: all edges representing relations (`supports`, `contradicts`, `extends`) must record whether they were explicitly stated by an author or inferred by LARIS.

### 4.2. The Resource Safety Boundary
Layer 9 (Adaptive Model Execution) monitors physical GPU allocations via hardware hooks. Before any neural specialist is invoked, Layer 9 performs a pre-flight memory check. If estimated VRAM exceeds 14.5 GB, Layer 9 automatically offloads idle models or triggers sequential batching to prevent Out-Of-Memory crashes.

### 4.3. The Document Format Invariance Boundary
All downstream semantic analysis (Layers 2, 3, 5, 7) interacts exclusively with normalized `DocumentTree` objects. Downstream reasoning has zero dependency on whether the original paper was a two-column IEEE PDF, an arXiv LaTeX source, or a Nature HTML webpage.
