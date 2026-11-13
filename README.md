# Local Agentic Research Intelligence System (LARIS)

**LARIS** is a scientific research system: a strong harness (agent loop, tools, policy, evidence gate,
brain) around a self-built language model. The model is the brain; the system decides how the work
is done.

## Status of this branch (`laris-v2`)

- The Python generation (client, server, Ink front end, packaging, CI, Docker) is frozen on the
  protected branch `laris-v1` (version 2.2.0).
- This branch is being rebuilt: the harness in Rust, the model side kept in Python. The plan is in
  [`idea.md`](idea.md) until the new specification exists.
- What remains in Python here: the model service (`src/laris/model`), research and evaluation code
  (`src/laris/research`), scientific NLP (`src/laris/shared`), the `laris-model` command, and their
  tests. Recorded interface scenarios kept as golden behaviour are in `tests/golden/ink_scenarios/`.
- The foundation model is **NOT QUALIFIED**: see the
  [empirical status report](docs/research/EMPIRICAL_STATUS.md).

## Documentation

Start at the [documentation index](docs/README.md). Working rules for agents are in `AGENTS.md`.
