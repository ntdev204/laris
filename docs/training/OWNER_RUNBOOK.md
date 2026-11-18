---
document_id: "DOC-RUNBOOK-OWNER-001"
title: "Owner-Executed Foundation Training and Evaluation"
document_type: "specification"
status: "DRAFT"
version: "1.4.0"
created_at: "2026-11-10"
updated_at: "2026-11-16"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: false
related_documents:
  - "docs/training/README.md"
  - "docs/specifications/LANGUAGE_ENCODER_TRAINING_SPECIFICATION.md"
decision_references:
  - "ADR-008"
change_summary: "Adds section 10 (T202 profile of the pair-remediation tasks and mixed batches); adds section 7 (T99 round plan for the R1 encoder), section 8 (R3) and section 9 (English stage 1, D46); sections 7 and 8 are historical."
---

# Owner runbook

All commands run from the repository root. The owner alone executes training and
authorized profiling. Agents only validate syntax and prepare files. No command
in this document authorizes an agent to perform training, fitting or optimizer steps.

## 1. Inspect readiness first

The existing tokenizer can be reused; no refitting is needed for this handoff.
Preserve the existing checkpoints and split manifest. Stop CARLA or other GPU
workloads before the owner starts GPU work.

```bash
.venv/bin/laris-server data check --verify-sha256
.venv/bin/laris-server evaluate readiness \
  --reports reports/language_encoder/compact-1024-04-best-val.json \
  --output artifacts/readiness/current-foundation.json
```

The last command should exit **1 / NOT QUALIFIED** for the historical checkpoint.
Exit 0 means the supplied report contracts meet all configured formal gates;
exit 2 means invalid input. This offline command does not load a model.

F01 added normalized answer-text QA. F04 found gaps in several validation
metrics, split collisions in STS-B and alternative answer offset errors in ViQuAD.
The existing tokenizer exceeds both fertility limits. G12 still needs independent
STEM relevance judgments. The runs below measure a sampling change on validation.
There is no model 02 training command at this stage.

## 2. Owner environment

Only if dependencies are missing:

```bash
uv pip install --python .venv/bin/python -e '.[dev,training]'
```

Confirm the CUDA/PyTorch build supports the GPU and preserve a package-version
snapshot with the run metadata. Installation does not establish training feasibility.

## 3. Owner-only training-memory measurement

This command performs backward and real optimizer steps on a discarded model.
It counts as training and MUST NOT be executed by an agent under this task.
Use the same configuration as the proposed run. A forward-only measurement does
not certify training memory; if this exceeds 14.5 GB, lower the micro-batch and
increase accumulation to preserve the intended effective batch.

```bash
LARIS_TRAINING_AUTHORIZED=1 .venv/bin/laris-server train language-encoder \
  --profile-only --model-size compact --max-seq-len 1024 \
  --training-config configs/language_encoder/compact.yaml \
  --micro-batch-size 4 --grad-accum-steps 16 --precision bf16 --no-8bit-adam \
  --tokenizer-model artifacts/tokenizer/laris_spm_32k.model
```

## 4. Owner-only sampling comparison

Both rounds load weights from the same compact checkpoint and start with a fresh
optimizer, schedule and counters. Use the existing tokenizer and identical seed,
batch, validation settings and five-task loss weights. The sampling round applies
dataset count exponent 0.7 within NLI, paraphrase and QA. The baseline uses source
row counts directly. Task selection keeps exponent 0.7 in both rounds.
[Approved budget](FOUNDATION_BUDGET.md)

Use unused run IDs. The comparison uses peak LR 2e-5 and 50 warmup steps as an
initial warm-start setting. Within each round, reserve 10 steps and 120 seconds
for smoke, 1,990 steps and 3,180 seconds for the main run, and 300 seconds for
validation inference. Across both rounds this caps GPU commands at 2 hours.
Each command has a hard timeout. A timed-out run may retain only a previously
saved checkpoint. Record its exit status and use the remaining approved budget
for any retry.

### Run smoke checks and return the logs

Stop other GPU workloads and run the two commands below sequentially. Return the
two logs with peak memory, final validation loss, and checkpoint manifests before
starting the main runs. Validate the checksums of the current processed shards
using the command in section 1.

```bash
set -o pipefail
mkdir -p artifacts/profiles
LARIS_TRAINING_AUTHORIZED=1 timeout -s KILL 120s .venv/bin/laris-server train language-encoder \
  --authorized --model-size compact --max-seq-len 1024 \
  --training-config configs/language_encoder/compact.yaml \
  --init-from artifacts/checkpoints/language_encoder/compact-1024-04/best \
  --micro-batch-size 4 --grad-accum-steps 16 --precision bf16 --no-8bit-adam \
  --steps 10 --learning-rate 0.00002 --warmup-steps 0 \
  --eval-interval 500 --eval-batches 16 --save-interval 500 --patience 3 --seed 42 \
  --tokenizer-model artifacts/tokenizer/laris_spm_32k.model \
  --retrieval-loss-weight 0 --run-id foundation-f05-baseline-smoke --no-evaluate-after \
  2>&1 | tee artifacts/profiles/foundation-f05-baseline-smoke.log

LARIS_TRAINING_AUTHORIZED=1 timeout -s KILL 120s .venv/bin/laris-server train language-encoder \
  --authorized --model-size compact --max-seq-len 1024 \
  --training-config configs/language_encoder/compact.yaml \
  --init-from artifacts/checkpoints/language_encoder/compact-1024-04/best \
  --micro-batch-size 4 --grad-accum-steps 16 --precision bf16 --no-8bit-adam \
  --steps 10 --learning-rate 0.00002 --warmup-steps 0 \
  --eval-interval 500 --eval-batches 16 --save-interval 500 --patience 3 --seed 42 \
  --tokenizer-model artifacts/tokenizer/laris_spm_32k.model \
  --retrieval-loss-weight 0 --dataset-sampling-ablation --run-id foundation-f05-sampling-smoke --no-evaluate-after \
  2>&1 | tee artifacts/profiles/foundation-f05-sampling-smoke.log
```

### Main comparison after smoke review

Each run starts again from the reference weights. Validation runs every 500
optimizer steps and at the final step. Patience 3 monitors mean validation loss
with the existing minimum improvement of 0.0001. Compare matched-step records
when one round stops early.

```bash
set -o pipefail
LARIS_TRAINING_AUTHORIZED=1 timeout -s KILL 3180s .venv/bin/laris-server train language-encoder \
  --authorized --model-size compact --max-seq-len 1024 \
  --training-config configs/language_encoder/compact.yaml \
  --init-from artifacts/checkpoints/language_encoder/compact-1024-04/best \
  --micro-batch-size 4 --grad-accum-steps 16 --precision bf16 --no-8bit-adam \
  --steps 1990 --learning-rate 0.00002 --warmup-steps 50 \
  --eval-interval 500 --eval-batches 16 --save-interval 500 --patience 3 --seed 42 \
  --tokenizer-model artifacts/tokenizer/laris_spm_32k.model \
  --retrieval-loss-weight 0 --run-id foundation-f05-baseline-run --no-evaluate-after \
  2>&1 | tee artifacts/profiles/foundation-f05-baseline-run.log

LARIS_TRAINING_AUTHORIZED=1 timeout -s KILL 3180s .venv/bin/laris-server train language-encoder \
  --authorized --model-size compact --max-seq-len 1024 \
  --training-config configs/language_encoder/compact.yaml \
  --init-from artifacts/checkpoints/language_encoder/compact-1024-04/best \
  --micro-batch-size 4 --grad-accum-steps 16 --precision bf16 --no-8bit-adam \
  --steps 1990 --learning-rate 0.00002 --warmup-steps 50 \
  --eval-interval 500 --eval-batches 16 --save-interval 500 --patience 3 --seed 42 \
  --tokenizer-model artifacts/tokenizer/laris_spm_32k.model \
  --retrieval-loss-weight 0 --dataset-sampling-ablation --run-id foundation-f05-sampling-run --no-evaluate-after \
  2>&1 | tee artifacts/profiles/foundation-f05-sampling-run.log
```

