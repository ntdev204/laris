# T98 — Vietnamese STEM retrieval-relevance gold (G12)

Date: 2026-11-13 · Branch `feature/T98-vi-stem-relevance` · The foundation model is **NOT QUALIFIED**; this
report measures a dataset, not the model. No training, tokenizer fit or optimizer step ran; the dense pool used the R1
encoder for inference only.

## What this is, and what it is not

**This is LLM-labelled evidence, not human gold.** The owner told the assistant to assign the labels ("Bạn tự gán",
"gán A2 luôn") and on 2026-11-13 lifted the D05 ban on agent labels (principle 1 of
`docs/training/D05_HUMAN_GOLD_PROTOCOL.md`). The manifest still records `label_source: llm` and `human_gold: false`,
and no result may call this human gold. Annotator A1 was a set of subagents; annotator A2 was the assistant itself, and A2 did not open A1's
labels while labelling. Both are language models, so agreement between them is not independent evidence of human
agreement, and shared model biases agree by construction.

## Construction (all frozen before labelling)

| Item | Value |
|---|---|
| Source text | VIPUBMED machine-translated PubMed abstracts, `data/raw/vi_pubmed_candidate/` (licence "cc", subtype not cleared; no training use) |
| Corpus | 4,000 passages, 500–1,800 chars, seed 42 |
| Queries | 200 written, 196 kept (4 excluded, below); split by query |
| Pooling | BM25 top 5 + dense (R1 encoder) top 3 + the source passage, `top_k` 6 |
| Items | 1,529 after exclusion (pilot 157, dev 1,068, test 304) |
| Labels | 0 not relevant, 1 partly relevant, 2 answers the query; the lower label when unsure |
| Guideline | `docs/training/D05_GUIDELINE_VI_STEM.md`, sha256 in `freeze_manifest.json` |
| Test split | sealed: not for tuning, hard-negative mining or checkpoint choice |

## Second pass (2026-11-13, owner instruction)

1. **A2 on full text.** The first A2 pass judged part of the items on a truncated view. Every item that A2 had not
   labelled 2, whose passage is at least 430 characters and shares six or more query bigrams with the query (86 items, a
   screen, not a full re-read of 1,529), was re-read in full. Three labels changed to 1 (two checkpoint-immunotherapy
   passages for q013 and the China warfarin-registry passage for q186). The old A2 files are in `labels/archive_A2_v1/`.
   Items outside the screen were not re-read; A1 had full text for all of them, and the 61 disagreements were adjudicated on full text.
2. **Copied queries.** The 55 queries that shared a 6-gram with their source passage were paraphrased; the original is kept as
   `query_original`, and none of the 196 queries now shares a 6-gram with its source. Pooling ran on the original queries and the
   items are unchanged, so a paraphrase can miss a passage the pool lacks; pool coverage was not re-measured. Existing labels
   were kept for the paraphrased queries.
3. **Degenerate sources.** q016, q085, q102 and q128 are built on source passages that are repeated-token machine-translation
   garbage; they are excluded from the sealed gold (`amendments.json`, `freeze_manifest.json`).
   Other garbled non-source passages stay in the pool as ordinary negatives.

## Agreement and adjudication

| Split | Items | Weighted quadratic kappa | Nominal kappa | Disagreements | Status |
|---|---|---|---|---|---|
| pilot | 157 | 0.9427 | 0.8044 | 7 | accepted |
| dev | 1,068 | 0.9523 | 0.8476 | 39 | accepted |
| test | 304 | 0.9392 | 0.7942 | 15 | accepted |

Threshold 0.85 (weighted). All disagreements were adjudicated by the assistant, who by then had seen both labels
(`adjudication.json`). Seal digests: dev `b72ebdf0…`, test `95df9287…` (full values in `reconcile_report.json`). A1 was a set of subagents and A2 the assistant, both
language models: agreement measures consistency, not human agreement.

## Remaining limits

- Both annotators are models and share biases; no human reviewed any label.
- The screen in step 1 is heuristic; a relevant sentence that shares no query bigram with a passage could still be missed.
- Paraphrased queries were not re-pooled (step 2).
- The source licence is not cleared, so the data stays under `data/processed/gold_vi_stem/` (git-ignored). Only the script,
  guideline and this report are committed.

## Reproduction

```
.venv/bin/python scripts/build_vi_stem_gold.py sample
.venv/bin/python scripts/build_vi_stem_gold.py pool      # R1 encoder, inference only
.venv/bin/python scripts/build_vi_stem_gold.py amend     # paraphrases and exclusions
.venv/bin/python scripts/build_vi_stem_gold.py reconcile
```

Labels and the 200 queries are model outputs saved in the git-ignored data directory; `sample` and `pool` are
deterministic given them.

## What this does and does not allow

It supplies a Vietnamese STEM relevance set with a frozen guideline and a sealed test split for the G12 measurement
(T99/T100 are owner runs). It does not show the model is qualified, and it does not replace human gold. Using it for
G12 follows the owner's instruction of 2026-11-13 and must be reported as LLM gold.
