---
document_id: "DOC-DEV-STEM-ROUTER-RUNBOOK-001"
title: "STEM router network owner run (T287)"
document_type: "architecture"
status: "DRAFT"
version: "0.1.0"
created_at: "2026-11-24"
updated_at: "2026-11-24"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/adr/ADR-026-stem-benchmark-qualification.md"
decision_references:
  - "ADR-026"
change_summary: "First version: dataset, training command, held-out gates and promotion of the STEM router network."
---

# STEM router network owner run (T287)

The agent writes and tests the code around this run and never executes the training (SR-M3). The rule router of
T278 stays in charge unless the network passes every gate of `configs/stem-router-gates.json` (fixed by the owner on
2026-11-23, before any routing number) and the owner promotes it. The model and the system are NOT QUALIFIED.

## 1. Labels (inference, already run by the agent)

Each path on each development item, then the report:

```bash
python scripts/stem_benchmarks.py harness --path deterministic   --run path-deterministic
python scripts/stem_benchmarks.py harness --path notes_model     --run path-notes_model
python scripts/stem_benchmarks.py harness --path model_solver    --run path-model_solver
python scripts/stem_benchmarks.py harness --path plain_retrieval --run path-plain_retrieval
python scripts/stem_benchmarks.py router-report
```

The run names read by the report are in `router_analysis.runs` of `configs/stem-benchmarks.json`.

## 2. The sealed dataset

```bash
python scripts/stem_benchmarks.py router-dataset --out data/benchmarks/router/RUN_DATE
```

It writes `pool.jsonl` (70 %, with five cross-fitting folds), `heldout.jsonl` (30 %, seeded hash of the item id,
independent of any label) and `manifest.json` (SHA-256 of both files and of the gates). Features only, no text:
`routing.FEATURES`. The sealed benchmark test sets are never read.

## 3. Training (the owner)

```bash
python scripts/train_stem_router.py --owner-run --dataset data/benchmarks/router/RUN_DATE \
    --config configs/stem-router-training.json --out data/benchmarks/router/RUN_DATE/net.json
```

It reads `pool.jsonl` only (checked against the manifest), fits one logistic score per model path by full-batch
gradient descent with L2 (CPU, numpy, seconds), prints the cross-fitted accuracy of the network's choices against
the rule router's on the pool, and writes the network. Change a setting only in a copy of the configuration; the
network records the checksum of the one used.

## 4. Gates (once per network)

```bash
python scripts/stem_benchmarks.py router-gates --dataset data/benchmarks/router/RUN_DATE \
    --net data/benchmarks/router/RUN_DATE/net.json --report reports/benchmarks/T287-router-gates.json
```

It refuses when a file no longer matches the manifest or the gates changed after sealing, and exits 1 unless N1-N4
all pass. Report every result, failures included. A pass is not a promotion: the owner decides, and only then does
the harness read the network (abstaining to the rule router below confidence 0.6, never overriding a model-free or
brain-only answer). The server's `Decider` seam receives it with T284.