## 5. Validation and handoff

```bash
timeout -s KILL 300s .venv/bin/laris-server evaluate language-encoder \
  --checkpoint artifacts/checkpoints/language_encoder/foundation-f05-baseline-run/best \
  --tokenizer-model artifacts/tokenizer/laris_spm_32k.model \
  --split val --max-samples 512 --batch-size 8 --seed 42 --device cuda \
  --output artifacts/evaluations/language_encoder/foundation-f05-baseline-val.json

timeout -s KILL 300s .venv/bin/laris-server evaluate language-encoder \
  --checkpoint artifacts/checkpoints/language_encoder/foundation-f05-sampling-run/best \
  --tokenizer-model artifacts/tokenizer/laris_spm_32k.model \
  --split val --max-samples 512 --batch-size 8 --seed 42 --device cuda \
  --output artifacts/evaluations/language_encoder/foundation-f05-sampling-val.json
```

Return each log, the effective configuration in the manifest, the best/last
checkpoint manifests and model SHA-256, the dataset manifest hash, and validation
reports. Keep weights and raw logs under ignored artifact paths. Report aborted
runs with the exit status and actual steps reached.

F05 also provides the train-only query-to-passage contrastive auxiliary loss.
A positive weight in `--retrieval-loss-weight` enables it on QA batches with
at least two answerable pairs. Queries and contexts are encoded separately.
The loss compares normalized CLS embeddings and treats duplicate encoded
queries or passages as additional positives. Other in-batch passages are
assumed negatives. Both sampling comparison rounds use weight zero. A future
retrieval ablation needs its own budget and memory profile with a positive weight.
General-domain QA relevance is training supervision for that objective.
The G12 evaluation requires independent STEM relevance and a BM25 comparison.

The validation reports are diagnostic. F07 requires held-out evidence with the
same model/tokenizer identity and all configured protocols. Keep the STS-B split
and ViQuAD offset findings open until the dataset revision is audited and frozen.

## 5b. F07 held-out evidence (inference only)

Run this only after F06-R1 has fixed the tokenizer and produced the final candidate;
nothing below trains, fits or optimises. Score the test sources **once** with the final
model and tokenizer, because the query sets are frozen and the test must not guide any
further choice. `<CHECKPOINT>` and `<TOKENIZER>` are the F06-R1 candidate and its tokenizer. Use `--normalize-input` only for a model trained with it (the F06-R1 run must pass
the same flag); the fit corpus for the leakage scan is the one the tokenizer was fitted on.

```bash
.venv/bin/python -m language.benchmarks.fertility \
  --tokenizer-model <TOKENIZER> --normalize-input \
  --fit-corpus artifacts/tokenizer/foundation-r1-super/fit-actual.txt \
  --output reports/tokenizer/foundation-f07.json
.venv/bin/python -m language.benchmarks.retrieval run \
  --checkpoint <CHECKPOINT> --tokenizer-model <TOKENIZER> \
  --output reports/retrieval/foundation-f07.json
```

The retrieval run verifies every frozen digest and SHA-256 before scoring. Only
`scifact_test_en` (expert relevance judgements) can satisfy G12; the SQuAD/ViQuAD sources
and the machine-translated `stem_vi_crosslingual_en_to_vi` diagnostic are reported under
`paragraph_retrieval` and never gate. G12 stays incomplete for Vietnamese until a source
with human relevance exists. SciFact is non-commercial: record the licence decision before
the run and do not redistribute the data.

### Development measurement before F06-R1 (inference only, 2026-11-11)

Scored on SciFact **train** claims (809 queries, 919 expert judgements; the sealed test claims
were not read) with the F06 sampling checkpoint; report `reports/retrieval/foundation-scifact-dev.json`:

| System | MRR | recall@10 |
| --- | --- | --- |
| BM25 | 0.636 | 0.801 |
| Dense (CLS embedding) | 0.012 | 0.017 |
| Hybrid RRF | 0.205 | 0.633 |

The same pattern appears on the earlier general-domain measurement (SQuAD dense 0.034 vs BM25
0.783). F06 ran with `--retrieval-loss-weight 0`, so the CLS embedding was never trained to
retrieve. G12 requires dense to beat BM25, so a tokenizer fix alone cannot pass it. The F06-R1
budget needs a retrieval-contrastive stage with a positive `--retrieval-loss-weight`, which the
runbook already says needs its own budget and memory profile. This measurement is diagnostic and
does not qualify the model.

The machine-translated STEM-VI diagnostic (EN abstract to its Vietnamese translation, 2,000 sampled
pairs, relevance by construction; `reports/retrieval/foundation-stem-vi-diagnostic.json`) shows the
same gap: dense MRR 0.019 (recall@10 0.036) against BM25
0.484 and hybrid 0.187. BM25 matches across languages only
through shared tokens (Latin names, numbers); the dense score is close to chance for 2,000 candidates
(about 0.004). It is a diagnostic, never a G12 source.

## 6. Stage boundary

Passing foundation report checks is a review prerequisite, not an automatic command
to train model 02. The owner reviews the complete held-out evidence first. Scientific
language is implemented and evaluated next; OCR, manuscripts, integration and later
specialists must not be advanced through the historical paper pilot.

> **Historical since D46 / ADR-022 (2026-11-14).** Sections 7 and 8 describe rounds R1-R3a of the EN+VI encoder with the 48k tokenizer. They stay as the record of what was run; their Vietnamese data, `score_vi_stem_gold.py` steps and Vietnamese gates are withdrawn from stage 1. Do not start R3b. The next owner runs are in section 9.

> **D46 / ADR-022 (2026-11-14):** sections 7 and 8 describe rounds on the English+Vietnamese R1 tokenizer. They are measured history and
> are **not to be rerun**; every Vietnamese command (`score_vi_stem_gold.py`, VI datasets) is withdrawn from stage 1. Section 9 is the current path.

## 7. T99: foundation rounds for the R1 encoder (48k tokenizer)

Status: **EXECUTED 2026-11-13 by the owner; results in 7.9 and `reports/verification/T99-r2-analysis.md`.** The text below is the plan as proposed (8 GB budget while CARLA held the GPU); the run itself used the full GPU with `--gradient-checkpointing` at 16 x 4. Sections 3 to 5b describe the historical 32k
tokenizer; their `laris` and `laris-server` commands also name scripts that the current virtual environment no
longer imports. Use `.venv/bin/python -m cli.model` as below. Nothing here authorizes an agent to train, profile with an
optimizer or set `LARIS_TRAINING_AUTHORIZED`. The foundation model is **NOT QUALIFIED**.

### 7.1 Evidence this plan rests on

| Fact | Source |
|---|---|
| `foundation-r1-run1`: 10,000 steps, effective batch 64 (16 x 4), 0.4-0.5 s/step, 1 h 24 min, peak 10.4 GiB, validation mean loss 0.3827 and still falling at the last evaluation; `--retrieval-loss-weight 0` | `artifacts/profiles/foundation-r1-run1.log`, best manifest |
| Dense retrieval is at chance because the CLS embedding was never trained to retrieve: SciFact dev MRR 0.0067 against BM25 0.636 | `reports/retrieval/foundation-r1-run1-scifact-dev.json` |
| Vietnamese STEM dev (LLM gold): dense MRR 0.115, BM25 0.989, hybrid 0.429 | `reports/retrieval/foundation-r1-run1-vi-stem-dev.json` |
| The contrastive term is added to the QA loss, so its effective weight is `loss_lambda_qa` (0.15) x `--retrieval-loss-weight` | `src/laris/research/language/training/trainer.py` |
| In-batch negatives only; no hard negatives; supervision comes from the general-domain QA shards (SQuAD, HotpotQA, ViQuAD v2) | trainer, `data/processed` |

