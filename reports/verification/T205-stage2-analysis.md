# T205 — analysis and decision after the stage-2 run (2026-11-19)

Status: analysis of the T204 figures plus the forward-only evaluation of section 5 (runbook section 17, run 2026-11-19; no training, no backward step). Every number below is on the **validation split** and names its source.
The foundation model stays **NOT QUALIFIED**: no held-out (test) gate was run, and nothing here is a gate result.

Sources: T204 = `reports/verification/T204-stage2-control-runs.md` (+ `reports/verification/T204/*-probe.txt`, `*-log-tail.txt`);
T191 = `reports/verification/T191-pair-path-diagnosis.md` (pilot 2, step 2,000); T212 = `reports/verification/T212-stage1-rerun.md` (the stage-1 rerun, the start of both T204 arms);
T203 = `reports/verification/T203-stage2-mixture.md` (expected draws); T208 = `reports/verification/T208-llm-similarity.md`.

## 1. Per-task comparison

Pilot 2 and the arms are not the same experiment: pilot 2 is 2,000 steps, one task per micro-step, the pre-correction data (T191); the arms are 5,000 further steps from the stage-1 rerun, two tasks per micro-step (T204).
The stage-1 rerun itself was not probed with `diagnose_pair_path.py`, so pilot 2 stands in for "before stage 2" (its validation loss at step 2,000 is 0.6865 against 0.6874 for the rerun, T212; same level, different data).
The control is the only like-for-like comparator of the stage-2 arm (same start, steps, learning rate, batch sizes, tasks per step).

| Measure (validation) | Pilot 2 (T191) | Control (T204) | Stage 2 (T204) | Reading |
|---|---|---|---|---|
| STS-B similarity head, Spearman (600 rows) | 0.026 (cross-encoder) | 0.203 (cross-encoder) | **0.840** (bi-encoder) | Head design and contrastive data matter far more than exposure |
| STS-B siamese CLS cosine, Spearman | 0.570 | 0.740 | 0.840 | Body embeddings improve in both arms; the contrastive arm gains 0.10 more |
| STS-B token Jaccard (no model) | 0.571 | — | 0.573 | The model-free baseline the head must clear |
| NLI all_nli accuracy (chance 0.333) | 0.368 | 0.432 | 0.455 | Both rise; arm gap 0.023 |
| NLI ANLI accuracy | 0.303 | 0.322 | 0.333 | At chance in every run |
| Paraphrase PAWS AUC (chance 0.5) | 0.505 | 0.504 | 0.553 | Word-order paraphrase still not learned |
| Paraphrase Quora AUC | 0.651 | 0.693 | 0.758 | Overlap-level paraphrase learned, more so in stage 2 |
| Sentence order accuracy | — | = majority (always "in_order") | 0.40-0.50, majority 0.34-0.41 | Above majority on 8 of 9 sources, but 50-78 % "other_document" predictions |
| MLM val loss at 5,000 | (2.797 at 2,000) | 2.293 | 2.535 | Stage 2 pays +0.242 |
| Retrieval val loss at 5,000 | (0.2843 at 2,000) | 0.2428 | 0.3473 | Stage 2 pays +0.105 |
| QA val loss (weighted) | (0.7414 at 2,000) | 0.5729 | 0.5641 | Equal within noise |
| NLI / paraphrase val loss (weighted) | 0.226 / n.a. | 0.2120 / 0.0616 | 0.2046 / 0.0609 | Small gap; NLI raw cross-entropy about 1.06 / 1.02 if the weight is 0.2 (derived) against ln 3 = 1.099 |

T204 itself ran with `--no-evaluate-after`; the task metrics missing from the table above (QA EM/F1, NLI macro F1, paraphrase F1) were measured afterwards and are in section 5. They change the reading of QA (section 5).
The 600-row probes carry sampling error: about ±0.02 on an accuracy near 0.45 and about ±0.02-0.03 on an AUC near 0.55 (binomial and rank-statistic estimates, not computed from the rows). The NLI gap (0.455 against 0.432) and the PAWS gap (0.553 against 0.504) are therefore at about one to two standard errors and **are not established differences**; the similarity gap (0.840 against 0.203) is far outside any such error.

## 2. Exposure against interference

The question from T190-T191: did the pair tasks stay at chance because they were drawn too rarely (exposure) or because MLM and retrieval steps moved the encoder between their updates (interference)?

