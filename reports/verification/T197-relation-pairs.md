# T197 — Relation pairs for contrastive similarity

Date 2026-11-16. Script `scripts/build_relation_pairs.py`, tests `tests/unit/language/test_relation_pairs.py`
(10 fixture tests), figures `T197-relation-pairs.json` (seed 17). Output
`data/processed/relation_pairs_en/train.parquet` (outside Git, 1,410,056 rows). No model, no training,
no tokenizer fit, no backward step.

## What the pairs are

Relation labels derived from data already on disk. They are **not graded similarity** and are never
reported as human similarity data; STS-B validation and test stay the only gate data (G05). Every row has
`label_source: derived`, `relation`, `polarity`, `source` and `symmetric`. Only training splits are read.

| Relation | Polarity | Rule | Sources |
|---|---|---|---|
| `entailment` | positive | premise and hypothesis with gold label entailment | all_nli, wanli_en, scitail_en |
| `paraphrase_duplicate` | positive | gold label 1 (duplicate or paraphrase) | quora_duplicates, mrpc_en, paws, paws_swap_en |
| `adjacent_sentences` | positive | two consecutive sentences of one paragraph, 6 to 60 words each, one pair per passage, first 150,000 passages of the source | wikipedia_en, cc_news_en, openwebtext_en, gutenberg_en |
| `contradiction` | negative | gold label contradiction | all_nli, wanli_en |
| `paws_non_paraphrase` | negative | PAWS gold label 0 (same words, different meaning) | paws, paws_swap_en |
| `order_swapped` | negative | the adjacent pair in reverse order | same passages as `adjacent_sentences` |

Left out on purpose: neutral NLI (not a similarity relation), ANLI and FEVER (premises are paragraphs or
evidence, not sentences), Quora non-duplicates (topical negatives, not hard), PAWS unlabeled (model labels),
VitaminC (enters at T203).

Pairs are deduplicated across sources (order-free key; `order_swapped` has its own ordered key so it never
collides with its adjacent pair), and a pair whose two sentences normalise equal is dropped.

## Leakage rescan

A pair is dropped when either sentence has a normalised exact match in STS-B validation or test (5,758
gate sentences) or shares an eight-word window with one. The written file is then rescanned by an
independent implementation (word tuples instead of hashes):

| | Pairs checked | Exact hits | Eight-word window hits |
|---|---|---|---|
| Output file | 1,410,056 | **0** | **0** |

Dropped by the guard: exact 3,704 rows (all_nli 3,440, mrpc_en 260, wanli_en 4), eight-word window 710
(all_nli 630, mrpc_en 46, openwebtext_en 22, wanli_en 8, cc_news_en 2, wikipedia_en 2). MRPC lost 306 of
3,510 positives, in line with the T193 finding that STS-B sentences sit inside MRPC and all_nli.

## Rows

| Relation | Rows |
|---|---|
| entailment | 355,695 |
| contradiction | 326,630 |
| paraphrase_duplicate | 149,525 |
| paws_non_paraphrase | 54,843 |
| adjacent_sentences | 261,677 |
| order_swapped | 261,686 |
| **positive / negative** | **766,897 / 643,159** |

Per source and relation (candidates, each drop reason and kept) are in the JSON `by_source_relation`.

## Findings for T198 and T203

1. **`order_swapped` is order-only.** Both orders hold the same two sentences, so a symmetric bi-encoder
   (mean-pooled, same tower) cannot separate it. The rows carry `symmetric: false`; T198 should use them
   only for an order-aware head or leave them out of the in-batch InfoNCE. This is a property of the
   spec rule, not a defect.
2. **Adjacent supply is uneven.** 150,000 passages gave 110,826 Wikipedia pairs and 141,618 OpenWebText
   pairs but only 7,795 cc_news and 3,136 Gutenberg pairs (multi-line paragraphs are skipped so a pair never
   crosses a heading or a list). Wikipedia and OpenWebText are 96 % of the adjacent pairs.
3. **Positives are topical, not graded.** NLI entailment pairs are short-hypothesis rewrites and adjacent
   sentences are context, so the pool will not reproduce STS-B score gradations; the graded pairs still
   calibrate the scale and bias of the head (T198). Whether the pool helps is unmeasured until T205.
4. The earlier open point (extra similarity label mean 0.628 above STS-B validation 0.473) is not
   addressed by this pool: its rows have no score.

## Checks

`ruff check`, `ruff format --check` and `mypy` on the new script pass; the 10 fixture tests pass.
