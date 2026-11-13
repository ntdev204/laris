# T94 — Model-block verification on `laris-v2`

Date: 2026-11-13 · Command: `.venv/bin/python scripts/verify_model_block.py` · Not a model measurement.

| Step | Result |
|---|---|
| no-training guard | 117 test files run, 10 excluded as training/profiling, 3 excluded as obsolete on `laris-v2` |
| ruff (`src tests scripts`) | pass |
| mypy (`src/laris`, 187 files) | pass |
| pytest (non-training files) | 1259 passed, 35 subtests, 1 warning |

Excluded because they train, run backward/optimizer steps or authorize training (never run by agents):
`tests/cli/test_laris_cli.py`, `tests/contract/test_readiness_blockers_contracts.py`,
`tests/unit/language/{test_encoder_scaling_and_training,test_memory_profile,test_neural_model,
test_padding_and_head_skipping,test_position_and_decay,test_trainer_and_streaming_dataloader,
test_training_data_integrity,test_training_loop}.py`. The list is computed by the guard on every run
(`--list` prints it); a guard hit is conservative, so some of these only construct a trainer or assert refusal.

Excluded as obsolete on `laris-v2` (fail for reasons unrelated to the model):
`tests/contract/test_spec_ledger.py` (v1 ledger, replaced by `scripts/validate_spec.py`),
`tests/documentation/test_docs.py` (48 links to documents removed on `laris-v2`),
`tests/unit/architecture/test_layers.py` (reads `src/laris/client/agent`, removed).

Guard seeded checks (`tests/unit/scripts/test_verify_model_block.py`): a backward call, an optimizer step, the trainer,
`run_training` and a set `LARIS_TRAINING_AUTHORIZED` are each caught; a `delenv` is not; the script exits 2 when the
variable is set in its environment and removes it from child processes.
