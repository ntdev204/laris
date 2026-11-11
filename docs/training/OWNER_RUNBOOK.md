---
document_id: "DOC-RUNBOOK-OWNER-001"
title: "Owner-Executed Foundation Training and Evaluation"
document_type: "specification"
status: "DRAFT"
version: "1.1.0"
created_at: "2026-11-10"
updated_at: "2026-11-11"
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
change_summary: "Records the F04A budget and owner commands for the F05 sampling comparison."
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
.venv/bin/python scripts/validate_work_plan.py
.venv/bin/laris data check --verify-sha256
.venv/bin/laris evaluate readiness \
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
LARIS_TRAINING_AUTHORIZED=1 .venv/bin/laris train language-encoder \
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
LARIS_TRAINING_AUTHORIZED=1 timeout -s KILL 120s .venv/bin/laris train language-encoder \
  --authorized --model-size compact --max-seq-len 1024 \
  --training-config configs/language_encoder/compact.yaml \
  --init-from artifacts/checkpoints/language_encoder/compact-1024-04/best \
  --micro-batch-size 4 --grad-accum-steps 16 --precision bf16 --no-8bit-adam \
  --steps 10 --learning-rate 0.00002 --warmup-steps 0 \
  --eval-interval 500 --eval-batches 16 --save-interval 500 --patience 3 --seed 42 \
  --tokenizer-model artifacts/tokenizer/laris_spm_32k.model \
  --retrieval-loss-weight 0 --run-id foundation-f05-baseline-smoke --no-evaluate-after \
  2>&1 | tee artifacts/profiles/foundation-f05-baseline-smoke.log

LARIS_TRAINING_AUTHORIZED=1 timeout -s KILL 120s .venv/bin/laris train language-encoder \
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
LARIS_TRAINING_AUTHORIZED=1 timeout -s KILL 3180s .venv/bin/laris train language-encoder \
  --authorized --model-size compact --max-seq-len 1024 \
  --training-config configs/language_encoder/compact.yaml \
  --init-from artifacts/checkpoints/language_encoder/compact-1024-04/best \
  --micro-batch-size 4 --grad-accum-steps 16 --precision bf16 --no-8bit-adam \
  --steps 1990 --learning-rate 0.00002 --warmup-steps 50 \
  --eval-interval 500 --eval-batches 16 --save-interval 500 --patience 3 --seed 42 \
  --tokenizer-model artifacts/tokenizer/laris_spm_32k.model \
  --retrieval-loss-weight 0 --run-id foundation-f05-baseline-run --no-evaluate-after \
  2>&1 | tee artifacts/profiles/foundation-f05-baseline-run.log

LARIS_TRAINING_AUTHORIZED=1 timeout -s KILL 3180s .venv/bin/laris train language-encoder \
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
timeout -s KILL 300s .venv/bin/laris evaluate language-encoder \
  --checkpoint artifacts/checkpoints/language_encoder/foundation-f05-baseline-run/best \
  --tokenizer-model artifacts/tokenizer/laris_spm_32k.model \
  --split val --max-samples 512 --batch-size 8 --seed 42 --device cuda \
  --output artifacts/evaluations/language_encoder/foundation-f05-baseline-val.json

timeout -s KILL 300s .venv/bin/laris evaluate language-encoder \
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
.venv/bin/python -m laris.language.benchmarks.fertility \
  --tokenizer-model <TOKENIZER> --normalize-input \
  --fit-corpus artifacts/tokenizer/foundation-r1-super/fit-actual.txt \
  --output reports/tokenizer/foundation-f07.json
.venv/bin/python -m laris.language.benchmarks.retrieval run \
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
