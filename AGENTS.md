# Working rules

The owner's current direction (2026-11-13): finish the model (ResearchLLM, programme 1) first; build the Rust system
and server (programme 2) while the next model task waits for the owner; the client after the model; the main brain
last (programme 3). The working ledger is `.claude/spec/spec.md` with `plan/` and `task/` (one file per programme:
`1-model`, `2-system`, `3-brain`). Read them before changing the repository, execute tasks in plan order, update spec,
plan and task together, and run `python scripts/validate_spec.py` before starting the next task (from T121:
`cargo xtask spec`). The earlier `.agents/` ledger is retired; do not recreate it.

- Branches: `laris-v2` integrates. Cut one feature branch per task from it (`feature/Txx-<slug>`), one task per
  session. After a task, cross-check it against plan and spec, then commit and merge it into `laris-v2`
  (owner authorisation of 2026-11-13). Push, tag and release stay with the owner (ADR-021 D42; `docs/development/GIT_FLOW.md` describes
  generation 1). `laris-v1` is frozen.
- A Rust task ends with `cargo fmt --check`, `cargo clippy -D warnings`, `cargo test` and `cargo deny check`
  (available from T121). Only crates and tools approved in T119 / ADR-021 may be added.
- Do not execute neural training, tokenizer fitting, backward/optimizer steps, or
  optimizer-bearing profiling. Do not run tests that perform these operations.
  Prepare commands for the owner instead. Never enable training authorization.
- Do not confuse a finished engineering task with a qualified model. The foundation model is NOT
  QUALIFIED; say so wherever it affects an answer, and do not claim scientific capability that was
  not measured against its formal held-out gates.
- Keep source and configuration names functional (ADR-013). Keep experiments outside
  the automated test suite, measured reports outside normative specifications, and
  local model weights/datasets (and collected fine-tune data) outside Git.
- Policy lives in `.laris/` (`prompts/`, `rules/`, `workflows/`, `help/`) and `LARIS.md`; it is covered
  by `integrity.lock`. Change it only with the owner's approval; `integrity.lock` is refreshed by
  the Rust harness once it provides verify and lock (the generation-1 `laris harness` commands no longer exist).
  No tunable, endpoint or secret is hardcoded: configuration and environment only.
- Preserve measured evidence and existing changes. Push, tag and release only within explicit owner
  authorization; merging a finished task into `laris-v2` follows the branch rule above.
- Do not install new dependencies without owner approval.
