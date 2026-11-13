# T99 (B) — Why PAWS is at chance, and what the task mixture did

Date: 2026-11-14 · Branch `feature/T99-investigate-paws` · The foundation model is **NOT QUALIFIED**. Read-only: no
training, no model forward pass; the numbers come from the code, the train manifests and the saved validation reports.

## Answer

PAWS is at chance (accuracy 0.501, AUC 0.508 for R2) most likely because the model has seen almost none of it. Under
the sampling the runs used, R1 and R2 together showed the model about **0.23 passes** over the paraphrase data and
about 11,000 PAWS training pairs in total (a quarter of one pass over PAWS's 49,401). STS-B, the other weak gate, got
about 0.5 pass. Nothing is memorised: **every task is under one epoch**. This is a measured exposure, not a proven cause
(the proving experiment is a training run, which is the owner's); it also matches the shortfall against the earlier 32k
model, which had 3.6 times more micro-batches.

## What I checked, and the result

| Check | Result |
|---|---|
| PAWS data is sound | `data/processed/paws/train.parquet`: 49,401 pairs, labels 27,572 / 21,829, pairs well formed; val 8,000 (4,461 / 3,539) |
| Labels parse correctly | `_format_paraphrase_batch` maps `"0"`/`"1"` to 0.0/1.0 and raises on anything else |
| The model sees the pair jointly | pair is built as `[CLS] a [SEP] b`; the paraphrase head reads the CLS vector (`transformer.py:686`) |
| The loss is a normal binary cross-entropy | `trainer.py:428-436`, weight `loss_lambda_para` 0.15 |
| No sampling exponents were set | `dataset_sampling_exponents: {}` in R1 and R2 (the earlier 32k baseline too; only the 1,990-step F05 sampling run used 0.7 for nli, paraphrase and qa) |
| Task sampling is temperature-based, alpha 0.7 | `TemperatureSamplingScheduler`; the CLI never passes alpha, so the default 0.7 applied to R1, R2 and the 32k run |

## The task mixture the runs actually used

Probabilities of a micro-batch belonging to each task (alpha 0.7, train rows MLM 5,414,554, NLI 1,200,353, paraphrase
379,753, QA 196,620, similarity 25,174):

| Task | Share of micro-batches | Passes over the task's data, R1 only (40,000 micro-batches of 16) | R1 + R2 (56,000) |
|---|---|---|---|
| MLM | 61.5 % | 0.07 | 0.10 |
| NLI | 21.4 % | 0.11 | 0.16 |
| paraphrase | 9.6 % | 0.16 | 0.23 |
| QA | 6.0 % | 0.20 | 0.28 |
| similarity | 1.4 % | 0.36 | 0.51 |

Within a task, datasets are drawn by row count (exponent 1.0): PAWS is 13 % of the paraphrase draws, so R1 + R2 showed
about 11,170 PAWS pairs; STS-B is 23 % of similarity, about 2,920 pairs (0.51 pass). The 32k model used 202,400
micro-batches, 3.6 times as many, so about 1.8 passes over similarity and 0.8 over paraphrase.

## Corrections to what I said earlier

- I assumed each task gets an equal share of micro-batches and concluded that 50k-100k steps would show QA 3-7 times and
  similarity 26-51 times. That was wrong: with alpha 0.7, 50,000 steps give about 1.0 pass over QA and 1.8 over
  similarity. **Overfitting on the small labelled tasks is not the near-term risk; under-exposure is.**
- The retrieval weight and the gates move with the mixture: the contrastive term is added only on QA micro-batches
  (6 % of them), so R2's four thousand steps contained about 960 QA micro-batches carrying it.

## What this does and does not show

- It supports: more steps, and a mixture that gives the weak tasks (similarity, paraphrase, QA-VI, NLI-VI) more
  micro-batches, can raise G03-G05 and G08-G09. It supports nothing about G01 (ANLI) or G06-G07, where the gap is
  large and the thresholds themselves may be out of reach (see the threshold review).
- PAWS is adversarial (word-swap pairs with high lexical overlap), so it may need many passes even when exposure is
  adequate; Quora at AUC 0.77 shows the head and the data path work.
- Not done: a forward pass on PAWS validation pairs to see whether the head output is constant. It is inference only and
  can be added if the owner wants it before R3.
