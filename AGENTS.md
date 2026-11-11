# Working rules

The owner's current direction (2026-11-11): build the complete system harness first (RAG, agent,
tools, skills, workflows, policy, learning data); the core reasoning model is paused and resumed
afterwards. The earlier spec/plan/task ledger under `.agents/` is retired; do not recreate it.

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
  by `integrity.lock`. Change it only with the owner's approval, then run `laris harness verify` and
  `laris harness lock`. No tunable, endpoint or secret is hardcoded: configuration and environment only.
- Preserve measured evidence and existing changes. Push, merge, tag and release only within explicit
  owner authorization, through pull requests (see `docs/development/GIT_FLOW.md`).
- Do not install new dependencies without owner approval.