Two consequences. First, gate G12 (dense MRR >= 0.82 and above BM25) cannot be reached by more of the same training: it
needs the retrieval objective. Second, BM25 scores 0.989 on the Vietnamese gold because its queries were written from
the passages, so that gold can show dense progress but **cannot show dense above BM25**; the English SciFact test is the
only discriminating G12 source until the owner decides otherwise.

### 7.2 Data rules for every round

Do not train on VIPUBMED (licence not cleared), on `data/processed/gold_vi_stem/`, on SciFact claims (dev or test) or on
any held-out test split. Round R2 uses only the existing QA shards. STEM-domain retrieval pairs do not exist yet; if the
probe fails the decision gate, adding licensed STEM pairs is a separate task and budget.

### 7.3 Round plan and budget (owner-approved when run)

| Step | What | GPU time (estimate) | Hard timeout |
|---|---|---|---|
| 0 | Development measurements of `foundation-r1-run1` (inference only) | 10 min | 600 s each |
| 1 | Memory profile of the R2 configuration under the 8 GB budget (optimizer steps, owner only) | 5 min | 300 s per attempt |
| 2 | Smoke run, 20 steps | 1 min | 180 s |
| 3 | Probe `foundation-r2-probe`: 1,000 steps, retrieval weight 5.0 | 18 min | 2,400 s |
| 4 | Decision gate on the probe (inference only) | 10 min | 600 s each |
| 5 | Main round `foundation-r2`: 4,000 steps | 72 min | 9,000 s |
| 6 | Development measurements and intake of `foundation-r2` | 20 min | 600 s each |

Total at most about 3 h of GPU time and two training runs. A step estimate of about 1.0 s per step assumes the two extra
encoder passes for QA batches cost at most 60 % more than the 0.5 s measured without them, and that activation
checkpointing (needed for the 8 GB budget, 7.5) adds about 25 %; the smoke log replaces this estimate. Stop other GPU workloads first. After this budget, stop and review before any further round.

### 7.4 Step 0: development measurements (inference only)

```bash
export HOME_ISOLATED=$(mktemp -d)
R1=artifacts/checkpoints/language_encoder/foundation-r1-run1/best
TOK=artifacts/tokenizer/foundation-r1-super/candidate/laris_spm_48k_r1.model
mkdir -p artifacts/evaluations/language_encoder
HOME=$HOME_ISOLATED timeout -s KILL 600s .venv/bin/python -m cli.model evaluate language-encoder \
  --checkpoint $R1 --tokenizer-model $TOK --split val --max-samples 2048 --batch-size 8 \
  --seed 42 --device cuda --output artifacts/evaluations/language_encoder/foundation-r1-run1-val.json
```

Read the validation report against the gate thresholds. If G01-G09 are far below target on validation, record it: more
retrieval training will not fix them and a later general round (7.9) has to be planned. The development retrieval numbers
of R1 already exist (see 7.1).

### 7.5 Step 1: memory profile under 8 GB (owner only)

This performs backward and optimizer steps on a discarded model. `foundation-r1-run1` peaked at 10.4 GiB with micro-batch 16
and no checkpointing, so that setting does not fit 8 GB. The contrastive term encodes queries and passages in two extra passes,
so it needs more. Try the attempts in order; the first one whose peak CUDA allocation is **<= 7.0 GiB** (leave about 1 GiB
for the CUDA context and fragmentation next to CARLA) is used in every later command. The effective batch stays 64.

| Attempt | `MB` | `ACC` | `CKPT` | In-batch negatives per query (QA) |
|---|---|---|---|---|
| a | 8 | 8 | (empty) | about 7 |
| b | 16 | 4 | `--gradient-checkpointing` | about 15 |
| c | 8 | 8 | `--gradient-checkpointing` | about 7 |
| d | 4 | 16 | `--gradient-checkpointing` | about 3 |

Attempt b is preferred if it fits: the same negatives as R1 at about 25 % more time per step. Fewer negatives weaken the
contrastive signal; if you end on c or d, say so in the return and expect the probe gate to be harder. The flag changes memory
and speed only; the weights and the saved model config stay compatible with `--init-from`.

```bash
MB=16; ACC=4; CKPT="--gradient-checkpointing"     # attempt b; edit for another attempt
mkdir -p artifacts/profiles
LARIS_TRAINING_AUTHORIZED=1 timeout -s KILL 300s .venv/bin/python -m cli.model train language-encoder \
  --profile-only --model-size compact --vocab-size 48000 --max-seq-len 1024 \
  --training-config configs/language_encoder/compact_r1.yaml \
  --micro-batch-size $MB --grad-accum-steps $ACC $CKPT --precision bf16 --no-8bit-adam \
  --retrieval-loss-weight 5.0 --tokenizer-model $TOK --normalize-input \
  2>&1 | tee artifacts/profiles/foundation-r2-profile.log
```

If every attempt exceeds 7.0 GiB, stop and tell the agent; do not raise the ceiling while CARLA is running.

### 7.6 Step 2 and 3: smoke, then the probe

Each run starts from the R1 best checkpoint with a fresh optimizer and schedule. Never use a 32k checkpoint.

```bash
set -o pipefail
for RUN in "smoke 20 240 foundation-r2-smoke 0" "probe 1000 2400 foundation-r2-probe 100"; do
  set -- $RUN
  LARIS_TRAINING_AUTHORIZED=1 timeout -s KILL ${3}s .venv/bin/python -m cli.model train language-encoder \
    --authorized --model-size compact --vocab-size 48000 --max-seq-len 1024 \
    --training-config configs/language_encoder/compact_r1.yaml \
    --init-from $R1 --micro-batch-size $MB --grad-accum-steps $ACC $CKPT --precision bf16 --no-8bit-adam \
    --steps $2 --learning-rate 0.00005 --warmup-steps $5 \
    --eval-interval 250 --eval-batches 16 --save-interval 250 --patience 4 --seed 42 \
    --tokenizer-model $TOK --normalize-input --retrieval-loss-weight 5.0 \
    --run-id $4 --no-evaluate-after 2>&1 | tee artifacts/profiles/$4.log
done
```

Return both logs before continuing. Smoke pass: finite losses, no out-of-memory, peak memory in the log <= 7.0 GiB, step time
recorded. Watch `nvidia-smi`: if CARLA's footprint grows, the run can fail with an out-of-memory error; that ends the run, it is
not a result.

### 7.7 Step 4: probe decision gate (inference only)

```bash
P=artifacts/checkpoints/language_encoder/foundation-r2-probe/best
HOME=$HOME_ISOLATED timeout -s KILL 600s .venv/bin/python -m laris.research.language.benchmarks.retrieval run \
  --config configs/evaluation/foundation_retrieval_dev.yaml --checkpoint $P --tokenizer-model $TOK \
  --output reports/retrieval/foundation-r2-probe-scifact-dev.json
HOME=$HOME_ISOLATED timeout -s KILL 600s .venv/bin/python scripts/score_vi_stem_gold.py --split dev \
  --checkpoint $P --tokenizer-model $TOK --output reports/retrieval/foundation-r2-probe-vi-stem-dev.json
.venv/bin/python scripts/training_intake.py --run-id foundation-r2-probe --expect-steps 1000 \
  --expect-retrieval-weight 5.0 --tokenizer-model $TOK --init-run foundation-r1-run1 \
  --reference-run foundation-r1-run1 --log artifacts/profiles/foundation-r2-probe.log --max-peak-gib 7.5
```

Decision (SciFact **dev**, never the sealed test): continue to step 5 only if dense MRR >= 0.10 and the intake passes.
If dense MRR is between 0.02 and 0.10, change one thing (retrieval weight 10.0, or micro-batch 32 x 2 if memory allows) and
rerun the probe once. Below 0.02, stop: the in-batch objective on general QA is not enough and the owner decides on STEM
pairs or hard negatives.

