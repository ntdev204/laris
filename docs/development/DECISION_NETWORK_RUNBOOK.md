---
document_id: "DOC-DEV-DECISION-NET-RUNBOOK-001"
title: "Decision network owner run (T170)"
document_type: "architecture"
status: "DRAFT"
version: "0.1.0"
created_at: "2026-11-20"
updated_at: "2026-11-20"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/adr/ADR-024-main-brain-design.md"
decision_references:
  - "ADR-024"
change_summary: "First version: commands, budget, stop rules and intake checks of the decision network run."
---

# Decision network owner run (T170)

The agent writes and tests the code around this run and never executes it (SR-M3). The owner trains the
decision network (ADR-024 5.4) with the commands below and returns the run directory; the agent then runs the
intake. A passing intake is **not** a promotion: the network is NOT QUALIFIED until it passes the sealed
held-out gates N1 to N8 in T171, and the rule decider stays in charge until the owner decides otherwise.

## 1. Before the run

1. Build the dataset from the real decision logs, **dated before the run** (the intake compares the dates).
   Output goes outside Git:

   ```bash
   cargo xtask decision-data --config CONFIG.json --out data/decision/RUN_DATE --date RUN_DATE --log LOG...
   cargo xtask decision-data --config CONFIG.json --verify data/decision/RUN_DATE
   ```

   Read `manifest.json`: `scenario_share` is 1.0 when there are no real logs. A network trained on scenario
   examples only learns the scenario oracle, a hand-made model of the world; say so in every result.
2. Read `configs/decision-net-training.json`. It is the whole prepared command: nothing is defaulted in the
   script. Change a value only in a copy, and use that copy in both commands (the run records its checksum).

## 2. The run (owner)

```bash
LARIS_TRAINING_AUTHORIZED=1 uv run python scripts/train_decision_net.py \
    --config configs/decision-net-training.json \
    --dataset data/decision/RUN_DATE \
    --out artifacts/decision-net/RUN_DATE-seed170
```

The output directory must not exist. The script reads `train.jsonl` and `validation.jsonl` only and never opens
the sealed splits. It writes `net.json` (best epoch, temperature and abstention threshold fitted on the
validation split), `train-log.jsonl` (one line per epoch) and `run.json`. Weights and logs stay outside Git.

| Budget and stop rules (config key) | Value of the prepared config | Effect |
| :--- | :--- | :--- |
| `max_epochs` | 200 | stops with reason `max_epochs` |
| `max_seconds` | 1800 | stops after the epoch that passes it: `max_seconds` |
| `patience`, `min_delta` | 15, 0.0001 | stops when the best validation loss is `patience` epochs old |
| `divergence_factor` | 3.0 | validation loss above 3 times that of epoch 1: `diverged` (run fails, no network) |
| non-finite loss | always | `non_finite_loss` (run fails, no network) |
| `max_parameters` | 5000 | the script refuses an architecture above it (the prepared one has 2 273) |

The model is the multilayer perceptron of T169 (36 inputs, hidden 32 and 32, one logit); the loss is binary
cross-entropy on (state, candidate) pairs, labelled by outcomes, not by the rule decider's choice.

## 3. Intake (agent, read-only)

```bash
uv run python scripts/decision_net_intake.py --run artifacts/decision-net/RUN_DIR \
    --dataset data/decision/RUN_DATE --config configs/decision-net-training.json \
    --report reports/brain/T170-decision-net-intake.json
```

It fails the run when any of these is false: the run used this config and this dataset manifest; only `train`
and `validation` were read; the seal and the sealed files are unchanged and were written no later than the run
started; the log has one contiguous line per epoch with finite values, within the epoch and time budget; the
stop rules, replayed on the log, give the recorded epoch and reason; `net.json` loads, matches the run record,
the architecture and the parameter limit, and names the same dataset, config and seed; the recorded validation
numbers reproduce from the exported weights with the float64 reference; and the temperature and threshold are
the validation fit. Warnings (not failures) say when the network does not beat the majority-by-action baseline
or when validation loss is far above train loss.

## 4. After the intake

T171 measures the gates on the sealed split, once, against the rule decider. Nothing from this run's validation
analysis may be quoted as held-out performance.
