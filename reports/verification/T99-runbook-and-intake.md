# T99 — Foundation round runbook and intake (prepared, not run)

Date: 2026-11-13 · Branch `feature/T99-training-runbook`. **Nothing was trained, profiled with an optimizer or fitted.** The only
model execution was inference for the baseline measurement below. The foundation model is **NOT QUALIFIED**.

## Deliverables

| Item | Where |
|---|---|
| Round plan, budget, timeouts, stop rules, decision gate | `docs/training/OWNER_RUNBOOK.md` section 7 (status PROPOSED) |
| Read-only intake of a returned run | `scripts/training_intake.py`, tests `tests/unit/scripts/test_training_intake.py` |
| Scorer for the Vietnamese STEM gold | `scripts/score_vi_stem_gold.py` (dev; sealed test needs `--final` and the seal digest) |

## Baseline measured for the plan (inference on `foundation-r1-run1`)

| Source | Dense MRR | BM25 MRR | Hybrid RRF MRR |
|---|---|---|---|
| SciFact dev (809 claims) | 0.0067 | 0.636 | 0.200 |
| Vietnamese STEM dev (137 queries, LLM gold, label 2) | 0.115 | 0.989 | 0.429 |

The run used `--retrieval-loss-weight 0`, so the CLS embedding was never trained to retrieve. The trainer adds the contrastive
term to the QA loss, so its effective weight is 0.15 times the flag; the plan therefore proposes weight 5.0.

## Findings for the owner

1. **The Vietnamese gold cannot show dense above BM25.** BM25 reaches 0.989 (rank 1 on 97.8 % of queries) because the queries were
   written from the passages. G12 asks dense above BM25 with MRR >= 0.82; on this gold that needs MRR above 0.989. It can
   track dense progress; the English SciFact test is the only discriminating G12 source unless the owner changes the gate or
   builds a lower-overlap query set.
2. **No STEM retrieval training pairs exist.** Round R2 trains the contrastive objective on general QA only, with in-batch
   negatives. If the probe gate fails (dense MRR < 0.02 on SciFact dev) the next step is a data decision, not more steps.
3. **Sources of the plan's numbers are estimates** (0.8 s/step with the contrastive term); the smoke log replaces them.
4. Section 7 uses `.venv/bin/python -m cli.model`; the `laris` and `laris-server` scripts in the current virtual environment fail
   to import (`cli.client` is gone on `laris-v2`).

## Intake check on the existing run

`scripts/training_intake.py --run-id foundation-r1-run1 ...` passes all 18 checks (weights equal the manifest hash, 10,000 of
10,000 steps, tokenizer hash equals the accepted candidate, peak 10.4 GiB, no NaN, no stale evaluations).

## Open for the owner

Approve (or change) the budget and run section 7 steps 0 to 6, or decide on the Vietnamese-gold and STEM-pair questions first.
T99 stays `blocked` until the returned logs and manifests pass the intake.