### 7.8 Step 5: main round R2

Same command as the probe with `--steps 4000 --warmup-steps 200`, `--run-id foundation-r2`, timeout 9,000 s, and the
retrieval weight chosen at the gate and the same `MB`, `ACC`, `CKPT`. Stop rules (any one ends the round; keep the last saved checkpoint):

1. four validation points in a row without improvement of the mean loss (`--patience 4`, interval 250);
2. a non-finite loss or an out-of-memory error (CARLA competing for memory counts; rerun with the next smaller attempt);
3. the hard timeout;
4. at intake: any of MLM, NLI, paraphrase or similarity validation loss more than 10 % above `foundation-r1-run1`
   (forgetting), or a failed integrity check. The round is then not accepted.

Then run step 6:

```bash
R2=artifacts/checkpoints/language_encoder/foundation-r2/best
.venv/bin/python scripts/training_intake.py --run-id foundation-r2 --expect-steps 4000 \
  --expect-retrieval-weight <WEIGHT> --tokenizer-model $TOK --init-run foundation-r1-run1 \
  --reference-run foundation-r1-run1 --log artifacts/profiles/foundation-r2.log --max-peak-gib 7.5 \
  --report reports/verification/T99-foundation-r2-intake.json
HOME=$HOME_ISOLATED timeout -s KILL 600s .venv/bin/python -m cli.model evaluate language-encoder \
  --checkpoint $R2 --tokenizer-model $TOK --split val --max-samples 2048 --batch-size 8 --seed 42 \
  --device cuda --output artifacts/evaluations/language_encoder/foundation-r2-val.json
HOME=$HOME_ISOLATED timeout -s KILL 600s .venv/bin/python -m laris.research.language.benchmarks.retrieval run \
  --config configs/evaluation/foundation_retrieval_dev.yaml --checkpoint $R2 --tokenizer-model $TOK \
  --output reports/retrieval/foundation-r2-scifact-dev.json
HOME=$HOME_ISOLATED timeout -s KILL 600s .venv/bin/python scripts/score_vi_stem_gold.py --split dev \
  --checkpoint $R2 --tokenizer-model $TOK --output reports/retrieval/foundation-r2-vi-stem-dev.json
```

Return: the three logs, the intake report, the two manifests with model SHA-256, and the three development reports. The
agent then writes the per-gate analysis (T99 validation) from them. Validation and development numbers are diagnostic and
are not held-out evidence.

### 7.9 Conditional round R3 (not approved)

Only if step 0 shows G01-G09 far below target and R2 is accepted: continue general training from `foundation-r2/best`
with the retrieval weight kept, about 6,000 steps, peak learning rate 3e-5. It needs its own budget sign-off after the R2
review; no command is given here on purpose.

### 7.10 What T100 does next

T100 scores the sealed held-out sources once per candidate (fertility, retrieval, the evaluation suite) and the sealed
Vietnamese test split with `scripts/score_vi_stem_gold.py --split test --final --seal-sha256 <digest>`. Do not run any of
that on the R2 candidate until the owner has reviewed the T99 analysis.

### 7.9 What was run and found (added after the owner's run)

| Item | Result |
|---|---|
| Configuration used | 16 x 4 (effective 64), `--gradient-checkpointing`, bf16, retrieval weight 5.0, learning rate 5e-5, warmup 200, from `foundation-r1-run1/best`, 4,000 steps, patience 4 |
| Why checkpointing | 16 x 4 without it ran out of memory twice (14.5-14.8 GiB) in the QA task that carries the contrastive term |
| Measured | peak 3.9-4.0 GiB, 0.6 s/step median, main round about 45 min (the 1.0 s/step estimate above was too high) |
| Probes | 16 x 4: SciFact dev dense MRR 0.0513. 32 x 2: 0.0454 and paraphrase loss +12.8 %, intake FAIL |
| Decision gate | not met by either probe (>= 0.10); the owner ran the main round anyway as an exploratory extension |
| Main round | intake 18/18; SciFact dev dense 0.1285 (BM25 0.636, hybrid 0.3417); Vietnamese gold dev dense 0.3915 (BM25 0.989) |
| Validation (`val`, 2,048 samples) | 6 of 9 development checks pass; QA-VI, similarity EN and VI fail |

No gate is close (per-gate table in the report). Round R3 is not approved. T100 (sealed test) is not run until the
owner reads the analysis. Evaluate on `val` with `--max-samples 2048` needs `timeout 1800s`; 600 s kills it.

## 8. T99: round R3, a mixture that shows the weak tasks more (R3a APPROVED 2026-11-14, owner run pending)

Status: **R3a APPROVED by the owner on 2026-11-14 (not yet run); R3b stays unapproved until R3a is analysed.** The owner runs it. The agent prepared the commands and the config and runs only inference and the intake. The foundation model is
**NOT QUALIFIED**; R2 has no gate close (`reports/verification/T99-r2-analysis.md`).

### 8.1 What changes and why

`reports/verification/T99-paws-and-mixture.md` found that R1 and R2 gave every task less than one pass over its data
(PAWS about 0.23, similarity 0.51) because tasks were drawn in proportion to size^0.7 and the CLI never exposed that
temperature. R3 changes **the mixture, not the model or the loss**:

| Setting | R1 / R2 | R3 |
|---|---|---|
| Task temperature alpha (`training.task_sampling_alpha`, new, default 0.7) | 0.7 | **0.4** |
| Micro-batch share MLM / NLI / paraphrase / QA / similarity | 61.5 / 21.4 / 9.6 / 6.0 / 1.4 % | **44.0 / 24.1 / 15.2 / 11.7 / 5.1 %** |
| Dataset exponent within NLI, paraphrase, QA (`--dataset-sampling-ablation`) | none (1.0) | **0.7** (PAWS 13 % to 21 % of the paraphrase draws) |
| Start | R1 best | **`foundation-r2/best`**, fresh optimizer |
| Retrieval weight, learning rate, model, tokenizer, batch | 5.0, 5e-5, compact 48k, 16 x 4 with checkpointing | unchanged |

Expected passes in 5,000 steps (R3a): paraphrase 0.13, QA 0.19, similarity 0.65; in 20,000 steps: 0.51, 0.76 and 2.6
(computed from the scheduler, not measured). Validation samples keep the old mixture, so validation losses stay
comparable with R1 and R2. The contrastive term is added on QA micro-batches, whose share doubles (6 % to 11.7 %); that
may move retrieval and forgetting, so both are measured.

### 8.2 Data rules, budget, stop rules

Same data rules as 7.2: no VIPUBMED, no `gold_vi_stem`, no SciFact claims, no held-out test, no S2ORC (stage 2). Stop
other GPU workloads first. R3a: 5,000 steps at about 0.6 s/step is about 50 min plus evaluations (timeout 5,400 s). R3b,
only after the decision below: 20,000 steps, about 3.5 h (timeout 18,000 s). Stop rules for both: four validation points
without improvement (`--patience 4`), a non-finite loss, an out-of-memory error, the timeout, or at intake any task loss
more than 10 % above `foundation-r2`.

### 8.3 Round R3a (owner run)

