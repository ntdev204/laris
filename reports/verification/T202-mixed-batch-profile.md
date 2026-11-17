# T202 — Memory and speed profile of the pair-remediation tasks and mixed batches (owner run)

Owner run 2026-11-17 on the RTX 5070 Ti (15.47 GB visible, limit 14.5 GB), `english_r1_t202_profile.yaml`, large model (543,995,596 parameters),
micro-batch 8, accumulation 4, bf16, gradient checkpointing, fp32 AdamW, 56k tokenizer, `--tasks-per-step` 1, 2 and 3.
Logs: `artifacts/profiles/english-r1-t202-profile-n{1,2,3}.log` (outside Git). The agent only read them; no training was run by the agent.

## Result
| `tasks_per_step` | outcome | measured peak | note |
|---|---|---|---|
| 1 | `[SUCCESS]` | **11.39 GB** | every task finite |
| 2 | `[SUCCESS]` | **13.12 GB** (similarity+retrieval) | all 21 pairs finite; 1.38 GB below the limit |
| 3 | `[FAIL]` CUDA out of memory | at least 14.16 GB allocated | 9 of the 3-task groups measured (largest 13.81 GB), then OOM with 14.16 GB allocated by PyTorch and 0.28 GB free |

**Chosen `tasks_per_step`: 2** (decision rule of runbook section 10: the largest value whose log ends in `[SUCCESS]` with a peak at least 0.3 GB below
14.5 GB; 3 failed). For 3 the exact worst group is not known: the log stops at the group that ran out of memory (by the loop order, the 10th,
`mlm+similarity+qa`; inferred, the log does not name it), and the 9 finished groups were already at 13.10 to 13.81 GB.

## Per task alone (identical in the three logs)
| task | peak GB |
|---|---|
| mlm (with order labels and two-segment rows) | 8.85 |
| nli | 10.32 |
| paraphrase | 10.33 |
| similarity (bi-encoder) | 11.39 |
| qa | 10.91 |
| retrieval | 11.39 |
| contrastive_sim (batch 64, length 128) | 10.05 |

Resident state is about 8.1 GiB (T201), so the activations of the new tasks are small: contrastive similarity adds about 1.9 GB and the order head and
two-segment rows nothing measurable on top of MLM (8.85, the T184 value).

## Mixed steps with 2 tasks (peak GB)
Highest: similarity+retrieval 13.12, similarity+qa 13.02, mlm+retrieval 12.86, similarity+contrastive_sim 12.76, qa+retrieval 12.72. Lowest: nli+contrastive_sim
11.75, paraphrase+contrastive_sim 11.75, paraphrase+nli 11.79, mlm+contrastive_sim 11.81. Every group stayed at least 1.38 GB below the limit.
With 3 tasks (9 groups finished): mlm+nli+retrieval 13.81, mlm+nli+similarity 13.79, mlm+paraphrase+retrieval 13.80, mlm+paraphrase+similarity 13.76,
lowest mlm+paraphrase+contrastive_sim 13.10.

## Estimate against measurement (T201)
| | estimate | measured |
|---|---|---|
| 1 task, worst | 11.4 GB | 11.39 GB |
| 2 tasks, worst | about 14.2 GB (retrieval+QA) | 13.12 GB (similarity+retrieval; retrieval+qa 12.72) |
| 3 tasks, worst | about 16.4 GB, does not fit | does not fit: OOM at 14.16 GB allocated |

The estimate was high for 2 (it added the two largest running maxima, but the activations of one task are freed before the next forward pass under
checkpointing) and right about 3. Which pair is worst changed: similarity (bi-encoder, two single-sentence passes) is the largest, not QA.

## Speed
One micro-batch (one task) 0.87 to 0.88 s including real data loading. A 2-task micro-step takes 1.68 s, so a 2-task micro-step costs about 1.9 times a
1-task one: mixed steps save no time per task batch, they put more tasks into each optimizer update. The log's "~3.5 s/optimizer step" line is 4 x 0.88 s
and is not the 2-task figure; the 2-task optimizer update is about 4 x 1.68 = 6.7 s (derived, not printed). Not measured: 3 tasks (it did not complete).

## Caveats
- The desktop session holds about 0.34 GB of the GPU (Xorg, gnome-shell, remote desktop), visible in the failed run (process 3680, 225 MiB). The limit of
  14.5 GB is against the 15.47 GB the process sees; a headless run would have a little more room but the margin for 3 tasks is not enough to rely on.
- The profile samples a few batches per task; a long run meets longer sequences. The 1.38 GB margin at 2 tasks covers that; allocator fragmentation under
  `expandable_segments` already showed warnings (failed mappings) once the memory was nearly full in the 3-task run.
- The profile does not pass `--dataset-sampling-ablation`, so the T207 weights were not applied; peaks do not depend on them (they depend on lengths).
- The gradient of a 2-task micro-step is about twice larger before clipping (`max_grad_norm` bounds it); the learning rate is unchanged (runbook).

## Consequence
T203 uses `tasks_per_step: 2`. If a later change raises the memory of the worst pair (a larger retrieval batch, a longer contrastive length), repeat the profile
with `--tasks-per-step 2` before a run.
