---
document_id: "DOC-ADR-022"
title: "ADR-022: English-only foundation encoder; Vietnamese through a translation layer"
document_type: "adr"
status: "ACCEPTED"
version: "0.1.0"
created_at: "2026-11-14"
updated_at: "2026-11-14"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/adr/ADR-020-researchllm.md"
decision_references:
  - "ADR-020"
  - "ADR-008"
change_summary: "Owner decision 2026-11-14 (D46): remove Vietnamese from the stage-1 encoder; Vietnamese reaches the model through translation."
---

# ADR-022: English-only foundation encoder

## Metadata
- **Status:** ACCEPTED on 2026-11-14 by the owner ("loại bỏ toàn bộ tiếng Việt ... dùng cơ chế dịch ... bổ sung dữ liệu hao hụt bằng các tài liệu khác"). **Ledger:** D46.
- **Qualification:** the foundation model is NOT QUALIFIED. Nothing here is a measured result; "expected" means a hypothesis.

## 1. Context
R3a (`reports/verification/T99-r3a-analysis.md`) improved most tasks but regressed Vietnamese similarity (0.384 to 0.230) and left
Vietnamese QA at the "always no answer" baseline. The data review found Vietnamese labelled data small and machine-translated
(similarity), or dominated by unanswerable questions (QA). Vietnamese costs tokenizer capacity (48k vocabulary) and training
exposure that the English tasks, which sit furthest from their gates, also need.

## 2. Decision
1. The stage-1 foundation encoder is **English only**: English text, English tasks, English gates.
2. Vietnamese is handled **outside the encoder**: a translation layer (i18n for interface strings, and a translation model for
   content, chosen later in its own ADR) maps Vietnamese input to English and output back. The encoder never sees Vietnamese.
3. The data removed (Vietnamese Wikipedia, CC100-vi, ViNLI, ViQuAD v2, ViSTS, gold_vi_stem) is **replaced by English documents**
   so the token budget is kept. Candidates and licences are decided before any acquisition (owner approval).

## 3. Consequences (what must change, in order; none is done by this ADR)
| Area | Change | Who |
|---|---|---|
| Gates | G02 (ViNLI), G08, G09 (ViQuAD), G11 (VI fertility) withdrawn from stage 1; G12 becomes English STEM retrieval; G01, G03-G07, G10 stay. Amending the training specification section 5 and the plan is a task, because a gate is never waived silently (ADR-008). | agent, owner approves |
| Tokenizer | The 48k SentencePiece model was fitted on EN+VI. An English vocabulary needs a **new fit**; the encoder is retrained from scratch (R1 weights depend on the old vocabulary). | owner runs |
| Data | Remove VI shards from the manifests and mixture; add English replacement (candidates: more English scientific and general text, extra NLI, paraphrase, QA, STS sets). No download without approval. | agent proposes, owner approves |
| Held-out sets | `gold_vi_stem` (LLM labels) stays in `data/` outside Git as unused; an English STEM gold set is needed for G12. | owner |
| Evaluation | The translation layer needs its own gate (round-trip quality) before Vietnamese is claimed; until then Vietnamese capability is **not claimed**. | later ADR |
| Reports | R1-R3a reports stay as measured history. | none |

### 3.1 Progress (2026-11-14)
| Area | State |
|---|---|
| Gates | Done in T173 (training specification 3.1.0) and T176 (the foundation evaluation config 1.1.0, readiness reports `WITHDRAWN`). |
| Data | The owner asked for replacement data of at least 20 GB covering the task cases; T175 acquired it (`configs/data/english_sources.yaml`, `DATASET_SPECIFICATION.md` section 2.1). Sources with a non-commercial or undeclared licence are `NEEDS_LICENSE_REVIEW` until the owner records approval. |
| Held-out sets | STS-B leakage check built (`scripts/check_sts_leakage.py`); an English STEM gold for G12 is still open. |
| Tokenizer, retraining | Pending: partition and wiring (T177), then the owner's fit and run. |
| Documents | Normative documents amended; measured-history documents carry a D46 banner and keep their text. D05 VI guideline is FROZEN (digest bound into the sealed gold) and is not edited. |

## 4. Risks
- Retrieval or QA quality on translated Vietnamese depends on the translator; this moves a risk, it does not remove it.
- Scientific Vietnamese terms may translate poorly.
- A smaller vocabulary may fit English better (10-20 percent fewer tokens per word is a hypothesis, not measured).
- A restart wastes R1-R3a compute; the saved checkpoints cannot initialise an English tokenizer.

## 5. Not decided here
The translation model, the English replacement corpora, the new vocabulary size, and whether R3-style mixtures carry over.
