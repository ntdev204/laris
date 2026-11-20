# Local Agentic Research Intelligence System (LARIS)

**LARIS** is a scientific research system: a strong harness (agent loop, tools, policy, evidence gate,
brain) around an open-weight third-party language model (D48). The model advises; the system decides how the work
is done.

## Status of this branch (`laris-v2`)

- The Python generation (client, server, Ink front end, packaging, CI, Docker) is frozen on the
  protected branch `laris-v1` (version 2.2.0).
- This branch is being rebuilt: the harness in Rust, the model side kept in Python. The specification, plan and tasks are the ledger in
  [`.claude/spec/`](.claude/spec/spec.md).
- What remains in Python here: the model service (`src/laris/model`), research and evaluation code
  (`src/laris/research`), scientific NLP (`src/laris/shared`), the `laris-model` command, and their
  tests. The self-trained encoder and its training code were removed (D48). Recorded interface scenarios kept as golden behaviour are in `tests/golden/ink_scenarios/`.
- The model is **NOT QUALIFIED**: no capability is claimed without a measurement on its held-out gate
  (ADR-008). The open-LLM selection is in [`reports/verification/T228-open-llm-selection.md`](reports/verification/T228-open-llm-selection.md).

## Documentation

Start at the [documentation index](docs/README.md). Working rules for agents are in `AGENTS.md`.
