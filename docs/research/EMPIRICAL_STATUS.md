---
document_id: "DOC-REPORT-EMPIRICAL-001"
title: "Checkpoint Validation and Scientific NLP Pilot"
document_type: "report"
status: "DRAFT"
version: "1.0.0"
created_at: "2026-11-10"
updated_at: "2026-11-10"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: false
related_documents:
  - "docs/plans/ROADMAP.md"
  - "docs/testing/BENCHMARK_PROTOCOL.md"
  - "docs/development/CLI.md"
decision_references:
  - "ADR-008"
change_summary: "Records measured checkpoint and pilot results, extraction failures, and the next experiment gates."
---

# Checkpoint validation and scientific NLP pilot

## Measured readiness

The compact encoder has trained local checkpoints. The measured best checkpoint
is `compact-1024-04/best`, optimizer step 50,600, trained from commit `dde23d8`.
Its model, tokenizer and dataset-manifest SHA-256 values matched the training
manifest. All 14 validation file hashes also matched their partition manifest.
This verifies file identity against the recorded manifest, rather than independently
re-proving that the original partitions contain no leakage.

The encoder exceeds the shipped baseline-relative acceptance floors. It has not
established the roadmap's scientific contradiction, retrieval or research-gap gates.
No test-set evaluation, additional training or threshold calibration was performed.

## Encoder validation

Source: [raw evaluation report](evidence/compact-1024-04-best-val.json).
The evaluation used 27,213 validation samples: up to 2,000 per dataset, batch 8,
seed 42, 1,024-token checkpoint configuration, and CUDA inference on RTX 5070 Ti.
Runtime was PyTorch 2.14.1+cu130. Total observed GPU usage during evaluation was
approximately 4.6 GB, including desktop processes; this is not a training profile.

| Task | Language | Metric | Checkpoint | Baseline |
| --- | --- | --- | ---: | ---: |
| MLM | EN | Masked accuracy | 0.5780 | 0.0343 |
| MLM | VI | Masked accuracy | 0.7188 | 0.0403 |
| NLI | EN | Macro F1 | 0.5966 | 0.1879 |
| NLI | VI | Macro F1 | 0.5385 | 0.1647 |
| Paraphrase | EN | AUC | 0.8274 | 0.5000 |
| QA | EN | Token-span F1 | 0.6115 | 0.0000 |
| QA | VI | Token-span F1 | 0.4190 | 0.2931 |
| Similarity | EN | Spearman | 0.7705 | 0.6124 |
| Similarity | VI | Spearman | 0.6866 | 0.5670 |

All nine groups passed the existing floors. Dataset results expose material
variation: ALL-NLI macro F1 was 0.8294, ANLI 0.4042 and ViNLI 0.5385.
FEVER macro F1 was 0.5562 using the evaluator's three-class definition, although
the processed FEVER evidence pairs only cover entailment and contradiction;
this score is not directly comparable to a three-label scientific NLI benchmark.
QA here measures overlap of predicted and gold token positions, rather than the
official normalized answer-string metric. Paraphrase has no Vietnamese group
in the current validation shards. Group scores average dataset-level metrics
weighted by sample count; they are not pooled-example macro F1 or AUC.

Reproduce from the repository root after installing dependencies:

```bash
OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 .venv/bin/laris evaluate language-encoder \
  --checkpoint artifacts/checkpoints/language_encoder/compact-1024-04/best \
  --tokenizer-model artifacts/tokenizer/laris_spm_32k.model \
  --split val --max-samples 2000 --batch-size 8 --seed 42 --device cuda \
  --output artifacts/evaluations/language_encoder/compact-1024-04-best-val.json
```

## Real-paper integration pilot

Sources: [20-paper manifest](evidence/scientific-nlp-corpus.json) and
[results with manual audit](evidence/scientific-nlp-pilot.json).
The bounded corpus covers scientific information extraction, evidence verification,
research-question generation and literature synthesis. PDFs were downloaded from
ACL Anthology; the manifest preserves URLs, PDF hashes, extracted-text hashes and
license links. These papers were used for the pilot only, with no changes to the
training splits. Text hashes depend on the Poppler extraction version.

The pilot exercised corpus license/normalization/deduplication checks, 1,290 text
passages, a persisted SQLite graph, lexical retrieval, the checkpoint's normalized
CLS embeddings, graph retrieval and reciprocal-rank fusion. Graph round-trip
counts matched: 1,310 nodes and 1,290 source-derivation edges.

Six manually selected queries each had one designated target paper. Ranking was
deduplicated by paper, and success means that target appeared among the first five
distinct papers in the first 100 passage results. BM25 succeeded on 6/6 queries,
dense on 1/6 and hybrid on 5/6. These are integration diagnostics on curated
queries, not an independent relevance benchmark or a general effectiveness claim.
Dense and hybrid have not demonstrated an improvement over lexical retrieval.

The extractive report's 12 assertions passed exact source hash/span verification.
Manual inspection judged only 5/12 useful as standalone excerpts; the remainder
included a broken URL, PDF reading-order corruption, missing context, headings,
an instructional prompt and a table pointer. This audit is an analyst judgment,
not an inter-annotator agreement study. No research gaps were verified. The pilot
does not meet production report or autonomous discovery acceptance criteria.

The source gate also rejected modified source text, an unsupported assertion and
additional unregistered prose. Citation-ID coverage alone remains insufficient
to establish extraction quality, entailment or novelty. An exact quote can still
be irrelevant, incomplete or assembled from corrupt PDF reading order.

For reproduction, apply the source-backed-report change (issue #311 / PR #312),
then run the bounded experiment scripts. Checkpoint and tokenizer artifacts must
be present; downloads require internet and inference requires CUDA:

```bash
.venv/bin/python tests/experiments/scientific_nlp_acquire.py
OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 \
  .venv/bin/python tests/experiments/scientific_nlp_pilot.py
```

Outputs go under `artifacts/pilots/scientific_nlp/`. Manual-audit annotations in
the committed results are not generated automatically by a rerun.

## Next experiment gates

1. Build independent relevance judgments for scientific retrieval, covering
   paraphrased queries, hard negatives, multiple relevant papers and Vietnamese.
   Freeze a held-out set before tuning. Compare BM25, dense and hybrid using MRR
   and nDCG, with per-query error review.
2. Repair and evaluate PDF reading order, sentence boundaries and figure/table
   contamination before treating extracted spans as usable assertions. Retain
   page mapping and review failure cases from this pilot.
3. Evaluate scientific contradiction and evidence support with verified labels,
   including scope/conditions and counter-evidence. General NLI validation scores
   do not certify scientific reasoning.
4. Only then compare retrieval-aligned training, such as contrastive query/evidence
   learning, against the current CLS baseline. Measure retrieval gains and regression
   on the five existing tasks before selecting a new checkpoint or scaling models.
5. Validate source-backed, semantically supported cross-paper synthesis and
   adversarial gap rejection. A missing search result must not be treated as proof
   of an unexplored research gap.

The current decision is to preserve the measured checkpoint and acceptance
thresholds. Additional training is deferred until independent retrieval/evidence
evaluation can identify and measure the intended improvement.

## Change validation

The combined proposed benchmark, source-gate and empirical-report changes passed
all 1,176 tests locally with CUDA enabled and optional progress tooling installed.
Ruff, mypy (146 source files), documentation validation (51 Markdown documents)
and whitespace checks also passed. One existing PyTorch warning in an
initialization test concerns converting a gradient-tracking tensor to a scalar.
The proposed changes remain in draft PRs and have not been merged into the
release or integration branches.
