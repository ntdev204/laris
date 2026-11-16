# T201 — Mixed batches: several tasks in one micro-step

Implemented 2026-11-16. Fixture tests only: no training, no backward step, no optimizer step, no tokenizer fit, no run on the real
model. `tests/unit/language/test_mixed_batches.py` (15 run, 1 skipped unless the owner authorises training).

## What exists
- `tasks_per_step` (`TrainingConfig`, YAML or `--tasks-per-step`; default 1). Each **micro-step** (one forward/backward unit; an optimizer
  update still covers `gradient_accumulation_steps` of them) draws that many **different** tasks, adds their weighted losses and runs
  one backward pass over the sum. Effective batch per task is unchanged; an optimizer update now sees `tasks_per_step` x
  `gradient_accumulation_steps` task batches.
- Drawing: `TemperatureSamplingScheduler.sample_tasks` draws without replacement from the scheduler distribution renormalised over the
  tasks not yet drawn, so floors and the alpha shares govern the first draw as before; `count == 1` is `sample_task` with identical RNG use
  (tested: same sequence, same RNG state). `generate_step_batches(n)` on both loaders; a step of 1 is `generate_batch()` (tested: same
  task and token ids from the same seed). More tasks than active tasks is refused by the scheduler, the CLI and the profile.
- Trainer: `execute_training_step` takes one batch or a sequence. `_step_loss` runs the forward passes and returns the summed loss, each
  task's weighted loss and the order loss; the snapshot has `task_type` joined with `+` (`mlm+nli`), `loss_value` = the sum, and the new
  `task_losses` (every task of the step; also set for single-task steps). The progress bar folds each task's loss into its own running
  average. The loop passes `TrainingRunConfig.tasks_per_step`; checkpointing and counters are unchanged (one micro-step is one
  accumulation count). A step with the same task twice is refused. Evaluation is unchanged.
- The loss is the **sum**, as specified: a micro-step's gradient is about `tasks_per_step` times larger before clipping (`max_grad_norm`
  bounds it). The learning rate is not rescaled; whether to divide by the number of tasks is a T203/T204 choice.
- Profile: `profile_training_memory(..., tasks_per_step=n)` measures every task alone with its own peak counter (the earlier profile
  reported running maxima per task), then every combination of n tasks as one mixed step (worst group = measurement). The profile
  now includes the contrastive task when it is active. `--profile-only --tasks-per-step N` prints each group, the worst one and the
  latency per mixed step; a non-finite group or an OOM fails the profile.

## Memory estimate (derived from the T184 log, not measured)
Resident state of the 543,991,751-parameter model with fp32 AdamW: 16 bytes per parameter = 8.11 GiB. T184 single-task peaks (GB):
MLM 8.85, NLI 10.32, paraphrase 10.33, similarity 10.33, QA 10.91, retrieval 11.39, i.e. activations of about 0.74, 2.22, 2.22,
2.22, 2.80 and 3.28 GB. The graphs of all tasks of a step are alive at the backward pass, so the worst step adds the largest activations:

| tasks per step | worst group | estimated peak | limit 14.5 GB |
|---|---|---|---|
| 1 | retrieval | 11.39 GB (measured, T184) | fits |
| 2 | retrieval + QA | about 14.19 GB | fits by 0.31 GB; common pairs (for example MLM + NLI about 11.1 GB) fit easily |
| 3 | retrieval + QA + NLI | about 16.42 GB | does not fit at micro-batch 8 |

Caveats: the T184 per-task numbers are running maxima (the estimate errs high); allocator fragmentation is not modelled; the order
labels, the bi-encoder similarity (two single-sentence passes) and the contrastive task at batch 64 were not in T184. T202 replaces
this table with measured peaks. (`estimate_mixed_peak_gb` and `resident_state_gb` in `memory_profile.py` compute it; tested against these figures.)

## Prepared for T202
`docs/training/OWNER_RUNBOOK.md` section 10: the three profile commands (`--tasks-per-step` 1, 2, 3), the decision rule (largest
value that ends in `[SUCCESS]` with at least 0.3 GB margin) and the intake. `configs/language_encoder/english_r1_t202_profile.yaml`
is english_r1 with the order task, two-segment MLM, bi-encoder similarity, contrastive similarity and label balancing on; it is for the
profile only, not a training mixture (T203).

## Not measured
Whether mixing tasks reduces the pair heads chasing a moving representation (the reason for this task) is unmeasured; T204 tests it
against the one-task baseline. The foundation model remains NOT QUALIFIED.

## Note on the test run
The wider run `tests/unit tests/contract` (1,440 passed, 5 skipped) includes older tests that switch authorisation on inside the test
(`temporary_training_authorization`, for example `test_training_loop.py`) and take optimizer steps on toy CPU models. They existed before
this task and were executed as part of that run; no new test does so, and no training authorisation was enabled for the repository or the
environment.