```bash
export HOME_ISOLATED=$(mktemp -d)
R1=artifacts/checkpoints/language_encoder/foundation-r1-run1/best
R2=artifacts/checkpoints/language_encoder/foundation-r2/best
TOK=artifacts/tokenizer/foundation-r1-super/candidate/laris_spm_48k_r1.model
MB=16; ACC=4; CKPT="--gradient-checkpointing"
echo "MB=$MB ACC=$ACC CKPT=[$CKPT]"      # CKPT must show the flag
set -o pipefail
LARIS_TRAINING_AUTHORIZED=1 timeout -s KILL 5400s .venv/bin/python -m cli.model train language-encoder \
  --authorized --model-size compact --vocab-size 48000 --max-seq-len 1024 \
  --training-config configs/language_encoder/compact_r3.yaml --dataset-sampling-ablation \
  --init-from $R2 --micro-batch-size $MB --grad-accum-steps $ACC $CKPT --precision bf16 --no-8bit-adam \
  --steps 5000 --learning-rate 0.00005 --warmup-steps 200 \
  --eval-interval 500 --eval-batches 16 --save-interval 500 --patience 4 --seed 42 \
  --tokenizer-model $TOK --normalize-input --retrieval-loss-weight 5.0 \
  --run-id foundation-r3a --no-evaluate-after 2>&1 | tee artifacts/profiles/foundation-r3a.log
```

The header must show `Micro-Batch / Accum: 16 / 4` and `Activation Checkpointing: ENABLED`.

### 8.4 Measurements after R3a (inference only)

```bash
R3A=artifacts/checkpoints/language_encoder/foundation-r3a/best
.venv/bin/python scripts/training_intake.py --run-id foundation-r3a --expect-steps 5000 \
  --expect-retrieval-weight 5.0 --tokenizer-model $TOK --init-run foundation-r2 --reference-run foundation-r2 \
  --log artifacts/profiles/foundation-r3a.log --max-peak-gib 14.5 --report reports/verification/T99-foundation-r3a-intake.json
HOME=$HOME_ISOLATED timeout -s KILL 1800s .venv/bin/python -m cli.model evaluate language-encoder \
  --checkpoint $R3A --tokenizer-model $TOK --split val --max-samples 2048 --batch-size 8 --seed 42 \
  --device cuda --output artifacts/evaluations/language_encoder/foundation-r3a-val.json
HOME=$HOME_ISOLATED timeout -s KILL 900s .venv/bin/python -m laris.research.language.benchmarks.retrieval run \
  --config configs/evaluation/foundation_retrieval_dev.yaml --checkpoint $R3A --tokenizer-model $TOK \
  --output reports/retrieval/foundation-r3a-scifact-dev.json
HOME=$HOME_ISOLATED timeout -s KILL 900s .venv/bin/python scripts/score_vi_stem_gold.py --split dev \
  --checkpoint $R3A --tokenizer-model $TOK --output reports/retrieval/foundation-r3a-vi-stem-dev.json
```

### 8.5 Decision after R3a (decision aids proposed by the agent, not gates)

| Observation on `val` / dev, against R2 | Reading | Next |
|---|---|---|
| PAWS accuracy from 0.50 to >= 0.60, or STS-B Spearman from 0.32 to >= 0.45 | the exposure explanation is supported | R3b: same command with `--init-from artifacts/checkpoints/language_encoder/foundation-r3a/best`, `--steps 20000`, `--eval-interval 1000 --save-interval 1000`, timeout 18,000 s, run-id `foundation-r3b`, intake `--init-run foundation-r3a --expect-steps 20000` |
| Neither moves, no forgetting | exposure is not the cause | stop; check the paraphrase head output on PAWS validation pairs (inference) and the data before any more GPU time |
| Any task loss more than 10 % above R2, or SciFact dense MRR below 0.10 | the mixture or the doubled contrastive share hurts | stop; return the logs to the agent |

R3 does not approve T100. The sealed test splits stay unused until the owner has reviewed the R3 analysis and the
threshold review (`reports/verification/T99-threshold-review.md`).


## 9. English stage 1 (D46 / ADR-022, T175-T177)

Status: the English data is acquired (T175) and the document and configuration sweep is done (T176). Partitioning, the data
wiring and the exact owner commands are task T177; **no command below fits a tokenizer or trains**, and none authorises an agent
to. The foundation model is NOT QUALIFIED.

### 9.1 Data acquired by the agent (T175, no training)

Sources, file selection and licences are in `configs/data/english_sources.yaml`; the result is in
`data/acquisition_manifest.json` and `data/raw/<source>_en/` (outside Git). To repeat or resume (it resumes partial files):

```bash
HOME=$HOME_ISOLATED .venv/bin/python -c "import sys; from laris.research.corpus.acquisition.runner import main; sys.exit(main(['--english-all']))"
.venv/bin/python scripts/check_sts_leakage.py     # writes data/processed/sts_extra_en/train.parquet and reports/verification/T175-sts-leakage.json
```

Sources with `license_approved: false` (non-commercial or undeclared licence) are in the manifest as `NEEDS_LICENSE_REVIEW`. The owner
records the decision per source before any of them is used in a run that is reported; until then they are research-only.

### 9.2 What the owner does next (after T177 prepares the commands)

1. Review the licence column of `DATASET_SPECIFICATION.md` section 2.1 and approve or drop sources.
2. Run the tokenizer fit on the English train text (command prepared in T177; no tokenizer is fitted by the agent).
3. Run the encoder from scratch (R1 weights depend on the old 48k vocabulary and cannot initialise an English tokenizer).
4. Return logs; the agent checks intake and reports per English gate; T100 (held-out) follows only after the owner reviews the analysis.

## 9. English stage 1 after D46 (T175 to T177)

State: the English data is on disk, partitioned (train/val/test, hash by document or pair, passages of at most 4,000 characters), deduplicated, and
checked against STS-B and SQuAD v1 held-out sets. Nothing below has been run by the agent: the foundation model is **NOT QUALIFIED**, and the
tokenizer fit and every training step are owner runs. R1-R3a weights cannot initialise this model.

### 9.1 What the agent prepared

| Item | Where |
|---|---|
| Sources, licences, owner approvals (2026-11-14) | `configs/data/english_sources.yaml`, `data/acquisition_manifest.json` |
| Partition and leakage rules | `configs/data/english_partition.yaml`, `scripts/partition_english.py`, `data/processed/task_splits_manifest.json` |
| STS-B leakage check (2,092 pairs removed) | `scripts/check_sts_leakage.py`, `reports/verification/T175-sts-leakage.json` |
| Tokenizer fit corpus (train splits only, word budgets per source) | `scripts/prepare_english_tokenizer_corpus.py` -> `data/cache/english_fit_corpus_t183.txt` and `.json` |
| Model and mixture | `configs/language_encoder/english_r1.yaml` (large size, about 544 M parameters, vocabulary 56,000 since T182; **proposal**) |
| Why this size | `reports/verification/T175-model-size-vs-data.md` |

Retrieval pairs (T178): GooAQ, Natural Questions, MS MARCO, ELI5, Yahoo, Stack Exchange duplicates, SPECTER, AltLex, Simple-Wiki and COCO captions
are partitioned (6.50 M pairs, 6.37 M train) and feed a dense-retrieval task with in-batch negatives (`retrieval_task: true`,
`loss_lambda_retrieval: 0.20`, batch 32, passages cut at 256 tokens in `english_r1.yaml`; all **proposals**). Pairs touching SQuAD v1
held-out text, STS-B held-out sentences or SciFact claims, titles and abstracts were removed (6,472) and the rescan is clean
(`scripts/check_retrieval_leakage.py`, `reports/verification/T178-retrieval-leakage.json`). With real row counts the task sampler draws
MLM 53.7 %, retrieval 28.8 %, NLI 9.5 %, paraphrase 4.0 %, QA 3.5 %, similarity 0.5 % of the steps, and a retrieval step encodes
32 queries and 32 passages, so it costs more than an 8-sequence MLM step. If the profile or the pilot shows the retrieval share is too
large, lower `loss_lambda_retrieval` or the batch size, or ask the agent for a row cap; do not change the files while a run is in progress.
This does not make G12 pass: the encoder is NOT QUALIFIED until T100 measures it on held-out data.

### 9.2 Owner steps

Set `HOME_ISOLATED` as in section 2 and stop other GPU workloads first.