- **Exposure alone is not enough for the cross-segment path.** The control draws NLI about 5,085 and similarity about 1,532 times (T203, expected draws, computed), against about 190 and 60 updates in pilot 2. That moves the cross-encoder similarity head only from 0.026 to 0.203 and all_nli from 0.368 to 0.432; ANLI and PAWS stay at chance. More draws helped, but slowly.
- **Exposure plus a task that needs no cross-segment circuit works.** The bi-encoder head reaches 0.840 because it compares two single-sentence embeddings, the form the body already handles (T191 finding 2). This confirms that the body's single-sentence meaning was the usable resource; it does not show that the cross-segment circuit has formed.
- **Evidence for a forming cross-segment circuit is weak.** The order head moves off the majority baseline for stage 2 (the cheapest direct test of two-segment attention, T195) but its predictions are skewed, so part of the gain is a cheaper cue; NLI on all_nli rises while ANLI and PAWS (which need word order or adversarial reasoning) do not move.
- **Interference is visible only as the cost of the mixture, not as a blocker.** The stage-2 mixture gives MLM and retrieval about 0.53 and 0.41 of the control's draws (T203: 8,426 / 15,908 and 4,878 / 11,709) and their losses are worse by the amounts in the table; the pair-task losses are not better by a comparable margin (NLI 0.2046 against 0.2120, QA equal). Giving the pair tasks 1.3-1.7x the draws (T203) did not give a measurable gain on them beyond the similarity head, so draw count is not the limiting factor for NLI and PAWS inside this horizon.
- **What the data cannot separate.** The arms differ at once in mixture, extra tasks (contrastive, order, two-segment MLM), head, balanced streams and batch composition; one seed each; 5,000 steps. A clean exposure-against-interference split would need single-factor arms, which no run so far provides. Both validation curves are still falling at step 5,000 for MLM and retrieval (stage 2: MLM 2.5497 -> 2.5351 over the last 500 steps), while NLI and paraphrase have been flat since about step 1,000 (T204 log tails): whether more steps help those two is unknown from these runs.

## 3. Decisions

