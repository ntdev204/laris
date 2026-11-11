---
document_id: "DOC-TEST-BENCH-001"
title: "LARIS Empirical Benchmark Protocol & Capability Evaluation"
document_type: "test"
status: "DRAFT"
version: "0.2.0"
created_at: "2026-10-15"
updated_at: "2026-11-11"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/architecture/SYSTEM_OVERVIEW.md"
  - "docs/testing/TEST_STRATEGY.md"
  - "docs/research/RESEARCH_STRATEGY.md"
decision_references:
  - "ADR-008"
change_summary: "Aligns fertility and evidence storage with canonical foundation qualification; distinguishes coordinate validity from semantic support."
---

# LARIS Empirical Benchmark Protocol & Capability Evaluation

## 1. Governance & Protocol Principles

In accordance with [ADR-008](../adr/ADR-008-evaluation-before-capability-claims.md), benchmarks in LARIS are reproducible, version-controlled experiments executed against frozen test datasets.

### Non-Negotiable Protocol Rules:
1. **Zero Test Set Contamination:** Test documents must never be included in tokenization or pretraining corpora.
2. **Fixed Evaluation Seeds:** All stochastic evaluations must specify a fixed random seed.
3. **Hardware Telemetry Recording:** Every benchmark run must log GPU VRAM allocated, host RAM used, and wall-clock execution time.
4. **Permanent Benchmark Reports:** Auditable measurement reports are versioned under `reports/` (JSON and explanatory Markdown as appropriate). Local raw outputs, weights and datasets remain outside Git under `artifacts/` or `data/`.

---

## 2. Core Benchmark Suites

| Suite ID | Evaluated Capability | Primary Metrics | Target Threshold |
| :--- | :--- | :--- | :--- |
| `BENCH-STEM-TOKEN-01` | Tokenizer fertility | Tokens per word separately on unseen EN and VI text; STEM fixtures are supplementary diagnostics. | Canonical foundation G10/G11: $\le 1.35$ tokens/word per language |
| `BENCH-SCINLI-01` | Scientific NLI & Contradiction | Macro F1, Contradiction Recall. | Macro F1 $\ge 0.82$ |
| `BENCH-DISCOURSE-01` | Heading-Agnostic Limitation Detection | Sensitivity (Recall) on stripped-header test set. | Recall $\ge 80.0\%$ |
| `BENCH-GAP-VAL-01` | Research Gap Non-Triviality | Adversarial refutation rate, expert validation. | $> 85\%$ validated |
| `BENCH-PROVENANCE-01`| Coordinate Validity | Percentage of claims linked to valid source coordinates; semantic support needs a separate audit. | 100.0% Exact Match |
| `BENCH-HARDWARE-01` | Local Workstation Resource Safety | Peak VRAM on RTX 5070 Ti, Peak Host RAM. | Peak VRAM $\le 15.0$ GB |

Foundation qualification requires every gate and exact metric protocol in
[`foundation.yaml`](../../configs/evaluation/foundation.yaml) and section 5 of the
[training specification](../specifications/LANGUAGE_ENCODER_TRAINING_SPECIFICATION.md).
This suite summary is not a replacement for those 12 gates. The baseline-relative
floors in `language_encoder.yaml` serve regression checks only. Synthetic fixture
scores and the historical six-query pilot cannot certify held-out effectiveness.
