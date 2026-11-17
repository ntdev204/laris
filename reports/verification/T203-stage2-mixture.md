# T203 — Stage-2 mixture and schedule (proposal; every figure computed, none measured)

No training, no backward step, no tokenizer fit. `scripts/plan_stage2_schedule.py` reads the Parquet footers of the train split (row counts) and the
YAML, builds the scheduler as the trainer does and computes, for `tasks_per_step` different tasks per micro-step, the chance that each task is in a
micro-step (`task_inclusion_probabilities`, exact enumeration, checked against `sample_tasks` by a Monte Carlo test). Raw output:
`reports/verification/T203-stage2-schedule.json`. The foundation model stays **NOT QUALIFIED**; nothing here is a result.

## What is proposed
- **Start.** Stage 2 starts from `artifacts/checkpoints/language_encoder/english-r1-pilot2/best` (pilot 2, step 2,000, MLM learned) with a fresh optimizer
  (`--init-from`, new `--run-id`); its step counter restarts at 0. The stage start is that checkpoint; there is no second switch inside the run, because nothing
  measured says when a switch would help (a two-phase schedule inside stage 2 would be a guess; the control and T205 decide whether it is needed).
- **Config.** `configs/language_encoder/english_r1_stage2.yaml`: `tasks_per_step: 2` (T202), `max_steps 5000`, `warmup_steps 300` (the pilot warm-up of 2,000
  would be 40 % of the run), learning rate and loss weights as in `english_r1.yaml` (new: order 0.1, contrastive similarity 0.5 as in the profile config),
  `mlm_pair_fraction 0.5`, order task, `similarity_head: bi_encoder`, `label_balanced_tasks: [nli, paraphrase]`, the T207 `dataset_sampling_weights`
  (applied with `--dataset-sampling-ablation`). Floors (scheduler probability): NLI 0.17, paraphrase 0.13, QA 0.11, similarity 0.08, contrastive
  similarity 0.17 (pair tasks together 0.66); the rest is shared by MLM and retrieval in their alpha-0.7 proportion: MLM 0.221, retrieval 0.119.
  Every floor binds exactly (test). 20,000 steps is the same file with `--steps 20000` (the cosine schedule follows `--steps`).
