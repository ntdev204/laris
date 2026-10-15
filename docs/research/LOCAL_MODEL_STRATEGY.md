---
document_id: "DOC-RES-MODEL-001"
title: "Research Strategy: Local Model Training & Specialist Adaptation"
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
  - "docs/architecture/SELECTIVE_COMPUTATION.md"
  - "docs/research/LANGUAGE_FOUNDATION.md"
decision_references:
  - "ADR-001"
  - "ADR-002"
  - "ADR-005"
change_summary: "Strategy for training specialized neural components within local workstation compute constraints."
---

# Research Strategy: Local Model Training & Specialist Adaptation

## 1. Feasibility Analysis under Hardware Envelope

Target Hardware:
- GPU: NVIDIA RTX 5070 Ti (16 GB VRAM, $\sim 350 - 450$ TFLOPs FP16/BF16 tensor compute).
- Host RAM: 32 GB DDR5.
- CPU: Intel Core i5-14600KF.

### Pretraining Realism:
- Training a 7B general foundation LLM from scratch requires $\sim 2\times 10^{23}$ FLOPs ($\sim 100,000$ GPU-hours on an RTX 5070 Ti), which is physically intractable.
- Conversely, training **compact specialist models (50M–150M parameters)** on curated scientific domain corpora (1B–5B tokens) requires only $30 - 100$ GPU hours, completely feasible on the local workstation.

---

## 2. Training Pipeline & Parameter Targets

| Specialist Module | Target Params | Objective / Architecture | Training Compute Est. |
| :--- | :--- | :--- | :--- |
| Scientific Tokenizer | N/A (Vocab: 40k) | Byte-level BPE / Unigram on clean corpus. | $< 1$ hour CPU |
| Core STEM Encoder | 60M–110M | RoPE Transformer, Masked Language Modeling + Contrastive. | $\sim 48 - 72$ hours GPU |
| Scientific NLI Head | 15M (on encoder) | 3-way classification on scientific claim pairs. | $\sim 6 - 12$ hours GPU |
| Claim/Discourse Extractor | 20M (on encoder) | Token sequence labeling & boundary span classification. | $\sim 8 - 16$ hours GPU |
