# T99 — Round R2: intake and per-gate analysis

Date: 2026-11-13 · Branch `feature/T99-r2-analysis` · The foundation model is **NOT QUALIFIED**. Every number below
is from the `val` split or a development set. None is held-out evidence for a gate (no gate has held-out encoder
evidence; T100 has not run). The agent ran no training; the owner ran steps 1-3 and 5 of runbook section 7, the agent
ran only inference and the read-only intake.

## What was run

| Run | Config | Steps | Result |
|---|---|---|---|
| `foundation-r2-smoke` | 16 x 4, checkpointing, weight 5.0, from R1 | 20 | ran; intake FAIL only on paraphrase loss (+15 %), a 20-step artefact |
| `foundation-r2-probe` | same, warmup 100 | 1,000 | intake pass; SciFact dev dense MRR 0.0513 |
| `foundation-r2-probe2` | 32 x 2 (one change), checkpointing | 1,000 | intake FAIL: paraphrase loss +12.8 %; SciFact dense 0.0454 |
| `foundation-r2` | 16 x 4, checkpointing, weight 5.0, warmup 200 | 4,000 | intake pass 18/18; best at step 3750 (val mean 0.3788), last 4000 (0.3787) |

All runs start from `foundation-r1-run1/best` with a fresh optimizer, tokenizer 48k (`36181adf…`), learning rate 5e-5,
seed 42. Model SHA-256: R2 best `f976318e…`, R2 last `62143bfe…`, probe `8d963da5…`, probe2 `b81b6470…`.

**Deviations from the plan in runbook section 7.** The 8 GB budget was dropped when the owner stopped CARLA and removed
the v1 model container; the profile of 16 x 4 *without* checkpointing ran out of memory twice (14.5-14.8 GiB, in the
QA task that carries the contrastive term), so every round used `--gradient-checkpointing` (peak 3.9-4.0 GiB at 16 x 4,
5.9 GiB at 32 x 2 in the profile; 0.6 s/step median, not the 1.0 s estimated). The decision gate (SciFact dev dense MRR
>= 0.10) was **not met** by either probe (0.0513 and 0.0454, inside the 0.02-0.10 band); after the single permitted
re-probe the plan gave no rule, and the owner chose to run the main round at 16 x 4 anyway ("1"). The main round was
therefore an exploratory extension, not a round that had passed its gate; it reached 0.1285.

## Intake of `foundation-r2` (read-only, `scripts/training_intake.py`)

18 of 18 checks pass: model SHA-256 equals the manifest for best and last, 4,000 of 4,000 optimizer steps, no skipped
step, retrieval weight 5.0, tokenizer SHA-256 equals the accepted candidate, initialised from `foundation-r1-run1/best`,
stale evaluations 1 of 4, finite validation losses, log `[SUCCESS]`, no `nan` or `inf`, peak 4.0 GiB. Validation loss
against R1 (limit +10 %): MLM 1.0819 (R1 1.1370), NLI 0.2277 (+8.4 %), paraphrase 0.0819 (+6.0 %), similarity 0.0053
(-1 %), QA 0.4968 (R1 0.4839). Mean 0.3787 against 0.3827. Report: `reports/verification/T99-foundation-r2-intake.json`.

## Retrieval (inference only, dev; the only discriminating G12 sources)

| | R1 | probe | probe2 | **R2** | BM25 |
|---|---|---|---|---|---|
| SciFact dev (809 claims) dense MRR | 0.0067 | 0.0513 | 0.0454 | **0.1285** | 0.6362 |
| SciFact dev hybrid (RRF) | 0.200 | 0.2691 | 0.2680 | **0.3417** | |
| Vietnamese STEM gold dev (137 queries, LLM gold) dense | 0.115 | 0.1507 | 0.1966 | **0.3915** | 0.9891 |
| Vietnamese STEM gold dev hybrid | 0.429 | 0.518 | 0.5516 | **0.7064** | |

The contrastive stage works: dense retrieval rose about 19-fold on SciFact. But dense is still five times below BM25,
and on SciFact the hybrid (0.3417) is **worse than BM25 alone** (0.6362): fusing the dense scores hurts. The Vietnamese
gold cannot show dense above BM25 (BM25 ranks the source first for 97.8 % of queries); it shows progress only, and it is
LLM-labelled (`human_gold: false`).

## Per-gate analysis

Values are the `val` split with 2,048 samples per dataset (QA protocol: normalized answer text), the closest the
evaluator gives to each gate metric. They are **not gate evidence**.