**Step 1: fit the English tokenizer** (CPU, about 5.4 GB of text, 888 M words, STEM 9.0%; about 3 hours; SentencePiece BPE, 56,000 pieces, digits NOT split since T184).

The first fit (32,000 pieces, `artifacts/tokenizer/english-r1/`) failed the intake: fertility 1.41 on general English validation text against the 1.35 limit (`reports/verification/english-r1-32k-tokenizer-intake.json`). The failed tokenizers and their fit logs were deleted on 2026-11-14 (T184); the intake reports stay. The vocabulary is raised to 56,000 (T182): the model grows by about 31 M parameters (tied embedding), the memory by about 0.5 GB. The 56,000 fit on the T181 corpus (`artifacts/tokenizer/english-r1-56k/`) measured 1.352 to 1.359 on general English validation text, 0.002 to 0.009 over the 1.35 limit (`reports/verification/english-r1-56k-tokenizer-intake.json`). The corpus was then rebuilt (T183) so that STEM stays 80 M words but is 9.0% of the fit (general text 808 M words); that second 56,000 fit (`artifacts/tokenizer/english-r1-56k-v2/`) measured 1.358, so the STEM share is not a lever (`reports/verification/english-r1-56k-v2-tokenizer-intake.json`). Digit splitting (one token per digit) is not needed for this encoder, so the fit below (T184) lets BPE merge digits into ordinary pieces (`--no-split-digits`); numbers use about 13% of the tokens of Wikipedia text, 5% of web text and 12 to 18% of STEM text today. The expected gain is an estimate (1 to 3% of the tokens of general text), not a measurement, and the intake decides.

```bash
HOME=$HOME_ISOLATED timeout -s KILL 14400s .venv/bin/python -m cli.main train tokenizer \
  --authorized --fit-corpus data/cache/english_fit_corpus_t183.txt --vocab-size 56000 --no-split-digits \
  --output-dir artifacts/tokenizer/english-r1-56k-nd --model-prefix laris_spm_en_56k_nd \
  2>&1 | tee artifacts/logs/english-r1-56k-nd-tokenizer-fit.log
```

Return the log, `artifacts/tokenizer/english-r1-56k-nd/` and `data/cache/english_fit_corpus_t183.json`. Watch memory during the fit (SentencePiece loads the whole corpus; the trainer sets no `input_sentence_size`): note the peak RSS, for example with `/usr/bin/time -v` or `htop`; if the fit is killed for memory, tell the agent and a sampled fit with the same proportions is prepared. The agent runs the intake (fertility on the
validation split, unknown-token rate, special-token ids; `scripts/english_tokenizer_intake.py --model artifacts/tokenizer/english-r1-56k-nd/laris_spm_en_56k_nd.model --out reports/verification/english-r1-56k-nd-tokenizer-intake.json`) before step 2. Do not continue if fertility on English validation text is above 1.35.

**Step 2: memory and speed profile** (decides batch size; the numbers replace every estimate in the size report).

```bash
TOK=artifacts/tokenizer/english-r1-56k-nd/laris_spm_en_56k_nd.model
mkdir -p artifacts/profiles
LARIS_TRAINING_AUTHORIZED=1 timeout -s KILL 600s .venv/bin/python -m cli.model train language-encoder \
  --profile-only --model-size large --vocab-size 56000 --max-seq-len 1024 \
  --training-config configs/language_encoder/english_r1.yaml \
  --micro-batch-size 8 --grad-accum-steps 4 --gradient-checkpointing --precision bf16 --no-8bit-adam \
  --tokenizer-model $TOK --normalize-input 2>&1 | tee artifacts/profiles/english-r1-profile.log
```

If peak memory exceeds the VRAM you can give the run, lower `--micro-batch-size` (4 or 2) and raise `--grad-accum-steps` to keep 32 per update;
if even 2 does not fit, tell the agent: the size is then reduced to the compact size (about 110 M) or an 8-bit optimiser state is considered.
Return the log; the tokens per second in it replace the 35 TFLOP/s assumption.
The profile also measures the retrieval task (peak memory is the maximum over all six tasks). If it is the task that does not fit, lower `retrieval_batch_size` in `english_r1.yaml` first (16 or 8) before touching `--micro-batch-size`.

**Step 3: smoke run, 20 steps.**

```bash
LARIS_TRAINING_AUTHORIZED=1 timeout -s KILL 300s .venv/bin/python -m cli.model train language-encoder \
  --authorized --model-size large --vocab-size 56000 --max-seq-len 1024 \
  --training-config configs/language_encoder/english_r1.yaml \
  --micro-batch-size 8 --grad-accum-steps 4 --gradient-checkpointing --precision bf16 --no-8bit-adam \
  --steps 20 --eval-interval 10 --eval-batches 2 --save-interval 20 --seed 42 \
  --tokenizer-model $TOK --normalize-input --run-id english-r1-smoke --no-evaluate-after \
  2>&1 | tee artifacts/profiles/english-r1-smoke.log
```

**Step 4: pilot, 5,000 steps** (about 160 M tokens; a short run to see the loss curve per task and the time per step before committing days).

```bash
LARIS_TRAINING_AUTHORIZED=1 timeout -s KILL 28800s .venv/bin/python -m cli.model train language-encoder \
  --authorized --model-size large --vocab-size 56000 --max-seq-len 1024 \
  --training-config configs/language_encoder/english_r1.yaml \
  --micro-batch-size 8 --grad-accum-steps 4 --gradient-checkpointing --precision bf16 --no-8bit-adam \
  --steps 5000 --learning-rate 0.0002 --warmup-steps 500 \
  --eval-interval 500 --eval-batches 16 --save-interval 500 --patience 4 --seed 42 \
  --tokenizer-model $TOK --normalize-input --run-id english-r1-pilot --no-evaluate-after \
  2>&1 | tee artifacts/profiles/english-r1-pilot.log
```

Stop rules: stop and return the log if any task loss is NaN or rises more than 10 % above its best value for two evaluations, or if a step takes
more than twice the smoke-run time. The agent writes the intake check and the per-task analysis from the returned log; the main run
(`max_steps` in the config, in segments with `--save-interval`) is approved after that review, not before.

**Step 5 (after the pilot review): main run and T100.** Command, step count and time budget are fixed from the measured pilot throughput. T100
(held-out evaluation, once per candidate) follows the main run.

## 10. T202: memory and speed profile of the pair-remediation tasks and mixed batches (owner run, done 2026-11-17)

Prepared by T201. The profile needs an optimizer step, so only the owner runs it. Nothing in this section authorises an agent to train.

**What it measures.** Every task alone (MLM with the sentence-order labels and two-segment rows, NLI and paraphrase label-balanced, similarity
with the bi-encoder head, QA, retrieval, contrastive similarity), then, when `--tasks-per-step` is 2 or 3, every combination of that many
different tasks as one mixed step (the losses are added and one backward pass covers them, as in training). Each measurement has its own
peak counter, so the worst group is a measurement, not an estimate. The config is `configs/language_encoder/english_r1_t202_profile.yaml`
(english_r1 with the new tasks on; profile only, not a training mixture: T203 proposes that).

**Result (2026-11-17, `reports/verification/T202-mixed-batch-profile.md`).** 1 task: 11.39 GB, `[SUCCESS]`. 2 tasks: 13.12 GB worst (similarity+retrieval),
`[SUCCESS]`. 3 tasks: CUDA out of memory at 14.16 GB allocated after 9 groups (largest 13.81 GB). Chosen `--tasks-per-step 2`. The T201 estimate (about 14.2 GB
for 2, 16.4 GB for 3) was high for 2 and right for 3. A 2-task micro-step takes 1.68 s against 0.88 s for one task.

