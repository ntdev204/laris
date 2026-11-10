# Working rules

Read `.agents/spec`, `.agents/plan` and `.agents/task` before changing this repository.
They are the current owner's cross-checked requirements, execution order and task ledger.

- Do not execute neural training, tokenizer fitting, backward/optimizer steps, or
  optimizer-bearing profiling. Do not run tests that perform these operations.
  Prepare commands for the owner instead. Never enable training authorization.
- Execute the task order in `.agents/plan`. After each task, reconcile requirements,
  deliverables, dependencies, validation evidence and identical completion notes in
  all three files. Strike through the finished checklist item and run
  `python scripts/validate_work_plan.py` successfully before starting its successor.
- Do not confuse a finished engineering task with a qualified model. General
  language must meet its formal held-out gates before scientific-language promotion;
  scientific language precedes OCR, manuscripts, integration and later specialists.
- Keep source and configuration names functional (ADR-013). Keep experiments outside
  the automated test suite, measured reports outside normative specifications, and
  local model weights/datasets outside Git.
- Preserve existing unmerged changes and measured evidence. Do not merge or release
  as part of this preparation task.
