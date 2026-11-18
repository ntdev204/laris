# T211 — Speed and memory profile on the Colab A100 (owner run 2026-11-18)

Owner run on a Colab A100-SXM4-40GB (driver 580.82.07), `scripts/colab/speed_profile.sh` with `configs/language_encoder/english_r1_stage2.yaml`, `--tasks-per-step 2`,
large model (543,995,596 parameters), bf16, fp32 AdamW, `LARIS_VRAM_CEILING_GB=36` (ADR-023). The agent read the output the owner pasted; it did not run the profile.
The foundation model stays NOT QUALIFIED; these are speed and memory figures, not results.

## Result (every run `[SUCCESS]`, exit 0)
| micro-batch x accumulation | worst mixed step | peak | latency per 2-task micro-step | seconds per optimizer step (x accumulation, derived) |
|---|---|---|---|---|
| 8 x 4 | similarity+retrieval | 13.07 GB | 1.15 s | 4.60 s |
| 16 x 2 | similarity+qa | 16.63 GB | 1.75 s | 3.50 s |
| 32 x 1 | similarity+qa | 23.93 GB | 3.00 s | **3.00 s** |

Rule of runbook section 13 (lowest seconds per effective batch of 32 with a peak at least 2 GB below the 36 GB ceiling): **micro-batch 32, accumulation 1** (23.93 GB, 12 GB of margin).
Against the RTX 5070 Ti of T202 (1.68 s per 2-task micro-step of 8, so 6.7 s per optimizer step, derived): 1.46x at 8 x 4, 2.2x at 32 x 1. Memory matches T202 (13.12 GB there, 13.07 GB here).
Extrapolating the peak (+3.6 GB from 8 to 16, +7.3 GB from 16 to 32) gives about 38.5 GB at micro-batch 64: above the ceiling, so 32 is the largest micro-batch for an effective batch of 32.
5,000 optimizer steps at 3.00 s are about 4.2 h (derived; evaluation and checkpoints not included).

## Finding 1: the checkpointing "off" runs were not off
The six logs form three pairs with identical peak and latency. Cause (read in `src/cli/commands/language_encoder.py`): for the large model the config hard-coded
`gradient_checkpointing=True`; `--gradient-checkpointing` only reached the compact model. So all six runs checkpointed, and the saving from turning it off is **not measured**.
Fixed in this task: `--no-gradient-checkpointing` (large model; the default stays on, so no existing run changes) and `speed_profile.sh` passes it for the "off" runs; test added.

## Finding 2: micro-batch 32 with accumulation 1 changes the schedule of T203
Each optimizer step now holds one 2-task micro-step instead of four. Tasks whose batch follows the micro-batch (NLI, paraphrase, QA, similarity, MLM) keep the same rows per step
(2 draws x 32 rows = 8 draws x 8 rows). Retrieval (32 rows) and contrastive similarity (64 rows) have their own batch sizes, so they see **4x fewer rows per step**.
`scripts/plan_stage2_schedule.py --micro-batch-size 32 --grad-accum-steps 1` at 5,000 steps (computed):
| task | stage 2 draws (8 x 4 -> 32 x 1) | passes (8 x 4 -> 32 x 1) | control draws (32 x 1) |
|---|---|---|---|
| nli | 6,744 -> 1,686 | 0.032 -> 0.032 | 1,271 |
| similarity | 3,362 -> 841 | 1.161 -> 1.161 | 383 |
| qa | 4,543 -> 1,136 | 0.082 -> 0.082 | 516 |
| retrieval | 4,878 -> 1,220 | 0.024 -> **0.006** | 2,927 |
| contrastive similarity | 6,744 -> 1,686 | 0.306 -> **0.077** | none |
An update also averages only 2 task batches instead of up to 8, so its gradient is noisier. Options (owner decision, not made here): (a) keep 8 x 4 (4.6 s per step, 53 % slower, schedule of T203 unchanged);
(b) 32 x 1 with `retrieval_batch_size` 128 and `contrastive_sim_batch_size` 256 to restore their rows (4x more in-batch negatives, which changes the objective; memory and speed unmeasured: needs a profile);
(c) 16 x 2 (3.50 s) as a middle way, with retrieval and contrastive rows halved. The stage-2 run and its control must use the same choice.

## Not measured
Checkpointing off; micro-batch 32 with larger retrieval and contrastive batches; GPU utilisation and data-loader wait (the loader runs in the main process); TF32, fused AdamW and `torch.compile` (not in the training path).

## Follow-up profile: option (b), owner run 2026-11-18 (runbook section 14)
Micro-batch 32 x accumulation 1, `--tasks-per-step 2`, retrieval batch 128, contrastive batch 256 (stage 2 only; the control has no contrastive task), `LARIS_VRAM_CEILING_GB=36`, A100 40 GB.
| config | checkpointing | worst mixed step | peak | latency per optimizer step |
|---|---|---|---|---|
| stage 2 | on (default) | similarity+retrieval | **26.82 GB** | **3.78 s** |
| stage 2 | off (`--no-gradient-checkpointing`) | - | CUDA out of memory (39.33 GiB in use of 39.49) | - |
| control | on (default) | qa+retrieval | **23.82 GB** | **3.45 s** |
| control | off | - | CUDA out of memory (same figure) | - |
Decision (rule of section 14): checkpointing **stays on** (off does not fit at micro-batch 32; this is also the first run where the new flag had an effect). Both peaks are at least 7 GB below the 34 GB limit, so
the batches stay at retrieval 128 and contrastive 256 (no fall-back to 96/192). 5,000 steps take about 5.25 h for stage 2 and 4.8 h for the control (derived from the latency; evaluation and checkpoints not included),
about 35 and 32 compute units at the 6.73 units per hour that `colab usage` showed (derived). Compared with 8 x 4 (4.60 s per step at the old retrieval batch) the larger batches cost 18 % less time and keep the passes of T203.
Not measured: micro-batch 16 or 24 with checkpointing off (it might fit), TF32, fused AdamW, `torch.compile`, the data-loader wait.
