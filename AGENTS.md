# Working rules

Read `.agents/spec.md`, `.agents/plan.md` and `.agents/task.md` before changing this repository.
They define the system specification, remaining project plan and project task ledger.

- Do not execute neural training, tokenizer fitting, backward/optimizer steps, or
  optimizer-bearing profiling. Do not run tests that perform these operations.
  Prepare commands for the owner instead. Never enable training authorization.
- Execute the task order in `.agents/plan.md`. After each task, reconcile requirements,
  deliverables, dependencies, validation evidence and identical completion notes in
  all three files (including the spec task-progress index). Strike through the finished checklist item and run
  `python scripts/validate_work_plan.py` successfully before starting its successor.
- Do not confuse a finished engineering task with a qualified model. General
  language must meet its formal held-out gates before scientific-language promotion;
  scientific language precedes OCR, manuscripts, integration and later specialists.
- Keep source and configuration names functional (ADR-013). Keep experiments outside
  the automated test suite, measured reports outside normative specifications, and
  local model weights/datasets outside Git.
- Preserve measured evidence and existing changes. Merge/release only within explicit
  owner authorization. The prior preparation PR #314 is merged into develop.
- The current request is to write and validate the three Markdown documents, then
  report back. Do not start the next project implementation task (G02, then F01) until asked.
