# T204 — stage-2 run and control run (Colab A100, 2026-11-19)

Status: measured on the **validation split**. The foundation model stays **NOT QUALIFIED**; no held-out gate was run.
Raw material: `reports/verification/T204/` (log tails with the validation tables, probe outputs). Checkpoints and full logs are on the owner's Drive in `runs/english-r1-stage2/` and `runs/english-r1-control/`.

## Setup (as prepared, runbook section 16)
Both arms: start from `english-r1-stage1-rerun/best` (fresh optimizer), micro-batch 32 x 1, 2 tasks per micro-step, retrieval batch 128, 5,000 steps, warm-up 300, lr 2e-4, seed 42, eval and save every 500,
checkpointing on, bf16, `--no-evaluate-after`. Colab A100-SXM4-40GB, Python 3.13.16, torch 2.14.1+cu130, code commit `f0845f0`. The agent started both runs under the owner's "Tự chạy đi" of 2026-11-19 (these two runs only).
Both ended `[SUCCESS]` at step 5,000; no NaN, no stop rule hit. Speed 1.7-1.8 s per optimizer step (profile bound was 3.78 s), peak 22.6 GB (profile 26.82 GB). About 2 h 30 min per arm; units 171.21 -> 115.56 including setup and probes.

## Validation, step 5,000 (stage-1 rerun at step 2,000: mean 0.6874, mlm 2.827, ret 0.3385, qa 0.6598)
| arm | mlm | nli | para | qa | ret | sim | mean |
|---|---|---|---|---|---|---|---|
| stage 2 | 2.5351 | 0.2046 | 0.0609 | 0.5641 | 0.3473 | 0.0020 | 0.6190 |
| control | 2.2930 | 0.2120 | 0.0616 | 0.5729 | 0.2428 | 0.0075 | 0.5650 |
The `sim` column is each arm's own head (stage 2 bi-encoder, control cross-encoder) and the mean mixes them: compare the other columns and the probes, not the mean.

## Forward-only probes (validation split, `scripts/diagnose_pair_path.py`, 600 rows)
| probe | stage 2 | control |
|---|---|---|
| STS-B similarity head Spearman | 0.840 (bi-encoder) | 0.203 (cross-encoder; siamese CLS cosine 0.740) |
| NLI all_nli accuracy (chance 0.333) | 0.455 | 0.432 |
| NLI anli accuracy | 0.333 | 0.322 |
| paraphrase PAWS AUC | 0.553 | 0.504 |
| paraphrase Quora AUC | 0.758 | 0.693 |
| sentence order, accuracy per source | 0.40-0.50 (majority 0.34-0.41) | 0.31-0.38 = majority (predicts "in_order" always) |
Stage-2 order head predicts "other_document" 50-78 % of the time, so its accuracy gain is partly a skewed prediction; it is above the majority baseline on 8 of 9 sources, not on Gutenberg.

## Reading (no more than the data supports)
- The stage-2 mixture does what T203 intended for the targeted tasks: similarity works (0.84 vs 0.20 head Spearman), order moves off chance, paraphrase and NLI rise slightly.
- It costs MLM (2.535 vs 2.293) and retrieval (0.347 vs 0.243) loss, as T203 expected from fewer draws; the control's MLM is still falling at 5,000 steps.
- NLI is only 0.455 on all_nli and about chance on ANLI; PAWS 0.553. The pair tasks that need graded or adversarial reasoning have not been learned in 5,000 steps. T205 decides the longer run.
- Caveats: the arms differ in several things at once (mixture, tasks, heads, batch composition); one seed each; validation split only, 600-row probes; the bi-encoder STS-B figure is on a task that sits in the stage-2 training mixture (STS-B train), not held-out.
- `scripts/measure_bi_encoder_head.py` was not run: it needs the relation-pair data (not on the VM) and `diagnose_pair_path.py` already reads the learned head directly.

## Findings
1. `diagnose_pair_path.py` crashed on a bi-encoder checkpoint (cross-encoder call). Fixed: section A uses `bi_encoder_similarity` when `similarity_head` is `bi_encoder`, section C is skipped for it.
2. `fineweb_edu_en/train.parquet` on Drive is still the truncated 8.70 GB file (10.05 GB expected); the VM copy was repaired by rsync and all 74 checksums matched. Re-upload it from `~/laris-colab-data` before the next session.
3. `colab exec` blocks while a long command runs and kills commands that outlive its timeout; long jobs need `setsid nohup ... &` and `colab ssh -s NAME -- CMD` for checks.
