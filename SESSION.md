# LARIS Session Context

Local-first scientific research system (ADR-001). Docs index: [docs/README.md](docs/README.md). CLI: [docs/development/CLI.md](docs/development/CLI.md).

## Environments
- **Development (WSL2):** code, tests, docs, quality gates. **No neural training** — guarded by `src/laris/core/authorization.py`.
- **Target server:** RTX 5070 Ti 16 GB, i5-14600KF, 32 GB RAM, NVMe. Partitioning, tokenizer fitting and training run here only, with explicit owner authorization (`LARIS_TRAINING_AUTHORIZED=1`).

## Layout
`src/laris/` is organised by domain (ADR-011/012/013): `language/{tokenization,encoder,training,benchmarks,evaluation,inference}`, `corpus/{acquisition,splits}`, `retrieval/`, `cli/`. Tests mirror it under `tests/unit/<domain>/`.

## State
- Data: 24 datasets tracked, 8,347,135 samples (~12 GB), 20 VERIFIED; ViNLI, UIT-ViQuAD2.0 and CC-100 are `APPROVED_BY_OWNER`.
- Partitioned so far: ViSTS, HotpotQA, FEVER, ViNLI, UIT-ViQuAD2.0, CC100-VI-CLEAN. Wikipedia, Quora, SQuAD, All-NLI etc. still need partitioning.
- No trained weights exist. Next on the server: partition the rest, install `sentencepiece`, `laris train tokenizer`, then train and evaluate.
- Open follow-ups: tighten evaluation thresholds with measured results; FEVER has no evidence text.

## Workflow (Git Flow)
Issue → `feature/<id>-<desc>` off `develop` → `make check` (pytest, ruff, mypy, `scripts/validate_docs.py`) → PR into `develop` → squash merge → delete the branch → close the issue. `main` only for tagged releases. See [docs/development/GIT_FLOW.md](docs/development/GIT_FLOW.md).

## Rules
Name by function, never by version or stage. Claims need benchmark evidence (ADR-008). Tests must not depend on `sentencepiece` or a GPU.
