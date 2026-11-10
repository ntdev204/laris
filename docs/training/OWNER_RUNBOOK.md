---
document_id: "DOC-RUNBOOK-OWNER-001"
title: "Owner-Executed Foundation Training and Evaluation"
document_type: "specification"
status: "DRAFT"
version: "1.0.0"
created_at: "2026-11-10"
updated_at: "2026-11-10"
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
change_summary: "Provides parsed owner-only commands; agents execute no training or optimizer profiling."
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

Current blockers: low ANLI/ViNLI/PAWS/STS scores, missing PAWS macro F1 in the old
report, no normalized answer-text QA evaluation, no qualifying unseen-text fertility
or held-out retrieval reports, and validation-only evidence. New evaluation reports
now include PAWS macro F1 and identify QA as token-span scoring, but that alone
does not implement normalized answer-text QA or close the other blockers.

Resolve evaluation/data/curriculum decisions before spending GPU time on a new
candidate. The commands below start a fresh **baseline candidate**; they are not
a claim that repeating the same objective will meet the gates. There is no runnable
scientific-language training pipeline yet, so no model 02 training command is given.

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
  --micro-batch-size 4 --grad-accum-steps 16 --precision bf16 \
  --tokenizer-model artifacts/tokenizer/laris_spm_32k.model
```

## 4. Owner-only fresh candidate

Choose an unused run ID before executing. This is a fresh initialization, not
a resume from `compact-1024-04`; it does not overwrite the historical checkpoint.
The example budget is the shipped 100,000-step schedule, not a measured requirement
or a guarantee of quality. Micro-batch 4 with accumulation 16 gives effective batch
64. The owner must measure this configuration before starting the full run.

```bash
LARIS_TRAINING_AUTHORIZED=1 .venv/bin/laris train language-encoder \
  --authorized --model-size compact --max-seq-len 1024 \
  --training-config configs/language_encoder/compact.yaml \
  --micro-batch-size 4 --grad-accum-steps 16 --precision bf16 \
  --steps 100000 --eval-interval 200 --eval-batches 16 \
  --save-interval 500 --patience 15 --seed 42 \
  --tokenizer-model artifacts/tokenizer/laris_spm_32k.model \
  --run-id foundation-candidate-001 --no-evaluate-after
```

The explicit `--no-evaluate-after` prevents the current default automatic test-set
evaluation. Compare candidates on validation. Resume only after verifying the
recorded architecture, tokenizer, optimizer, schedule, accumulation and run settings;
an already early-stopped run should not be resumed as an assumed quality fix.

## 5. Owner validation, then formal review

```bash
.venv/bin/laris evaluate language-encoder \
  --checkpoint artifacts/checkpoints/language_encoder/foundation-candidate-001/best \
  --tokenizer-model artifacts/tokenizer/laris_spm_32k.model \
  --split val --max-samples 2000 --batch-size 8 --seed 42 --device cuda \
  --output artifacts/evaluations/language_encoder/foundation-candidate-001-val.json

.venv/bin/laris evaluate readiness \
  --reports artifacts/evaluations/language_encoder/foundation-candidate-001-val.json \
  --output artifacts/readiness/foundation-candidate-001-val.json
```

Readiness remains NOT QUALIFIED with validation-only evidence, even if all measured
scores increase. Return the checkpoint manifest, validation JSON and training log
for error review. Do not tune thresholds or choose models using the test set.

The existing CLI cannot yet produce every formal measurement. Before final
qualification, implement normalized answer-text QA and provide independently
measured fertility/retrieval reports. Do not relabel token-span metrics as answer
metrics or substitute the historical 6-query pilot for held-out retrieval.

Only after measurement protocols and candidate choices are fixed should the owner
perform final held-out evaluation. Additional measurement files use the same
report envelope: `split`, `model_sha256`, `tokenizer_sha256`,
`dataset_manifest_sha256`, `split_isolation_checked`, and `datasets` records with
`dataset`, `language`, positive `samples`, `metrics`, optional `baseline`, and
`metric_protocols`. Every required metric/protocol is defined in
`configs/evaluation/foundation.yaml`; all files must refer to the same model and
tokenizer. Missing, conflicting or non-finite evidence blocks qualification.

## 6. Stage boundary

Passing foundation report checks is a review prerequisite, not an automatic command
to train model 02. The owner reviews the complete held-out evidence first. Scientific
language is implemented and evaluated next; OCR, manuscripts, integration and later
specialists must not be advanced through the historical paper pilot.