1. **Not to the sealed T100 evaluation.** NLI (ANLI 0.333), PAWS (0.553) and MLM/retrieval cost are not at a level a gate run would clear, and no QA EM/F1 figure exists. Opening the sealed split to confirm a known shortfall would only spend it.
2. **Not a main run on the current recipe.** The stage-2 recipe fixed similarity (a candidate for G05 once measured on the full validation split and then the sealed test) but left NLI and PAWS at or near chance; the cost to MLM and retrieval is real and its effect on QA (G06, G07) is unmeasured.
3. **Measurement gap, closed on 2026-11-19 (section 5).** The evaluator and the probes were run forward-only on `english-r1-stage1-rerun/best`, `english-r1-stage2/best` and `english-r1-control/best` (512 samples per dataset, validation split). The "before" row is now the stage-1 rerun itself, not pilot 2.
4. **A longer stage-2 run is justified only as one measured step, and only with the QA finding of section 5 in view.** Reason for: MLM and retrieval losses are still moving, and the similarity result shows the recipe can teach a pair task. Reason for caution: QA span extraction has not formed in either arm (SQuAD v1 F1 0.05-0.11 against G07 0.83). **Correction (2026-11-20):** the "4,543 QA draws" of T203 count micro-batches of 8 rows; T204 ran at micro-batch 32 x 1, so stage 2 saw about 36,000 QA rows (4,543 x 8; 1,136 draws of 32), about 0.46 of one SQuAD v1 train pass, and the earlier sentence here that QA "did not learn despite many draws" overstated the exposure. Exposure, not only capacity, may be what is short: a 15,000-step run at the QA floor 0.15 gives about 145,000 QA rows (4,544 draws x 32, computed by `scripts/plan_stage2_schedule.py`), about 1.8 SQuAD v1 passes; whether that is enough is unmeasured. Proposal for the owner (not started; a run needs the owner's order): continue from `english-r1-stage2/best` with a fresh optimizer and warm-up, 15,000 further steps, eval and save every 1,000, same mixture, probes at 5,000-step marks. Budget from T204 (about 2.5 h per 5,000 steps, about 28 compute units per arm including probes, derived): about 7.5 h and about 85 units, no control. Stop and escalate if NaN, a task loss more than 10 % above its best for two evaluations, or, at 10,000 further steps, ANLI accuracy still below 0.36 and PAWS AUC below 0.60, or SQuAD v1 F1 still below 0.20 (evaluator on the validation split at each 5,000-step mark, about 7 minutes per checkpoint at 512 samples; thresholds chosen here as "clearly above the chance level plus about two standard errors"; unmeasured against any gate).
   Two data conditions before a longer run: (a) `similarity` has 23,163 rows and would repeat about 4.6x at 20,000 steps (T203); the longer run should lower the similarity floor to hold repeats near the 5,000-step level rather than grade more rows, because T204 shows similarity is no longer the shortfall; (b) the Drive copy of `fineweb_edu_en/train.parquet` is truncated (T204 finding 2) and must be re-uploaded first.
5. **No new graded-label task now.** The plan said to open one if similarity or any pair task still fell short and labels were the cause. Similarity does not fall short on validation (0.840). NLI and PAWS fall short, but their gap is not a label-quantity gap on this evidence: NLI has 1.67 M training rows and PAWS-type data is already in the mixture (T197, T200). LLM-graded labels (T208 shards 020-039 stay ungraded) would not address them, and T205 cannot show that the T208 rows helped, because the stage-2 and control arms differ in the similarity head and the contrastive data as well. Revisit only if the full-validation STS-B figure or the longer run shows a similarity shortfall.
6. **Model-side options if the longer run still leaves NLI and PAWS at chance** (not proposed for now, noted so the next decision has them): a larger share or a dedicated warm-up for pair-format MLM, source-balanced NLI curriculum with ANLI-style data introduced later, or a larger body step budget. None is measured.

## 5. Forward-only evaluation of the three checkpoints (runbook section 17, 2026-11-19)

Run on the Colab A100 (code commit `e53be82` plus the evaluator change below), `cli.model evaluate language-encoder --split val --max-samples 512 --batch-size 8 --seed 42`, and `scripts/diagnose_pair_path.py` (600 rows). Files in `reports/verification/T205/` (`*-val.json`, `*-eval.log`, `*-probe.txt`).
The control's probe file was lost when the session was stopped before it finished writing; its probe figures are those of T204 (`reports/verification/T204/control-probe.txt`, same checkpoint, script and 600 rows). The stage-1 rerun and stage-2 probes reproduce T191 and T204 respectively (stage 2: STS-B 0.840, all_nli 0.455, PAWS 0.553, identical to T204).
The "required" column of the evaluator is its internal chance-plus-margin threshold, **not** G01-G12; every line below is "measured on the validation split".

| group (512 samples per dataset) | stage-1 rerun | stage 2 | control | internal threshold |
|---|---|---|---|---|
| MLM masked accuracy | 0.2326 | 0.2831 | 0.3272 | 0.063 |
| NLI macro F1 (5 datasets) | 0.2673 | 0.3681 | 0.3192 | 0.2617 |
| Paraphrase AUC (3 datasets) | 0.5806 | 0.6346 | 0.5986 | 0.55 |
| QA F1 (pooled, 4 datasets) | 0.0766 | 0.0928 | 0.1093 | 0.1286 (fails in all three) |
| STS-B Spearman (512 rows) | 0.0556 | 0.8461 | 0.2471 | 0.5292 (Jaccard) |

| dataset | stage-1 rerun | stage 2 | control |
|---|---|---|---|
| SQuAD v1, exact match / F1 (the G06/G07 dataset; gates 0.72 / 0.83) | 0.020 / 0.105 | 0.025 / 0.051 | 0.041 / 0.111 |
| SQuAD v2, F1 (no-answer exact match) | 0.068 (0.006) | 0.229 (0.662) | 0.154 (0.281) |
| HotpotQA F1 / AdversarialQA F1 | 0.073 / 0.059 | 0.083 / 0.008 | 0.091 / 0.081 |
| NLI all_nli / ANLI macro F1 | 0.325 / 0.219 | 0.424 / 0.332 | 0.409 / 0.277 |
| Paraphrase PAWS / Quora AUC | 0.510 / 0.677 | 0.560 / 0.757 | 0.515 / 0.698 |

Readings (one seed, 512 rows per dataset; an F1 near 0.1 carries about ±0.02 sampling error, estimated, not computed):
1. **QA span extraction has not formed in any run.** SQuAD v1 F1 is 0.05-0.11 against 0.83 required by G07, and the pooled QA figure is below or near the empty-answer baseline (0.0786). The stage-2 pooled figure (0.0928) is lifted by SQuAD v2 no-answer rows (it predicts "no answer" for 66 % of them, the control for 28 %), not by extraction: its SQuAD v1 F1 (0.051) is the lowest of the three. The QA validation loss in T204 (0.56 against 0.66 at the start) fell without this showing in span quality. This is a larger shortfall than NLI or PAWS and was invisible until this evaluation.
2. Stage 2 against control, pooled QA: 0.0928 against 0.1093, inside the sampling error; it is not shown that stage 2 harms QA, only that neither arm learned it.
3. NLI rises in both arms (0.267 -> 0.368 / 0.319); the ANLI macro F1 of 0.332 (stage 2) is close to chance for three classes. Paraphrase on PAWS stays at 0.51-0.56.
4. Similarity is the only pair task with a large effect, and it is also the only one where head design changed (bi-encoder).
5. MLM accuracy falls for stage 2 (0.2831 against 0.3272), as the loss did; the control is still improving.
6. None of these is a gate result; the sealed test split was not touched; the foundation model stays NOT QUALIFIED.

Evaluator speed (measured on the A100, 64 samples): every dataset takes about 4.5-6 s per 64 rows (fp32 forward, about 0.57 s per batch of 8), so 22 datasets at 2,048 samples would take about 50 minutes per checkpoint; 512 samples take about 7 minutes. `_score_mlm` also moved the full logits (batch x length x vocabulary, about 1.8 GB) to the CPU before selecting the masked rows; it now selects on the device first (same result, `evaluator.py`), which does not change the dominant forward cost.

## 4. Limits and caveats
- One seed per arm, 600-row probes and 512-row evaluator samples, validation split only; probe errors are estimates, not computed.
- The bi-encoder STS-B figure is on STS-B **validation** rows; STS-B train is in the stage-2 mixture, validation and test are not (T197 leakage guard: 0 hits). G05 is a test-split gate (Spearman ≥ 0.82): 0.840 on 600 validation rows is a signal, not a pass.
- Pilot 2 is a stand-in for the stage-1 rerun; data and batch layout differ.
- No qualification claim: no gate on held-out data was run, so the foundation model stays NOT QUALIFIED.
