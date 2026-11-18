# T212 - Stage-1 rerun on the corrected data (agent-run 2026-11-18, owner permission)

The owner permitted the agent to run this one 2,000-step run ("Tôi cho phép bạn tự chạy 2000 bước"); it ran on the owner's Colab A100 (40 GB) with `LARIS_TRAINING_AUTHORIZED=1` and `--authorized` set for that command only.
Config `configs/language_encoder/english_r1_stage1_rerun.yaml` (pilot 2 settings plus the T207 weights, `--dataset-sampling-ablation`), micro-batch 8 x 4, one task per micro-step, `--steps 5000 --stop-after-steps 2000`,
seed 42, bf16, fp32 AdamW, run id `english-r1-stage1-rerun`, code commit `00f3c60`. Log and checkpoints: `MyDrive/laris/runs/english-r1-stage1-rerun/` (`best` and `last`, 13.06 GB, fsynced). The foundation model stays NOT QUALIFIED.

## Validation losses (val split, 16 batches per task), against pilot 2 (`english-r1-pilot2`)
| step | mlm | nli | para | qa | ret | sim | mean | pilot 2 mean | pilot 2 mlm |
|---|---|---|---|---|---|---|---|---|---|
| 500 | 3.5572 | 0.2183 | 0.0698 | 0.7525 | 0.5757 | 0.0067 | 0.8634 | 0.8506 | 3.536 |
| 1000 | 3.1508 | 0.2208 | 0.0716 | 0.6854 | 0.4424 | 0.0066 | 0.7630 | 0.7658 | 3.150 |
| 1500 | 2.9942 | 0.2212 | 0.1046 | 0.6575 | 0.3841 | 0.0072 | 0.7281 | 0.7174 | 2.944 |
| 2000 | 2.8272 | 0.2261 | 0.0636 | 0.6598 | 0.3385 | 0.0093 | **0.6874** | 0.6865 | 2.797 |
Retrieval fell from 0.5757 to 0.3385 (pilot 2: 0.2843 at step 2,000); QA 0.6598 (pilot 2: 0.7414); MLM 2.827 (pilot 2: 2.797). NLI (0.226 = 0.2 x ln 3 plus noise), paraphrase and similarity stayed at their chance-level values,
as in pilot 2: these losses are weighted and say nothing about the pair tasks beyond "not learned yet". Differences against pilot 2 are small (mean 0.6874 against 0.6865) and the runs differ in data and in the dataset weights,
so no difference is attributed to a cause.

## Speed and resources
1.3 to 1.4 s per optimizer step (320-350 ms per micro-batch of 8 rows), 45.6 min for 2,000 steps, peak 11.3 GB, about 5 compute units. During the run the training process showed one core at 100 % (load average
1.2 of 12) and one `nvidia-smi` sample read the GPU about 32 % busy. **Correction (T213, measured afterwards):** these two readings did not show that the data path was the bottleneck. The loader alone takes
11.6 ms per micro-step of 8 rows (about 3 % of the 350 ms), and a CPU thread waiting on a CUDA synchronisation also shows 100 %. The first draft of this report and of the T213 task named the data path as the cause; that was an
inference, and it was wrong. Rough arithmetic (not a measurement): a micro-batch of 8 rows of up to 1,024 tokens costs about 6 x 544 M x 8,192 x 4/3 = 3.6e13 FLOPs with checkpointing, about 115 ms at the A100's 312 TFLOPs bf16
peak, so 350 ms means about a third of peak if the rows are full length (lower if they are shorter). A large further gain from the loader is not available; kernel-level work (fused ops, `torch.compile`) is untested.

## Lineage
The manifest recorded `git_commit: None` because the VM has no `.git`. Fixed after the run: `current_git_commit` falls back to `LARIS_GIT_COMMIT` (set it from `artifacts/colab/COMMIT`); for this run the commit is `00f3c60`
(`artifacts/colab/COMMIT` at packing time). Tokenizer sha256 and dataset manifest hash are in the manifest. This checkpoint trained on the corrected data, so it carries no SQuAD v2 held-out rows; `best` (step 2,000) is the
`--init-from` of T204.
