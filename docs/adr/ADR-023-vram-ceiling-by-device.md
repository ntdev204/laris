---
document_id: "DOC-ADR-023"
title: "ADR-023: VRAM ceiling by device for training and profile runs"
document_type: "adr"
status: "SUPERSEDED"
version: "0.1.0"
created_at: "2026-11-18"
updated_at: "2026-11-18"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/adr/ADR-022-english-only-foundation.md"
decision_references:
  - "ADR-022"
  - "ADR-008"
change_summary: "Superseded 2026-11-20 by D48 (spec.md): the self-trained model is dropped; ResearchLLM is an open-weight third-party LLM. Owner decision 2026-11-18: the 14.5 GB training ceiling of the RTX 5070 Ti may be raised by the owner on a GPU of 24 GB or more (Colab A100), never on the 16 GB card."
---

# ADR-023: VRAM ceiling by device

## Metadata
- **Status:** ACCEPTED on 2026-11-18 by the owner ("Cho phép", after the agent proposed relaxing the 14.5 GB ceiling by device so a Colab A100 can be used at its full speed).
- **Qualification:** the foundation model is NOT QUALIFIED. This ADR changes a resource limit of owner runs; it is not a result.

## 1. Context
Training and profile runs of the language encoder enforced a fixed ceiling of 14.5 GB (the safe envelope of the 16 GB RTX 5070 Ti, formerly ADR-005 of the Python generation).
The owner now has a Colab A100 (40 GB) and keeps a GPU program running locally. The fixed ceiling would waste the A100 and make its speed profile impossible.

## 2. Decision
1. The default ceiling stays **14.5 GB**. It applies when nothing else is set and on every GPU below 24 GB.
2. The owner may set `LARIS_VRAM_CEILING_GB` (environment, not a tunable in code). A value at or below 14.5 is always accepted. A value above 14.5 is accepted only
   when PyTorch sees a CUDA device with **at least 24 GB** and the value is at most **95 %** of the memory it sees; otherwise the run stops with an error before any training.
3. The ceiling in force is printed at the start, used by the memory profile, and recorded in the checkpoint provenance (`vram_ceiling_gb`, `gpu_name`).
4. The central product configuration (`HardwareConfig`, `config_handoff` invariants, the inference-side headroom governor) is **not** changed: it describes the RTX 5070 Ti envelope.

## 3. Consequences
- A Colab run can use the A100's memory (for example `LARIS_VRAM_CEILING_GB=36`) while a local run on the RTX 5070 Ti cannot be raised by mistake.
- Results are "measured on" a named GPU with its ceiling; speed and memory figures of one device do not transfer to another (T202 versus T211).
- Implementation: removed in T233 with the self-trained model (D48); the decision stays as history.

## 4. Risks
- A ceiling is a check on the profile and a record, not an allocator limit: a run that really needs more memory ends in CUDA out of memory, as before.
- The 24 GB threshold and the 95 % fraction are judgement values chosen by the agent; the owner may change them by amending this ADR.
