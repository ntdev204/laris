# T198: bi-encoder similarity head (forward-only measurement)

Measured 2026-11-16 on `artifacts/checkpoints/language_encoder/english-r1-pilot2/best` (step 2,000 of a stopped run),
forward passes only (no backward step, no optimizer, training authorization not enabled). STS-B **validation** only; the
sealed test split is not read. The foundation model is **NOT QUALIFIED**: this is the untrained head on a stopped pilot,
not a qualification result. Script `scripts/measure_bi_encoder_head.py`, data `T198-bi-encoder-head.json`.

## The head

`similarity_head: bi_encoder` (default `cross`, the unchanged pair-input linear head): score = sigmoid(scale x cosine(CLS_a,
CLS_b) + bias), each sentence run alone as `[CLS] s [SEP]`, the cosine in fp32. `scale` and `bias` are two learned scalars,
initial 10.0 and -7.5 (`similarity_initial_scale`, `similarity_initial_bias`; chosen so a cosine near the pilot's 0.74 mean maps
near the STS-B label mean 0.47, not tuned on data). They are built without drawing from the RNG, so the body of a seed is
identical for both heads; the cross `sim_head` stays in the model (unused in bi-encoder mode). Trainer, evaluator and
predictor call the same `bi_encoder_similarity`; the loader adds `sim_a_*` and `sim_b_*` single-sentence inputs to every
similarity batch. A cross checkpoint (pilot 2) loads into a bi-encoder model and keeps the initial scale and bias; a
`--init-from` check ignores the three head settings. Parameters: +2 for the bi-encoder (cross counts unchanged).

## STS-B validation (1,500 rows)

| Measure | Value |
|---|---|
| Spearman, all 1,500 rows | **0.494** |
| Spearman, first 600 rows (the T191 subset) | 0.572 (T191: 0.570, same cosine) |
| Cross head, T191 (600 rows) | 0.026 |
| Token Jaccard, T191 (600 rows) | 0.571 |
| Cosine mean / std | 0.817 / 0.142 |
| Score mean / std (label mean 0.473) | 0.641 / 0.255 |
| MSE to label (constant label mean: 0.090) | 0.114 |

Reading: the untrained head ranks STS-B at 0.49 to 0.57 depending on the subset, against 0.03 for the cross head, so the
contrastive objective of T199 starts from a usable ranking. Its scale and bias are not calibrated (score mean 0.64 against
0.47, MSE above the constant); calibration is the job of the graded STS pairs in T199. The 600-row number matches T191, the
full-validation number is lower: T191's 600 rows were the easier part of the split.

## T197 relation pairs (2,000 sampled per relation, seed 42, cosine)

| Relation | Polarity | Cosine mean (std) |
|---|---|---|
| paraphrase_duplicate | positive | 0.881 (0.102) |
| entailment | positive | 0.846 (0.107) |
| adjacent_sentences | positive | 0.697 (0.131) |
| contradiction | negative | 0.810 (0.120) |
| paws_non_paraphrase | negative | 0.970 (0.042) |
| order_swapped | negative | 0.690 (0.137) |

AUC (a positive scores above a negative):

| Positive | vs contradiction | vs paws_non_paraphrase |
|---|---|---|
| paraphrase_duplicate | 0.694 | 0.165 |
| entailment | 0.594 | 0.078 |
| adjacent_sentences | 0.243 | 0.009 |

Reading: (1) the body separates paraphrase from contradiction only weakly (0.69, entailment 0.59); (2) PAWS non-paraphrases
(same words, different order) get the highest cosine of all (0.970), so a bag-of-words-like embedding ranks them above true
paraphrases: the hard negative the contrastive objective has to move; (3) adjacent sentences sit lower than contradictions
because they share fewer words, so as positives they are a topical-relatedness signal that the weights of T199 must keep
apart from similarity; (4) `order_swapped` has the same two sentences as its adjacent pair and so the same cosine in a
symmetric head (0.690 against 0.697, sampling noise), as T197 predicted: it stays out of InfoNCE. The pooled positive against
negative AUC (0.297) mixes these and is not used as a decision number.

## Limits

One checkpoint, one seed, untrained head, derived (not graded) relation labels, a sample of 2,000 per relation. Nothing here
says what training will reach; the project's own number comes from T204.
