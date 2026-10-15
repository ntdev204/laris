---
document_id: "DOC-TEST-BENCH-001"
title: "LARIS Empirical Benchmark Protocol & Capability Evaluation"
document_type: "test"
status: "DRAFT"
version: "0.1.0"
created_at: "2026-10-15"
updated_at: "2026-10-15"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/IDEA.md"
  - "docs/testing/TEST_STRATEGY.md"
  - "docs/research/EVALUATION_STRATEGY.md"
decision_references:
  - "ADR-008"
change_summary: "Formal benchmark execution protocol, evaluation metrics, and dataset leakage rules."
---

# LARIS Empirical Benchmark Protocol & Capability Evaluation

## 1. Governance & Protocol Principles

In accordance with [ADR-008](file:///home/thientn204/laris/docs/adr/ADR-008-evaluation-before-capability-claims.md), benchmarks in LARIS are reproducible, version-controlled experiments executed against frozen test datasets.

### Non-Negotiable Protocol Rules:
1. **Zero Test Set Contamination:** Test documents must never be included in tokenization or pretraining corpora.
2. **Fixed Evaluation Seeds:** All stochastic evaluations must specify a fixed random seed.
3. **Hardware Telemetry Recording:** Every benchmark run must log GPU VRAM allocated, host RAM used, and wall-clock execution time.
4. **Permanent Benchmark Reports:** Results are archived as versioned markdown reports in `artifacts/benchmark_reports/`.

---

## 2. Core Benchmark Suites

| Suite ID | Evaluated Capability | Primary Metrics | Target Threshold |
| :--- | :--- | :--- | :--- |
| `BENCH-STEM-TOKEN-01` | STEM Tokenizer Fertility | Tokens per word on STEM test set. | $\le 1.40$ tokens/word |
| `BENCH-SCINLI-01` | Scientific NLI & Contradiction | Macro F1, Contradiction Recall. | Macro F1 $\ge 0.82$ |
| `BENCH-DISCOURSE-01` | Heading-Agnostic Limitation Detection | Sensitivity (Recall) on stripped-header test set. | Recall $\ge 80.0\%$ |
| `BENCH-GAP-VAL-01` | Research Gap Non-Triviality | Adversarial refutation rate, expert validation. | $> 85\%$ validated |
| `BENCH-PROVENANCE-01`| Zero Hallucination & Coordinate Validity | Percentage of claims linked to valid source coordinates. | 100.0% Exact Match |
| `BENCH-HARDWARE-01` | Local Workstation Resource Safety | Peak VRAM on RTX 5070 Ti, Peak Host RAM. | Peak VRAM $\le 15.0$ GB |