| Gate | Metric (threshold) | R1 | **R2** | Gap to threshold | Reading |
|---|---|---|---|---|---|
| G01 | ANLI macro F1 >= 0.85 | 0.3549 | **0.3178** | 0.53 | far; R2 below R1 |
| G02 | ViNLI macro F1 >= 0.78 | 0.1742 | **0.3258** | 0.45 | far; improved, cause not identified |
| G03 | PAWS accuracy >= 0.88 | 0.5562 | **0.5010** | 0.38 | at chance |
| G04 | PAWS macro F1 >= 0.88 | 0.4116 | **0.5003** | 0.38 | at chance |
| G05 | STS-B Spearman >= 0.82 | 0.3707 | **0.3218** | 0.50 | far; R2 below R1 |
| G06 | SQuAD EM >= 0.72 | 0.1714 | **0.1543** | 0.57 | far |
| G07 | SQuAD F1 >= 0.83 | 0.2540 | **0.2275** | 0.60 | far |
| G08 | ViQuAD EM >= 0.65 | 0.2925 | **0.2796** | 0.37 | far |
| G09 | ViQuAD F1 >= 0.78 | 0.2936 | **0.2888** | 0.49 | far; equals the majority baseline 0.2931 |
| G10 | EN fertility <= 1.35 | 1.2996 (T97 dev) | same tokenizer | margin 0.05 | passes on the development sample; held-out is T100 |
| G11 | VI fertility <= 1.35 | 1.1848 (T97 dev) | same tokenizer | margin 0.17 | as G10 |
| G12 | STEM retrieval MRR >= 0.82 and > BM25 | 0.0067 | **0.1285** (SciFact dev) | 0.69; BM25 0.636 | far; dense not above BM25 |

The T95 values for the earlier 32k model on `val` (ANLI 0.404, ViNLI 0.538, PAWS accuracy 0.696, STS-B 0.770) used a
different tokenizer, 50,600 steps and partly different protocols, so they are not a like-for-like comparison. They show
all the same that **the 48k line (R1 + R2, about 14,000 steps) is far below the 32k model on every gate-related
validation metric**; the only gains of the 48k line are G10 and G11 (fertility) and retrieval after R2.

## Findings

1. **No gate is close.** On `val`, the nine task gates G01-G09 are 0.37-0.60 below their thresholds; two are at chance
   (PAWS). The held-out run cannot reasonably reverse this, because held-out scores are normally at or below `val`.
2. **R2 helped retrieval and did not help the task gates.** Contrastive training raised dense MRR and improved ViNLI
   and similarity-VI, but ANLI, STS-B, SQuAD and PAWS did not improve and several fell slightly while the mean loss
   improved. A contrastive objective on QA pairs is not training these tasks.
3. **PAWS is at chance (accuracy 0.501, AUC 0.508).** This is not a small shortfall. Whether the encoder cannot learn PAWS
   under this mixture (small weight, 49,401 training pairs) or something is wrong in the paraphrase head or labels was not
   investigated; it should be before any further round.
4. **Training volume and mixture are the visible difference from the earlier line.** The 32k model had 50,600+ steps and
   the F05 sampling run reached STS-B 0.832 with `dataset_sampling_exponents`; R1 used none (`{}`). This is a hypothesis
   from the T95 record, not tested on the 48k tokenizer.
5. **Some gate thresholds may be out of reach for a 122 M encoder.** ANLI macro F1 >= 0.85 is, as far as I recall,
   above published results of much larger models on ANLI; I did not verify this. If it holds, G01 is not a measure of
   this model's progress. The thresholds are the owner's; ADR-020 marks S6-1..S6-6 provisional but not G01-G12.
6. **The Vietnamese STEM gold is LLM-labelled and BM25-saturated.** It supports progress statements only. SciFact test
   (sealed, T100) is the only G12 source that can discriminate.

## What the owner decides next

| Option | What it does | Cost | Assessment |
|---|---|---|---|
| A. T100 now on R2 | One held-out evaluation of all gates; records NOT QUALIFIED and returns to T99 | one use of the sealed test splits, about 1 h inference | gives the formal number but the outcome is predictable from the table; the test splits are spent on this candidate |
| B. Investigate PAWS and the mixture first (inference and data review, no GPU) | Find out why PAWS is at chance and whether sampling exponents explain the STS-B gap | agent time | cheapest; settles whether another round can move G03-G05 |
| C. Round R3 (more steps, with a changed mixture) | Continue from R2; the runbook does not approve it | hours of GPU, owner run | worth it only after B; SciFact was still rising (0.0513 at 1,000, 0.1285 at 4,000 steps) |
| D. Review G01-G12 thresholds | Decide whether the gates fit a 122 M encoder | owner decision, ADR amendment | needed before T100 if finding 5 holds |

Recommendation: B, then C or D. Do not run T100 until B shows a cause for the PAWS and similarity results or the owner
accepts spending the sealed test on a known-weak candidate. The foundation model remains **NOT QUALIFIED**.

## Reproduction

Intake: `.venv/bin/python scripts/training_intake.py --run-id foundation-r2 --expect-steps 4000
--expect-retrieval-weight 5.0 --tokenizer-model artifacts/tokenizer/foundation-r1-super/candidate/laris_spm_48k_r1.model
--init-run foundation-r1-run1 --reference-run foundation-r1-run1 --log artifacts/profiles/foundation-r2.log
--max-peak-gib 14.5`. Dev retrieval: `reports/retrieval/foundation-r2-*.json` (R1, probe, probe2 and R2 files).
Validation: `artifacts/evaluations/language_encoder/foundation-r1-run1-val.json` and `foundation-r2-val.json`
(git-ignored artifacts; run with `--max-samples 2048`, timeout 1,800 s: 600 s kills it).
