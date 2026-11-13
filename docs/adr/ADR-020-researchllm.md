---
document_id: "DOC-ADR-020"
title: "ADR-020: What ResearchLLM is (stages, stage-6 advisor options, gates)"
document_type: "adr"
status: "ACCEPTED"
version: "0.1.0"
created_at: "2026-11-13"
updated_at: "2026-11-13"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/specifications/LANGUAGE_ENCODER_TRAINING_SPECIFICATION.md"
decision_references:
  - "ADR-002"
  - "ADR-008"
change_summary: "Draft for the owner's decision D44: options for the stage-6 generative advisor and the stage-6 gates."
---

# ADR-020: What ResearchLLM is

## Metadata
- **Status:** ACCEPTED on 2026-11-13 by the owner's delegation ("tự chọn phương án phù hợp nhất"); the thresholds stay provisional until T113.
- **Date drafted:** 2026-11-13 · **Decision (ledger):** D44 · **Requirements:** SR-M11, SR-M3
- **Qualification:** the foundation model and every specialist are NOT QUALIFIED. Every number below marked *estimate*
  is arithmetic from assumptions, not a measurement.

## 1. Context
ResearchLLM is the self-built model stack of programme 1 (ADR-002: no pretrained third-party language model as a
dependency). Stages 1 to 5 are fixed by the training specification section 8; stage 6 is open: the generative research
advisor served on `/v1/chat/completions` with tool calls, plus reasoning and verification specialists. The hardware
envelope is one RTX 5070 Ti with 16 GB VRAM (target server limit 15.0 GB for all loaded models, stage 5 gate).

## 2. The six stages and their gates (fixed; not decided here)
| Stage | Capability | Gate |
|---|---|---|
| 1 | General language, English only since D46 / ADR-022 (encoder, ~110 M parameters *estimate* from `configs/default.yaml`) | G01-G12 of the specification (ANLI, PAWS, STS-B, SQuAD, English fertility, English STEM MRR; the ViNLI, ViQuAD and Vietnamese fertility gates are withdrawn) |
| 2 | Scientific language | SciFact NLI macro F1 >= 0.82; evidence precision and recall >= 0.80 |
| 3 | Scientific OCR | CER <= 1.5 % clean, <= 3.0 % degraded; layout IoU >= 0.88 |
| 4 | Manuscript learning | Discourse-role macro F1 >= 0.82 |
| 5 | Integration in the model service | Measured full-load VRAM <= 15.0 GB |
| 6 | Advisor and specialists | Section 5 below |

## 3. Options for the stage-6 generative advisor
Compute estimates assume 6·N·D training FLOPs, bf16, about 35 TFLOP/s sustained on the RTX 5070 Ti (*estimate*, about
40 % of an assumed 90 TFLOP/s peak; to be replaced by an owner-measured throughput) and about 16 bytes per parameter for
weights, gradients and AdamW state. Token budgets follow roughly 20 tokens per parameter (compute-optimal rule of thumb).

| Option | Parameters | Training tokens | Pretraining time (*estimate*) | Training memory (*estimate*) |
|---|---|---|---|---|
| A1. Decoder on the shared tokenizer, small | 125 M | 2.5 B | about 15 h | about 2 GB + activations |
| A2. Decoder on the shared tokenizer, medium | 350 M | 7 B | about 5 days | about 5.6 GB + activations |
| A3. Decoder, large | 1 B | 20 B | about 40 days | over 16 GB with full-precision state; needs 8-bit state and offload |
| B. Encoder-decoder on the stage-1 encoder (110 M encoder + 150-250 M decoder with cross-attention) | 260-360 M | 5-7 B for the decoder, encoder initialised | about 3-5 days | about 4-6 GB + activations |
| C. Retrieval-conditioned generation (A1 or A2 plus mandatory evidence passages in context and extractive fallback) | as A | as A plus instruction data | as A | as A, plus longer context |

Serving memory is small for all options except A3 (A2 in bf16 about 0.7 GB weights plus KV cache), so the stage-5 budget
is the constraint on the sum of all models, not on the advisor alone.

**Option A (decoder).** Simplest, standard tool-call decoding, reuses the tokenizer; the foundation encoder is not reused.
**Option B (encoder-decoder).** Reuses the qualified encoder as the reader of evidence, which fits grounded answering;
less common tooling, tool-call output needs a constrained decoder.
**Option C (retrieval-conditioned).** A discipline on top of A or B rather than a separate architecture: the advisor may
only assert what the retrieved evidence or the brain supports; unsupported claims are refused or marked.

## 4. Risk: a small self-built generator stays weak as an advisor
At 125-350 M parameters trained on a few billion tokens, fluency, multi-step reasoning and long-context faithfulness are
expected to be far below pretrained general models; open-ended research advice may not pass the gates below. Mitigations
in the design: the advisor only advises (the decision network and policy decide, spec section 6.9); answers are
retrieval-conditioned and checked by the verification specialists; tool calls are validated against schemas. If the gates
are not met the stage stays NOT QUALIFIED and the system keeps the extractive path; no capability is claimed (ADR-008).
Recommendation of this draft, for the owner to accept or change: **Option C on top of A2**, with A1 as the first
debugging-scale run and B kept as a fallback if grounded faithfulness fails on A2.

## 5. Stage-6 gates (thresholds proposed, to be set by the owner)
Measured on sealed held-out research tasks. Stage-6 language scope: English is measured directly; Vietnamese is measured only after the translation layer of ADR-022 has its own round-trip gate, and until then Vietnamese capability is not claimed (this paragraph replaces "EN and VI separately").

| Gate | Metric | Proposed threshold |
|---|---|---|
| S6-1 | Grounded-answer faithfulness (claims supported by cited evidence / all claims) | >= 0.90 |
| S6-2 | Citation accuracy (citations that support their claim) | >= 0.90 |
| S6-3 | Unsupported-claim rate | <= 0.05 |
| S6-4 | Tool-call validity (schema-valid, allowed tool, valid arguments) | >= 0.98 |
| S6-5 | Plan quality on scripted research tasks (rubric, two annotators, weighted kappa reported) | >= 0.75 of rubric maximum |
| S6-6 | Verification specialists: claim verification macro F1 on held-out claims | >= 0.82 |

The thresholds are proposals without any empirical basis yet; T113 revises them with the measured stage 1-5 results
and the owner freezes them before T114.

## 6. Decision (owner-delegated)
- Chosen option: C (retrieval-conditioned generation) on A2 (350M decoder on the shared tokenizer), as recommended in
  section 4 · Data mix and compute budget: as estimated in section 3, to be fixed in T113 before any stage-6 work.
- Thresholds: S6-1 to S6-6 accepted as proposed and provisional; T113 revises them with the measured stage 1-5 results
  and the owner freezes them before T114.
- Date: 2026-11-13. The owner delegated the choice to the assistant in conversation ("Tự chọn phương án phù hợp nhất");
  this is a recorded delegation, not a signature, and the owner may overturn it. Nothing in stage 6 starts before stage 5
  is promoted.

## 7. Consequences
Nothing in stage 6 starts before this ADR is ACCEPTED and stage 5 is promoted. No agent trains or fits any stage.