```bash
TOK=artifacts/tokenizer/english-r1-56k-nd/laris_spm_en_56k_nd.model
mkdir -p artifacts/profiles
for N in 1 2 3; do
  LARIS_TRAINING_AUTHORIZED=1 timeout -s KILL 900s .venv/bin/python -m cli.model train language-encoder \
    --profile-only --model-size large --vocab-size 56000 --max-seq-len 1024 \
    --training-config configs/language_encoder/english_r1_t202_profile.yaml --tasks-per-step $N \
    --micro-batch-size 8 --grad-accum-steps 4 --gradient-checkpointing --precision bf16 --no-8bit-adam \
    --tokenizer-model $TOK --normalize-input 2>&1 | tee artifacts/profiles/english-r1-t202-profile-n$N.log
done
```

T207 (2026-11-17) added `dataset_sampling_weights` to the profile config (VitaminC in the NLI pool, `squad_v2_en` x1.695, `paws_unlabeled_en` x0.17). The
profile does not pass `--dataset-sampling-ablation`, so it draws datasets by row count; its memory peaks do not depend on the weights. A stage-2 run (T204) passes
the flag so the exponents and weights apply.

A run that ends in `CUDA out of memory` is a result, not a failure of the procedure: keep its log. The single-task part of the log comes first,
then one line per mixed step, `Worst mixed step`, `Measured peak` and the latency per micro-batch and per mixed step.

**Decision rule.** The largest `--tasks-per-step` whose log ends in `[SUCCESS]` (every task and every group finite, measured peak at most 14.5 GB)
and whose peak leaves at least 0.3 GB below the limit (the data of a long run is longer than one profile sample). If 2 fails on the worst pair
only, lower `retrieval_batch_size` (16) or `--micro-batch-size` (4, with `--grad-accum-steps 8`) before giving up on 2. A larger step also adds the loss
of each of its tasks, so the gradient of a micro-step is about `tasks_per_step` times larger before clipping (`max_grad_norm` bounds it); the
learning rate is not changed by this runbook.

**Intake.** Done: the three logs were returned and the report written. T203 uses `tasks_per_step: 2` in the stage-2 proposal.

## 11. T209: memory profile with a shared GPU (owner run, prepared 2026-11-18)

Prepared because the owner keeps CARLA (headless, about 2.3 GB, measured 2,285 MiB) running during training. `nvidia-smi` then shows about 12.6 GiB free of
16,303 MiB (2,886 MiB used before any training). The T202 peaks do not fit: 2 tasks per step peaked at 13.12 GB, 1 task at 11.39 GB (both maximum allocated,
without the CUDA context of about 0.3-0.5 GB). Nothing in this section authorises an agent to train; the profile needs an optimizer step, so only the owner runs it.

**What changes.** `configs/language_encoder/english_r1_t209_shared_gpu_profile.yaml` is the T202 profile config with `retrieval_batch_size` 16 (was 32),
`contrastive_sim_batch_size` 32 (was 64) and `max_vram_gb` 11.5. The command lowers the micro-batch to 4 and raises the accumulation to 8 (effective batch 32 as
before). The resident state (about 8.1 GiB of weights, gradients and fp32 AdamW) does not shrink, so the room for activations is about 3.4 GB at best; whether 2
tasks fit is the question this profile answers. Halving the retrieval and contrastive batches halves their in-batch negatives: a stage-1 rerun, the stage-2 run and
its control must all use the same sizes, or the comparison is not like for like.

```bash
TOK=artifacts/tokenizer/english-r1-56k-nd/laris_spm_en_56k_nd.model
mkdir -p artifacts/profiles
nvidia-smi --query-gpu=memory.used,memory.free --format=csv | tee artifacts/profiles/english-r1-t209-gpu-before.txt   # with CARLA running
for N in 1 2; do
  LARIS_TRAINING_AUTHORIZED=1 timeout -s KILL 900s .venv/bin/python -m cli.model train language-encoder \
    --profile-only --model-size large --vocab-size 56000 --max-seq-len 1024 \
    --training-config configs/language_encoder/english_r1_t209_shared_gpu_profile.yaml --tasks-per-step $N \
    --micro-batch-size 4 --grad-accum-steps 8 --gradient-checkpointing --precision bf16 --no-8bit-adam \
    --tokenizer-model $TOK --normalize-input 2>&1 | tee artifacts/profiles/english-r1-t209-profile-n$N.log
done
nvidia-smi --query-gpu=memory.used,memory.free --format=csv | tee artifacts/profiles/english-r1-t209-gpu-after.txt
```

**Decision rule.** Keep CARLA in its usual scene while profiling (its memory grows with sensors and map). The largest `--tasks-per-step` whose log ends in
`[SUCCESS]` with a measured peak at most 11.5 GB wins; the margin to the free memory must stay at least 1 GiB, because CARLA can grow. If 2 fails, the
stage-2 and control runs use `--tasks-per-step 1` (T203 then needs its floors recomputed: draw share equals the scheduler probability) or wait until the
GPU is free. A log that ends in `CUDA out of memory` is a result: keep it. If both fail, do not train with CARLA running.

