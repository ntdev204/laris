---
document_id: "DOC-ADR-005"
title: "ADR-005: Strict Separation of Selective Loading, Computation, and Information Access"
document_type: "adr"
status: "ACCEPTED"
version: "1.0.0"
created_at: "2026-10-15"
updated_at: "2026-10-15"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/archive/IDEA.md"
  - "docs/architecture/SELECTIVE_COMPUTATION.md"
  - "docs/architecture/MODEL_ROUTING.md"
decision_references:
  - "ADR-005"
change_summary: "Formalized three-way distinction between selective loading, computation, and information access under local hardware constraints."
---

# ADR-005: Strict Separation of Selective Loading, Computation, and Information Access

## Metadata
- **ADR ID:** ADR-005
- **Status:** ACCEPTED
- **Date Decided:** 2026-10-15
- **Decision Owner:** LARIS Architecture Team
- **Target Layers:** Layer 6 (Hybrid RAG), Layer 8 (Agent Orchestration), Layer 9 (Adaptive Model Execution)

## 1. Context and Problem Statement
Scientific research workflows require evaluating dozens or hundreds of technical papers. Naive architectures attempt to solve this either by:
1. Pushing massive context windows into memory, which rapidly causes catastrophic Out-of-Memory (OOM) failures on a 16 GB GPU.
2. Assuming that Sparse Mixture-of-Experts (MoE) automatically solves all memory limits, failing to realize that inactive expert weights must still reside in VRAM or host RAM.
3. Loading all specialist models (embedder, parser, NLI, claim extractor, graph reasoner) simultaneously into GPU memory, exhausting VRAM before inference begins.

To ensure stability on the target hardware envelope (RTX 5070 Ti 16GB VRAM, 32GB RAM), the architecture must formally separate and manage three distinct optimization mechanisms.

## 2. Decision
LARIS SHALL formally categorize and decouple the following three computational disciplines:

1. **Selective Loading (Physical Resource Allocation):**
   - The system SHALL NOT attempt to keep all neural models or expert weights resident in GPU VRAM simultaneously.
   - Weights SHALL be staged across a 3-tier hierarchy: GPU VRAM (16 GB) $\leftrightarrow$ Host RAM (32 GB) $\leftrightarrow$ NVMe SSD.
   - The Layer 9 Resource Orchestrator SHALL dynamically load only the specialist weights required for the currently active workflow stage and promptly offload or park idle weights.

2. **Selective Computation (Dynamic Execution Routing):**
   - The system SHALL NOT invoke heavy neural models for every task.
   - Execution paths SHALL prioritize deterministic rules, inverted indexes, and lightweight statistical algorithms before dispatching to neural specialist models.
   - When neural models are invoked, learned routers SHALL activate only the specialized expert modules needed for that domain or subtask.

3. **Selective Information Access (Hierarchical Knowledge Retrieval):**
   - The system SHALL NOT dump full documents into working memory.
   - Information retrieval SHALL proceed hierarchically: sentence/claim level $\rightarrow$ paragraph level $\rightarrow$ section level $\rightarrow$ full document only when ambiguity or context demand requires it.
   - Multi-hop retrieval expansion SHALL occur adaptively based on epistemic uncertainty, not unconstrained search.

4. **Telemetry Mandate:**
   - The system MUST continuously measure and log: total model parameter count, active parameter count, allocated VRAM, cached VRAM, host RAM usage, SSD-to-RAM-to-VRAM weight transfer latency, and per-token/per-step inference latency.

## 3. Alternatives Considered
1. **Monolithic Multi-Task Model:**
   *Rejected because:* Exceeds 16GB VRAM limits and makes isolated component upgrades impossible.
2. **Naive MoE with All Experts Resident in VRAM:**
   *Rejected because:* 16GB VRAM is insufficient to hold 8x7B or 16x3B expert weights concurrently alongside runtime activations and retrieval indexes.

## 4. Consequences
### 4.1. Positive
- System remains completely within the physical 16 GB VRAM and 32 GB RAM hardware envelope.
- Elimination of GPU Out-Of-Memory (OOM) crashes during complex workflows.
- Significant throughput gains by bypassing heavy neural inference for deterministic subtasks.

### 4.2. Negative & Trade-offs
- Latency penalty associated with moving expert weights across PCI-Express bus when switching specialists.
- Increased complexity in Layer 9 execution scheduling and cache eviction management.

## 5. Risks and Mitigations
| Risk | Severity | Mitigation Strategy |
| :--- | :--- | :--- |
| High PCIe transfer latency degrading user experience | Medium | Group sequential tasks targeting the same specialist model (batch scheduling) to minimize frequent weight swapping. |
| Memory fragmentation from dynamic allocations | Medium | Pre-allocate fixed VRAM memory pools for active specialist execution. |

## 6. Validation and Acceptance Criteria
- [ ] Automated stress tests verify that GPU VRAM usage never exceeds 15.0 GB under peak multi-agent research workloads.
- [ ] Benchmark logs record distinct metrics for weight load time, active execution time, and retrieval latency.
