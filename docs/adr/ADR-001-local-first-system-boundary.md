---
document_id: "DOC-ADR-001"
title: "ADR-001: Local-First System Boundary & Zero Mandatory Cloud Inference"
document_type: "adr"
status: "ACCEPTED"
version: "1.0.0"
created_at: "2026-10-15"
updated_at: "2026-10-15"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/IDEA.md"
  - "docs/architecture/SYSTEM_OVERVIEW.md"
decision_references:
  - "ADR-001"
change_summary: "Formalized local-first system boundary and prohibition of mandatory external API dependencies."
---

# ADR-001: Local-First System Boundary & Zero Mandatory Cloud Inference

## Metadata
- **ADR ID:** ADR-001
- **Status:** ACCEPTED
- **Date Decided:** 2026-10-15
- **Decision Owner:** LARIS Architecture Team
- **Target Layers:** System-Wide, Layer 9 (Adaptive Model Execution)

## 1. Context and Problem Statement
Scientific research workflows frequently handle sensitive pre-publication drafts, proprietary intellectual property, and institutional data subject to strict data governance constraints. Existing cloud-dependent LLM workflows introduce severe risks: data exfiltration, vendor lock-in, non-deterministic model version shifts, API rate limiting, and recurring operational costs.

LARIS requires a reliable, reproducible, and private research intelligence environment capable of executing entirely on dedicated local workstation hardware.

## 2. Decision
The system boundary of LARIS SHALL be strictly **local-first**:
1. All core processing, document ingestion, linguistic encoding, semantic parsing, evidence graph reasoning, and report generation MUST execute on local workstation hardware without requiring internet connectivity.
2. The core execution pipeline MUST NOT include cloud LLM inference APIs (e.g. OpenAI, Anthropic, Google Cloud Vertex, or remote inference endpoints) as a mandatory architectural dependency.
3. Target hardware envelope is fixed at:
   - GPU: NVIDIA GeForce RTX 5070 Ti (16 GB VRAM).
   - Host Memory: 32 GB DDR5 RAM.
   - CPU: Intel Core i5-14600KF.
   - Storage: Local NVMe SSD.
4. Any optional external web retrieval (e.g. fetching papers from public open APIs) MUST be strictly isolated as non-mandatory data ingestion plugins, fully decoupled from the core offline reasoning engine.

## 3. Alternatives Considered
1. **Cloud-Hybrid Architecture:** Offload heavy synthesis to cloud LLMs while keeping retrieval local.
   *Rejected because:* Violates data privacy, compromises reproducibility due to opaque remote model updates, and creates external cost dependencies.
2. **Local Multi-GPU Cluster Assumption:** Design the system requiring high-end dual or quad workstation GPUs (e.g. 2x 24GB or A100/H100).
   *Rejected because:* Exceeds target workstation hardware constraints and prevents broad local adoption by individual researchers.

## 4. Consequences
### 4.1. Positive
- 100% data privacy and offline capability.
- Absolute determinism and reproducibility of inference results.
- Zero external API operational costs and immunity to remote service deprecation.

### 4.2. Negative & Trade-offs
- Strict physical memory ceiling (16 GB VRAM, 32 GB host RAM).
- Inability to run monolithic 70B+ dense foundation models locally without extreme quantization or severe latency penalties.
- Mandates aggressive memory management, selective loading, and compact specialist models.

## 5. Risks and Mitigations
| Risk | Severity | Mitigation Strategy |
| :--- | :--- | :--- |
| Insufficient VRAM during concurrent expert execution | High | Enforce strict selective loading (ADR-005) and compact specialist models (ADR-006). |
| Out-Of-Memory (OOM) fatal crashes | High | Implement hardware telemetry gates in Layer 9 that refuse task dispatch when safety thresholds (e.g. 14.5 GB VRAM) are exceeded. |

## 6. Validation and Acceptance Criteria
- [ ] System executes full document ingestion, claim extraction, and report generation in air-gapped environment with network interfaces disabled.
- [ ] Zero network requests generated during core inference execution.
- [ ] Peak GPU memory allocation remains strictly $\le 16$ GB throughout multi-step reasoning workflows.