- **MLM kept near 20 %.** With two different tasks per micro-step a task can be drawn at most once per step, so its share of the batch draws is not its
  scheduler probability: MLM 0.221 is **0.211 of the draws** (the control's MLM 0.490 is 0.398). The floors were chosen on the draw share. Two-segment
  rows are half of the MLM rows, so about 10 % of the draws are pair-format MLM with the order labels.
- **Similarity data.** The similarity directory includes the T208 rows (3,000, `label_source: llm`; 23,163 rows in all) because the loader reads every
  directory of a task and the rows passed calibration (Spearman 0.914) and the leakage rescan; shards 020-039 stay ungraded. Graded pairs train the body
  (`similarity_calibration_only` stays off): an unmeasured choice, listed under the risks.
- **Control** `configs/language_encoder/english_r1_stage2_control.yaml`: same checkpoint, steps, warm-up, learning rate, batch sizes and `tasks_per_step 2`, with
  the original `english_r1.yaml` mixture (similarity floor 0.03, cross-input head, no two-segment MLM, no order or contrastive task, no T207 weights, plain
  streams). It isolates what the mixture, tasks and data decisions add for the same compute. It is not pilot 2 continued: `tasks_per_step 2` doubles its batch draws
  per step, and it reads the T208 rows because they sit in the similarity directory.

## Expected draws, updates and passes (computed from the scheduler and the train row counts)
One optimizer step = 4 micro-steps; one micro-step = 2 batch draws, so 8 draws per optimizer step. `draws` = expected batches of the task;
`updates` = optimizer steps whose 4 micro-steps contain the task at least once; `passes` = draws x rows per draw / train rows (rows per draw: 8, retrieval 32,
contrastive similarity 64 anchors; MLM rows are passages, not tokens).

### Stage 2 (`english_r1_stage2.yaml`)
| task | train rows | sched. p | draw share | rows/draw | 5k draws | 5k updates | 5k passes | 20k draws | 20k updates | 20k passes |
|---|---|---|---|---|---|---|---|---|---|---|
| contrastive_sim | 1,410,056 | 0.170 | 0.169 | 64 | 6,744 | 4,035 | 0.306 | 26,978 | 16,141 | 1.224 |
| mlm | 15,500,570 | 0.221 | 0.211 | 8 | 8,426 | 4,439 | 0.004 | 33,706 | 17,757 | 0.017 |
| nli | 1,670,892 | 0.170 | 0.169 | 8 | 6,744 | 4,035 | 0.032 | 26,978 | 16,141 | 0.129 |
| paraphrase | 1,039,794 | 0.130 | 0.133 | 8 | 5,302 | 3,541 | 0.041 | 21,206 | 14,166 | 0.163 |
| qa | 442,809 | 0.110 | 0.114 | 8 | 4,543 | 3,216 | 0.082 | 18,171 | 12,864 | 0.328 |
| retrieval | 6,373,045 | 0.119 | 0.122 | 32 | 4,878 | 3,366 | 0.024 | 19,512 | 13,463 | 0.098 |
| similarity | 23,163 | 0.080 | 0.084 | 8 | 3,362 | 2,606 | 1.161 | 13,450 | 10,422 | 4.645 |

### Control (`english_r1_stage2_control.yaml`)
| task | train rows | sched. p | draw share | rows/draw | 5k draws | 5k updates | 5k passes | 20k draws | 20k updates | 20k passes |
|---|---|---|---|---|---|---|---|---|---|---|
| mlm | 15,500,570 | 0.490 | 0.398 | 8 | 15,908 | 4,991 | 0.008 | 63,633 | 19,965 | 0.033 |
| nli | 1,670,892 | 0.103 | 0.127 | 8 | 5,085 | 3,454 | 0.024 | 20,340 | 13,814 | 0.097 |
| paraphrase | 1,039,794 | 0.074 | 0.092 | 8 | 3,700 | 2,794 | 0.028 | 14,800 | 11,176 | 0.114 |
| qa | 442,809 | 0.041 | 0.052 | 8 | 2,066 | 1,767 | 0.037 | 8,264 | 7,069 | 0.149 |
| retrieval | 6,373,045 | 0.263 | 0.293 | 32 | 11,709 | 4,852 | 0.059 | 46,835 | 19,409 | 0.235 |
| similarity | 23,163 | 0.030 | 0.038 | 8 | 1,532 | 1,365 | 0.529 | 6,127 | 5,458 | 2.116 |

Against pilot 2 (about 190 NLI and 60 similarity updates in 2,000 steps at one task per micro-step) both runs give the pair tasks far more draws; the stage-2 run gives
NLI 1.33x, paraphrase 1.43x, QA 2.2x, similarity 2.2x the control's draws at 5,000 steps, and adds contrastive similarity (6,744 draws, 0.31 passes of 1.41 M pairs).

## Findings and risks (read before T204)
1. **The NLI gain over the control is small in draws (1.33x).** What differs for NLI is the balanced, VitaminC-extended stream and the cross-segment
   exposure from the pair-format MLM and contrastive rows, not the count of NLI batches. If stage 2 and the control look alike on NLI, exposure was not the limit.
2. **Similarity repeats its data.** 23,163 rows are seen 1.16 times in 5,000 steps and 4.6 times in 20,000 (control 0.53 and 2.1): a 20,000-step run
   would overfit the graded pairs unless the T208 shards 020-039 are graded or the similarity floor is lowered for the longer run. At 5,000 steps this is acceptable.
3. **Retrieval falls** from 0.293 to 0.122 of the draws; its stage-1 loss was 0.511 at the first pilot evaluation. The retrieval loss in the stage-2 log is the
   forgetting check; a rise above 10 % over its best for two evaluations is a T204 stop rule already.
4. **MLM falls** from 0.398 to 0.211 of the draws (0.004 passes at 5,000 steps either way: MLM is far from exhausted). Its loss is also a forgetting check.
5. **Unmeasured choices:** the floors, the warm-up of 300, the unchanged learning rate 2e-4 (a 2-task micro-step has a gradient about twice as large before
   clipping; `max_grad_norm` bounds it), loss weight 0.05 for similarity with the new head, graded pairs training the body, and the 2-task micro-step costing about
   1.9x a 1-task one (T202: 1.68 s against 0.88 s), so 5,000 steps are about 5000 x 4 x 1.68 s = 9.3 h of compute for each of the two runs (derived, not measured).
6. The control cannot exclude the T208 rows or the changed head by itself; it separates the mixture and tasks from the same compute, and T205 must say so.

## Verification
`tests/unit/language/test_stage2_schedule.py` (8 tests): inclusion probabilities equal the scheduler probabilities for one task per step, the closed form for two,
sum to `tasks_per_step`, agree with `sample_tasks` by Monte Carlo (30,000 draws, 0.01); every stage-2 floor binds exactly, pair tasks total 0.66, MLM draw share
between 0.18 and 0.25, no task below 0.07; the control equals the original mixture and has the same steps, warm-up, learning rate, batch sizes and
`tasks_per_step` as stage 2; every pair task has more draws in stage 2 than in the control.
