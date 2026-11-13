---
document_id: "DOC-RUNBOOK-OWNER-001"
title: "Owner-Executed Foundation Training and Evaluation"
document_type: "specification"
status: "DRAFT"
version: "1.2.0"
created_at: "2026-11-10"
updated_at: "2026-11-13"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: false
related_documents:
  - "docs/training/README.md"
  - "docs/specifications/LANGUAGE_ENCODER_TRAINING_SPECIFICATION.md"
  - "docs/development/CLI.md"
decision_references:
  - "ADR-008"
  - "ADR-013"
change_summary: "Adds section 7: the T99 round plan for the R1 (48k tokenizer) encoder."
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

## 7. T99: foundation rounds for the R1 encoder (48k tokenizer)

Status: **PROPOSED budget; the owner approves it by running it.** **VRAM budget for this round: 8 GB** (CARLA holds the rest of the GPU), not the 14.5 GiB of section 3. Sections 3 to 5b describe the historical 32k
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
