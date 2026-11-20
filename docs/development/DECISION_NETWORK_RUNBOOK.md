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

## 5. Held-out gates (T171)

The gates N1 to N8 of ADR-024 section 8 are measured on the sealed held-out split, against the rule decider, with
inference only (no training authorisation is needed or used). Thresholds are in `configs/decision-net-gates.json`.

```bash
cargo run --release -p xtask -- decision-gates --dataset data/decision/RUN_DATE \
    --dataset-config data/decision/config-RUN_DATE.json --net artifacts/decision-net/RUN_DIR/net.json \
    --gates configs/decision-net-gates.json --out SCRATCH/pre.json --scores-out SCRATCH/scores.json
uv run python scripts/decision_net_parity.py --net artifacts/decision-net/RUN_DIR/net.json \
    --dataset data/decision/RUN_DATE --scores SCRATCH/scores.json --out SCRATCH/parity.json
cargo run --release -p xtask -- decision-gates --dataset data/decision/RUN_DATE \
    --dataset-config data/decision/config-RUN_DATE.json --net artifacts/decision-net/RUN_DIR/net.json \
    --gates configs/decision-net-gates.json --out reports/brain/T171-decision-net-gates.json --parity SCRATCH/parity.json
```

The first command is the same measurement as the last; it exists only to write the scores for the parity check
(N6). Do not change the network, the thresholds or the dataset after reading a number. A gate that was not measured is
`NOT VERIFIED` and is not a pass; the command exits 1 unless all eight pass. Even then the promotion is the owner's
decision, recorded in the task note. N7 is timed on the machine that runs the command: the specification does not
define the reference CPU, so say which machine it was.

## 6. Cognitive evaluation (T172)

One command writes the report of SR-K7. It uses the real write gate, rule decider, answer assembly and prompt layer, with
advisors given as data:

```bash
cargo run --release -p laris-brain --example cognitive_eval -- \
    --config configs/cognitive-eval.json --out reports/brain/T172-cognitive-evaluation.json
```

The four advisors in the configuration are scripted profiles, labelled as such in the report. To measure ResearchLLM
(or any other advisor), record its answers (inference only) and label them:

```bash
HOME=SCRATCH/home HF_HUB_OFFLINE=1 LARIS_MODEL_SERVICE__CHAT_MODEL_ID=MODEL_DIR \
    uv run python scripts/record_advisor.py --config configs/cognitive-eval.json --name NAME --out RAW.json
```

`RAW.json` has every label `null`. Read each entry against the accepted claims, fill the labels and save the file in
`reports/brain/advisors/`. The shape of that file is:

```json
{
  "name": "researchllm-RUN_DATE",
  "kind": "recorded: ResearchLLM checkpoint, prompt and decoding settings",
  "replies":    {"q1": {"text": "...", "supported": true}, "...": {}},
  "rewordings": {"c1": {"text": "...", "faithful": true}, "...": {}},
  "proposals":  [{"statement": "...", "source": "Paper", "quote": "...", "supported": false}]
}
```

`replies` has one entry per question id and `rewordings` one per claim id of the configuration. `supported` and
`faithful` are labels that **you** assign by reading the reply against the accepted claims (a reply that asserts
nothing outside them is supported); the harness trusts them, so label before looking at the numbers. Then add
`--advisors that-file.json` (repeatable) to the command. The file's checksum is written to the report. The report is a
set of system measurements; it never qualifies the model, and `tests/cognition.rs` keeps checking the invariants of
the system with the scripted advisors only.
