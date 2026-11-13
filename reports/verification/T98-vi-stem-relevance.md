# T98 — Vietnamese STEM retrieval-relevance gold (G12)

Date: 2026-11-13 · Branch `feature/T98-vi-stem-relevance` · The foundation model is **NOT QUALIFIED**; this
report measures a dataset, not the model. No training, tokenizer fit or optimizer step ran; the dense pool used the R1
encoder for inference only.

## What this is, and what it is not

**This is LLM-labelled evidence, not human gold.** Protocol D05 forbids agents from creating gold labels. The owner
told the assistant to assign the labels ("Bạn tự gán", then "gán A2 luôn"), so the manifest records
`label_source: llm` and `human_gold: false`. The owner has to accept this explicitly before gate G12 is promoted
for Vietnamese. Annotator A1 was a set of subagents; annotator A2 was the assistant itself, and A2 did not open A1's
labels while labelling. Both are language models, so agreement between them is not independent evidence of human
agreement, and shared model biases agree by construction.

## Construction (all frozen before labelling)

| Item | Value |
|---|---|
| Source text | VIPUBMED machine-translated PubMed abstracts, `data/raw/vi_pubmed_candidate/` (licence "cc", subtype not cleared; no training use) |
| Corpus | 4,000 passages, 500–1,800 chars, seed 42 |
| Queries | 200 Vietnamese queries written from 200 sampled passages (pilot 20, dev 140, test 40); the split is by query |
| Pooling | BM25 top 5 + dense (R1 encoder) top 3 + the source passage, `top_k` 6 |
| Items | 1,561 (pilot 157, dev 1,093, test 311) |
| Labels | 0 not relevant, 1 partly relevant, 2 answers the query; the lower label when unsure |
| Guideline | `docs/training/D05_GUIDELINE_VI_STEM.md`, sha256 in `freeze_manifest.json` |
| Test split | sealed: not for tuning, hard-negative mining or checkpoint choice |

## Agreement and adjudication

| Split | Items | Weighted quadratic kappa | Nominal kappa | Disagreements | Status |
|---|---|---|---|---|---|
| pilot | 157 | 0.9427 | 0.8044 | 7 | accepted |
| dev | 1,093 | 0.9448 | 0.8335 | 43 | accepted |
| test | 311 | 0.9325 | 0.7749 | 17 | accepted |

Threshold 0.85 (weighted). All 67 disagreements were adjudicated by the assistant, who by then had seen both labels
(`adjudication.json`): 54 became 2, 7 became 1 and 6 became 0. 55 of the 67 were A1 = 1 versus A2 = 2, that is, A1
was stricter on the passage a query was written from. Seal digests: dev `775bff75…2bd1`, test `c377ce16…36eb23`
(`reconcile_report.json`).

## Known limits

- **Queries:** 55 of 200 queries share a 6-gram with their source passage (listed in `freeze_manifest.json`), so lexical
  retrieval has an easier time on them than on a fully paraphrased query.
- **Passage view:** during A2 labelling the display cut each passage to its head plus the best query-matching window. A2 opened
  the full text for some ambiguous passages (about 40); the rest were judged on the truncated view. This can hide a relevant
  sentence and push a label down.
- **Machine-translation artefacts:** some source passages are degenerate repetitions (for example
  q102, q128 and the source of q085). They were labelled 1 when they were the source and only their title
  matched.
- **Adjudication:** one model adjudicated with sight of both labels; no human reviewed the 67 changes or a sample of
  the agreed items.
- **Licence:** the source licence is not cleared, so the data stays under `data/processed/gold_vi_stem/`, which Git ignores.
  Only the script, the guideline and this report are committed.

## Reproduction

```
.venv/bin/python scripts/build_vi_stem_gold.py sample
.venv/bin/python scripts/build_vi_stem_gold.py pool      # R1 encoder, inference only
.venv/bin/python scripts/build_vi_stem_gold.py reconcile
```

Labels and the 200 queries are model outputs saved in the git-ignored data directory; `sample` and `pool` are
deterministic given them.

## What this does and does not allow

It supplies a Vietnamese STEM relevance set with a frozen guideline and a sealed test split for the G12 measurement
(T99/T100 are owner runs). It does not show the model is qualified, and it does not replace human gold. Until the
owner accepts LLM labels, G12 for Vietnamese stays unpromoted.
