---
document_id: "DOC-TMPL-REP-001"
title: "Standard Benchmark Report Template"
document_type: "template"
status: "DRAFT"
version: "0.1.0"
created_at: "2026-10-15"
updated_at: "2026-10-15"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/DOCUMENTATION_STANDARD.md"
  - "docs/testing/BENCHMARK_PROTOCOL.md"
decision_references:
  - "ADR-008"
change_summary: "Standard template for recording empirical benchmark outcomes."
---

# Benchmark Report: [Suite ID & Run Title]

## 1. Run Metadata
- **Benchmark Suite ID:** `BENCH-XXX-01`
- **Model Checkpoint:** `artifacts/checkpoints/[model_id]`
- **Execution Date:** YYYY-MM-DD
- **Random Seed:** 42
- **Hardware Platform:** NVIDIA GeForce RTX 5070 Ti 16GB, 32GB RAM, i5-14600KF

## 2. Quantitative Results Table
| Metric Name | Baseline Standard | Target Threshold | Measured Score | Pass / Fail |
| :--- | :--- | :--- | :--- | :--- |
| [Metric A] | 0.00 | 0.00 | 0.00 | PASS / FAIL |
| [Metric B] | 0.00 | 0.00 | 0.00 | PASS / FAIL |

## 3. Physical Hardware Telemetry
- **Peak GPU VRAM Allocated:** [e.g. 8.4 GB]
- **Peak Host RAM Used:** [e.g. 14.2 GB]
- **Average Inference Latency:** [e.g. 24 ms/step]
- **Zero OOM Violations:** YES / NO

## 4. Failure Analysis & Taxonomy Errors
- [Summary of error taxonomy classifications, edge cases, and hard negatives.]

## 5. Conclusions & Milestone Impact
- [Assessment against milestone acceptance criteria.]