**Not covered.** The profile samples a few batches per task. CARLA's memory is not constant: a heavier scene can take the margin and kill a run of hours.
Speed is not comparable with T202 (the GPU is shared with CARLA's rendering and the micro-batch is half).

## 12. T210: running the owner runs on a Colab A100 (prepared 2026-11-18)

Prepared because the local GPU is shared with CARLA (section 11) and the owner has a Colab A100 (40 GB, 83 GB RAM, 12 CPUs, 236 GB disk, driver 580 with
CUDA 13.0, PyTorch 2.14.1+cu130 preinstalled; checked on 2026-11-18 with a 10 s session) and 191 compute units. Nothing in this section authorises an
agent to train: the agent may prepare the VM and read logs over SSH, the owner starts every training command.

**Why no config change.** 40 GB holds the stage-2 mixture (peak 13.12 GB at `tasks_per_step 2`, T202) and the 14.5 GB envelope of ADR-005 stays in the
configs, so the Colab run uses the same files as a local one and its results stay comparable. Do not use the spare memory to change batch sizes or
`tasks_per_step`: that changes the experiment. Speed and memory figures of T202 do not transfer to the A100; measure the first steps.

**Cost guard.** Units are used while the runtime exists, not only while a command runs. Create a session only when the data is ready, check the rate in
the Colab UI first, and end every session with `colab stop -s NAME` (or use `--rm` for a short check). `colab sessions` must list none when you stop working.
Whether a running process keeps an SSH-less runtime alive is not verified: run long jobs with `nohup` and watch the log; keep a login that can reach the session.

**Prerequisite the agent cannot settle.** Google Drive space for the data (28.1 GB) and at least one checkpoint (6.1 GB `best`, plus `last`): check the quota
before uploading. A free Drive account (15 GB) is not enough.

Steps (owner's machine unless it says VM):
1. `colab` CLI v0.8.0 is installed (`uv tool install "google-colab-cli>=0.7.2"`, the PyPI 0.6.0 has no `ssh`). Log in once with `colab sessions` in a terminal.
2. Stage the data: `.venv/bin/python -I scripts/colab/data_manifest.py --stage ~/laris-colab-data` hard-links the 74 train and val parquet files of the directories
   the loader reads (28.10 GB; **test splits and unread directories such as `uspto_patents` are left out**) and writes `files.sha256`. Upload that folder's contents to
   `MyDrive/laris/data/processed` (Drive for desktop or the web upload). The data carries SICK (CC-BY-NC-SA) and VitaminC (BIG-bench canary): uploading to the owner's own Drive is
   the owner's decision, recorded 2026-11-18.
3. Pack the code: `scripts/colab/pack_code.sh` (needs a clean tracked tree; writes `artifacts/colab/laris-code.tar.gz` of `git archive HEAD` and the 3 MB tokenizer archive;
   the commit is in `artifacts/colab/COMMIT` and goes into the run manifest).
4. Create the session and upload (the GPU is attached from `colab new`, so do this when the data is already on Drive):
   `colab new -s laris --gpu A100`, then `colab upload artifacts/colab/laris-code.tar.gz /content/laris-code.tar.gz`, the same for `laris-tokenizer.tar.gz`, and
   `scripts/colab/setup_vm.sh` to `/content/setup_vm.sh`; if a checkpoint is needed (stage 2 starts from one), upload the `best` folder to
   `/content/laris/artifacts/checkpoints/language_encoder/<run>/best` (6.1 GB; or place it on Drive and copy).
5. On the VM (`colab ssh -s laris`): `bash /content/setup_vm.sh` (installs the project with its `training` extra from `pyproject.toml`, no new package; prints Python, torch, CUDA and bf16),
   `colab drivemount /content/drive` (from the owner's machine), then `bash /content/laris/scripts/colab/sync_data.sh` (copies Drive to `/content/laris/data/processed` and verifies `files.sha256`).
6. Run the owner command of the task (T204 stage 2 and control, or the stage-1 rerun) from `/content/laris` with `--no-evaluate-after` (the test split is not on the VM; the sealed
   test split is never touched), `nohup ... > artifacts/profiles/<run>.log 2>&1 &`, and `--save-interval` as the task says. The loader and trainer are unchanged.
7. Bring back what matters **before** `colab stop`: the `best` and `last` folders and the log (`colab download`, or copy to `/content/drive/MyDrive/laris/runs/`). The VM disk is gone after the session ends.
   Resume after a break uses `--resume` on the checkpoint, as in section 9.

**Differences from the local environment (record them in the report).** Python 3.13 on the VM against 3.10 in `.venv`; the same PyTorch 2.14.1+cu130 as local. The run manifest records the
versions, the commit and the GPU; a result is "measured on the Colab A100 with ...". Dependency pins are not locked in Git (`uv.lock` is untracked), so the VM resolves current compatible versions.

## 13. T211: speed profile and ceiling on the Colab A100 (owner run, prepared 2026-11-18)

Owner order 2026-11-18: use the A100 to train as fast as possible. **ADR-023** lets the owner raise the VRAM ceiling above 14.5 GB on a GPU of 24 GB or more with
`LARIS_VRAM_CEILING_GB`; on the RTX 5070 Ti the value is refused. Use `export LARIS_VRAM_CEILING_GB=36` on the Colab VM (95 % of the 39.5 GiB PyTorch sees is 37.5). The ceiling is
printed at the start, used by the profile, and written to the checkpoint provenance with the GPU name.

**Levers, in the order of how little they change the experiment.**
1. Gradient checkpointing off (`--gradient-checkpointing` omitted): the same mathematics, about 25-35 % less recompute (expectation, not measured here).
2. A larger micro-batch with fewer accumulation steps (16 x 2 or 32 x 1; effective batch 32 as before). Each micro-step then has fewer draws per optimizer step (accumulation x
   `tasks_per_step`), so the draws and passes of reports/verification/T203-stage2-mixture.md change: recompute them with
   `scripts/plan_stage2_schedule.py --micro-batch-size M --grad-accum-steps A` before a run, and use the same values in the stage-2 run and its control.
   Retrieval (32) and contrastive similarity (64) keep their own batch sizes, so their rows per optimizer step fall with the accumulation.
3. `--tasks-per-step 3` fits in 40 GB but changes the experiment decided in T202; not used unless the owner says so.

**Procedure (VM, after section 12 step 5; the owner starts it).**
```bash
cd /content/laris
export LARIS_TRAINING_AUTHORIZED=1 LARIS_VRAM_CEILING_GB=36
bash scripts/colab/speed_profile.sh configs/language_encoder/english_r1_stage2.yaml 2      # six profiles of a few minutes
bash scripts/colab/speed_profile.sh configs/language_encoder/english_r1.yaml 1             # for the stage-1 rerun, optional
```
**Decision rule.** Among the combinations whose log shows every task and every group finite and a peak at least 2 GB below the ceiling, choose the one with the lowest
`Latency per mixed step` x accumulation (seconds per effective batch of 32). Report the table and the choice; then recompute the T203 schedule for that micro-batch and accumulation and
use it in the stage-1 rerun, the stage-2 run and the control alike. A profile ending in `CUDA out of memory` is a result: keep its log. Stop the session (`colab stop`) as soon as the
logs are copied back.

**Cost.** Six profiles are a few minutes each on a model that does not train; with the rate in the Colab UI the owner can bound the units before starting. Not measured: any
A100 figure (speed, peak). The T202 figures belong to the RTX 5070 Ti.

## 14. T211 option (b): profile of micro-batch 32 with retrieval batch 128 and contrastive batch 256 (owner run, prepared 2026-11-18)

Owner decision 2026-11-18 after the A100 profile (`reports/verification/T211-a100-speed-profile.md`): train at **micro-batch 32, accumulation 1** (3.00 s per optimizer step, peak 23.93 GB at the
old retrieval and contrastive batches) and raise `retrieval_batch_size` to 128 and `contrastive_sim_batch_size` to 256, so retrieval and contrastive similarity see the same rows per step as at 8 x 4
(computed: 0.024 and 0.306 passes at 5,000 steps). The cost is 4x more in-batch negatives for those two tasks, which changes their objective, and every update averages two task batches. Both
`english_r1_stage2.yaml` and `english_r1_stage2_control.yaml` now carry these values (the control's retrieval batch too, so the comparison stays like for like).

**Not measured:** the peak with retrieval 128 (256-token passages) and contrastive 256 (128-token sentences) next to a 32-row task; the speed of those steps; the saving of turning
checkpointing off. Estimate only: the peak may approach the 36 GB ceiling; this profile decides.

```bash
cd /content/laris
export LARIS_TRAINING_AUTHORIZED=1 LARIS_VRAM_CEILING_GB=36
TOK=artifacts/tokenizer/english-r1-56k-nd/laris_spm_en_56k_nd.model
for CFG in english_r1_stage2 english_r1_stage2_control; do
  for CK in "" "--no-gradient-checkpointing"; do
    tag=$([ -z "$CK" ] && echo ckpton || echo ckptoff)
    timeout -s KILL 1500s python3 -m cli.model train language-encoder --profile-only \
      --model-size large --vocab-size 56000 --max-seq-len 1024 \
      --training-config configs/language_encoder/$CFG.yaml --tasks-per-step 2 \
      --micro-batch-size 32 --grad-accum-steps 1 $CK \
      --precision bf16 --no-8bit-adam --tokenizer-model $TOK --normalize-input \
      2>&1 | tee artifacts/profiles/optb-$CFG-$tag.log | grep -E "Worst mixed|Latency per mixed|Measured peak|SUCCESS|FAIL|out of memory"
  done
done
```
Four runs of a few minutes each. **Decision rule.** Per config, take the checkpointing setting with the lower latency whose peak is at least 2 GB below 36 GB (34 GB). If checkpointing "on" at stage 2
exceeds 34 GB, lower `retrieval_batch_size` to 96 (then 64) and `contrastive_sim_batch_size` to 192 (then 128) in both configs and profile again; the report records every value tried. Whatever is chosen is used by the
stage-1 rerun, the stage-2 run and the control alike, and `scripts/plan_stage2_schedule.py` (it now reads the micro-batch, accumulation and batch sizes from the YAML) recomputes the draws and passes.

**Result (2026-11-18).** Stage 2 with checkpointing: 26.82 GB, 3.78 s per optimizer step; control with checkpointing: 23.82 GB, 3.45 s; both "off" runs: CUDA out of memory. Checkpointing stays on and the batches stay at
128 and 256 (`reports/verification/T211-a100-speed-profile.md`). Use `--micro-batch-size 32 --grad-accum-steps 1` for the stage-2 run and the control, without `--no-gradient-checkpointing`.
