# T99 (D) — Review of the stage-1 gate thresholds G01-G12

Date: 2026-11-14 · Branch `feature/T99-r3-prep` · The foundation model is **NOT QUALIFIED**. This review changes no
threshold: the gates are defined in `configs/evaluation/foundation.yaml` ("formal section-5 gates") and only the owner
can amend them (ADR-020 marks only the stage-6 thresholds S6-1..S6-6 provisional, not G01-G12).

## Why look at them now

R2 is 0.37 to 0.60 below the nine task gates on `val`, and the earlier 32k model (50,600 steps) was 0.05 to 0.45 below
them on the gates with a value (T95; protocols differ). Before spending the sealed test splits (T100) or hours of GPU (R3), the owner should know which gaps a
better mixture can close and which may not be closable by this model at all.

## What external evidence I found, and what I did not

- **ANLI (G01, macro F1 >= 0.85).** One 2024 paper on NLI for large language models reports that
  [on ANLI the accuracy of even the best model does not exceed 70 %](https://arxiv.org/html/2411.14103v1). A leaderboard
  aggregator lists top entries at 58.1 %, but its snippet does not say which round, split or model, so I treat it as
  unverified. On this evidence 0.85 is above what the models in that paper reach; a 122 M encoder is unlikely to
  reach it. I did not read the ANLI leaderboard itself.
- **Every other gate.** I did not search for published figures for PAWS, STS-B, SQuAD, ViQuAD or ViNLI. From memory,
  base-size encoders *fine-tuned on one task* are reported near or above G03-G07 (for example SQuAD v1.1 EM about 81 and
  F1 about 88, STS-B Spearman above 0.85); that is a recollection, not verified here. If it holds, G03-G09 are
  reasonable for a model fine-tuned per task and ambitious for one multi-task encoder that has had about one pass over each
  task's data.
- **Fertility (G10, G11).** Measured with tokenizer R1 on a development sample at 1.2996 and 1.1848 (T97); the held-out
  measurement is T100.
- **STEM retrieval (G12, MRR >= 0.82 and above BM25).** BM25 is 0.636 on SciFact dev and 0.989 on the Vietnamese gold
  (written from the passages). A dense encoder beating 0.989 on that gold is not meaningful; SciFact test is the only
  discriminating source. A dense MRR >= 0.82 on a scientific-claim task for a general-language model is a stage-2
  target in practice.

## Gate by gate

| Gate | Threshold | R2 on `val` | Verdict |
|---|---|---|---|
| G01 ANLI macro F1 | >= 0.85 | 0.318 | **likely unreachable** (above the 70 % ceiling cited); amend or replace |
| G02 ViNLI macro F1 | >= 0.78 | 0.326 | far; keep, may need a longer run |
| G03 PAWS accuracy | >= 0.88 | 0.501 | far; at chance, exposure was the issue (T99 B) |
| G04 PAWS macro F1 | >= 0.88 | 0.500 | as G03 |
| G05 STS-B Spearman | >= 0.82 | 0.322 | far; 32k line reached 0.770 on `val` |
| G06 SQuAD EM | >= 0.72 | 0.154 | far; keep |
| G07 SQuAD F1 | >= 0.83 | 0.228 | far; keep |
| G08 ViQuAD EM | >= 0.65 | 0.280 | far; keep |
| G09 ViQuAD F1 | >= 0.78 | 0.289 | far; keep |
| G10 EN fertility | <= 1.35 | 1.2996 (dev) | on track |
| G11 VI fertility | <= 1.35 | 1.1848 (dev) | on track |
| G12 STEM retrieval | >= 0.82, > BM25 | dense 0.1285 vs BM25 0.636 (SciFact dev) | far; probably a stage-2 target |

## Options for the owner

1. **Keep all twelve gates unchanged.** Honest and simple; accept that G01 may never pass and that a stage-1
   promotion would then need G01 amended later anyway.
2. **Amend G01 now** (for example a threshold set from a verified published result of a model of comparable size, or
   "above the majority and BM25-style baselines by a stated margin"), keep G02-G12. Needs a verified external figure
   first; I do not propose a number without one.
3. **Split the gates into stage-1 gates and later targets,** moving G12 (and, if the owner agrees, G01) to stage 2 where
   scientific data exists. This changes the stage boundary in the specification.

Rules for any change: decide **before** T100 and before anyone sees the held-out numbers (a threshold moved after the
test is a post-hoc tuning of the gate); record it in an ADR amendment and in `configs/evaluation/foundation.yaml`; run
`laris harness verify`/`lock` only if policy files change (`configs/evaluation` is not `.laris/` policy).

## Recommendation

Option 2 for G01 (after a verified external figure) and option 1 for the rest, then R3a. If R3a leaves G02-G09 as far
as R2 does, revisit option 3. The sealed tests wait for a round whose development numbers are within reach.
