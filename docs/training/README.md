---
document_id: "DOC-INDEX-TRAINING-001"
title: "Ordered Training and Owner Handoff"
document_type: "plan"
status: "DRAFT"
version: "1.1.0"
created_at: "2026-11-10"
updated_at: "2026-11-10"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: false
related_documents:
  - "docs/specifications/LANGUAGE_ENCODER_TRAINING_SPECIFICATION.md"
  - "docs/research/EMPIRICAL_STATUS.md"
decision_references:
  - "ADR-008"
  - "ADR-013"
change_summary: "Indexes the current foundation-first preparation and owner-only training boundary."
---

# Ordered training

The current work prepares model 01, the general English/Vietnamese foundation.
It does not implement or train model 02, the scientific-language specialization.
The foundation checkpoint has not met its formal exit gates. Passing the current
baseline-relative evaluation config does not change that state.

Follow the [canonical specification](../specifications/LANGUAGE_ENCODER_TRAINING_SPECIFICATION.md)
for architecture and stage gates. See the [empirical report](../research/EMPIRICAL_STATUS.md)
for the actual measurements and protocol gaps, rather than interpreting the old
scientific-paper pilot as a stage-completion result.

Execution order:

1. Finish repository organization and three-file cross-checking.
2. Audit foundation evaluation against formal gates using existing reports.
3. Resolve measurement gaps and prepare the owner's commands.
4. The owner alone runs training and returns results for review.
5. Qualify model 01 on appropriately held-out evidence.
6. Only then implement/execute scientific-language learning, followed by OCR,
   manuscript learning, integration and later specialists.

The system specification, remaining project plan and implementation tasks live in `.agents/spec.md`, `.agents/plan.md` and
`.agents/task.md`. Completed preparation tasks do not mean completed model training.
Agents must not run fitting, backward passes, optimizer steps, authorized memory
profiling or tests that perform these operations.

Source packages remain functional under `src/`, as required by ADR-013.
Experiments live under `experiments/`, measured reports under `reports/`, and
weights/data remain local under ignored `artifacts/` and `data/` paths.

The [owner runbook](OWNER_RUNBOOK.md) contains the commands and remaining measurement blockers. `laris evaluate readiness --reports ...` is an offline audit; it does not run a model or authorize promotion through missing metrics.
