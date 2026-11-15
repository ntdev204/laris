# T193: pair-task data audit (counts only)

Measured 2026-11-15 by `scripts/audit_pair_data.py`. All figures come from
`reports/verification/T193-pair-data-audit.json`; the JSON key for each figure is given in brackets.
Scope: the full splits of every pair-task source the loader feeds today (`TASK_DATASET_DIRS`, status `in_mixture`), the
raw candidate sources from T192 (status `candidate`, not partitioned, not in the mixture) and the train and validation
MLM shards. Token lengths use the pilot-2 tokenizer `artifacts/tokenizer/english-r1-56k-nd/laris_spm_en_56k_nd.model`
(sha256 `3cbb017c…`); it was used for encoding only. Nothing was trained. There was no tokenizer fit, no backward step and
no optimizer. The sealed test splits were only read to count overlap and label priors. The foundation model is
**NOT QUALIFIED**. This report is about data and says nothing about model capability.

Rules the counts follow:
- Cut shares use the loader's `build_sequence` rule. The first segment is cut at (L - 3) // 2 tokens and the second
  segment gets what is left. L is 1,024 (the `english_r1` `max_sequence_length`) and 512.
- QA windows follow `_locate_answer_span`.
- Pair keys are normalised: lower case, letters and digits only. NLI and QA keys are ordered. Paraphrase and
  similarity keys are unordered.
- "Held-out" means the val and test splits of the in-mixture sources of the same task.

## 1. Defects found (they change what the later tasks must do)

1. **More than half of `sts_extra_en` has the wrong similarity label.** The table has 14,429 rows. 8,389 of them come
   from SICK-EN (58 %), and their scores take only the values 0.0, 0.2 and 0.4 (2,356 / 4,824 / 1,209 rows). These are
   the SICK NLI class (`label`: 0 entailment, 1 neutral, 2 contradiction) divided by 5, not `relatedness_score`.
   - Cause: `scripts/check_sts_leakage.py` tries `SCORE_KEYS = ("score", "label", "relatedness_score")` in order, so
     for SICK it finds `label` first.
   - Effect: the label is inverted, since an entailment pair gets similarity 0.0. The SICK rows have a word-overlap
     Spearman of -0.136, against +0.566 for STS Companion and +0.499 for STS12 train (measured on the table by source).
     The whole table therefore reads mean 0.358 and overlap Spearman 0.014
     [`tasks.similarity.sources.sts_extra_en.train.label`, `.word_overlap_spearman`].
   - The clean similarity training pool is STS-B train 5,734 + STS Companion 5,237 + STS12 train 803 = **11,774
     rows**, not 20,163.
   - This corrects two earlier figures. The T191 reading "training label mean 0.624" and the T193 plan note "label mean
     0.54 to 0.62" both came from the first rows of the table, which are STS Companion.
   - The defect also makes the similarity loss of every run since T175 partly train against the gate direction. That is
     one more explanation for the STS-B Spearman of 0.046 in pilot 2, and one the T191 diagnosis could not see.
2. **SQuAD 2.0 held-out data is largely in SQuAD v1 training data.**
   - 9,280 rows of `squad/train` are exact (question, context) matches in `squad_v2_en` held-out: 5,698 in val and 3,582
     in test [`tasks.qa.overlap["squad/train"]`]. Seen from the other side, 5,690 of 7,576 `squad_v2_en/val` rows (75 %)
     and 3,578 of 5,163 test rows (69 %) appear in another QA source.
   - Cause: SQuAD 2.0 contains the SQuAD 1.1 questions. The partitioner guards SQuAD v1 held-out against v2 training
     (`squad_v1_heldout_keys`) but not the reverse.
   - In addition, 77,591 `squad_v2_en/train` rows duplicate SQuAD v1 rows, so these questions are trained twice.
   - Consequence: any QA figure measured on `squad_v2_en` val or test is contaminated until the overlap is removed.
3. **VitaminC val and test contain the FEVER held-out claims.**
   - 2,008 VitaminC test rows and 1,887 VitaminC val rows are exact pairs from `fever` val or test.
   - Through `FEVER_id`, 7,808 VitaminC val rows carry a claim that is in processed FEVER val, and 6,892 a claim in
     processed FEVER test [`tasks.nli.vitaminc_fever`].
   - VitaminC train is clean against FEVER held-out: 0 exact pairs, 0 FEVER-id claims in FEVER val or test, and 6
     VitaminC claim texts (normalised) in FEVER val.
   - VitaminC train does overlap FEVER train: 93,136 rows carry a FEVER-train claim and 11,602 are exact pairs with
     another source.
   - So only VitaminC train is usable for training, and the 6 claim-level hits must be dropped.
4. **Some Quoref offsets are wrong.** 462 train rows (2.4 %) and 53 val rows have an `answer_start` that does not point
   at the answer text [`bad_offset`]. The loader raises on such rows, so T200 needs a formatter rule before Quoref can
   enter.
5. **The FEVER label prior shifts between splits.** Train is 74.7 % entailment and 25.3 % contradiction. Val is
   52.8 / 47.2 and test 52.4 / 47.6. The processed FEVER val and test follow the balanced labelled dev, train follows the
   raw train. FEVER has no neutral class.

## 2. Label priors (full splits)

NLI [`label_prior`], train split unless noted:

| Source | Rows | Entailment | Neutral | Contradiction | Note |
|---|---|---|---|---|---|
| all_nli | 942,068 | 0.334 | 0.333 | 0.333 | balanced |
| anli | 162,864 | 0.320 | 0.422 | 0.258 | val and test balanced (0.33 each) |
| fever | 77,139 | 0.747 | none | 0.253 | val 0.528 / 0.472 |
| wanli_en | 97,067 | 0.374 | 0.477 | 0.150 | same in val and test |
| scitail_en | 24,332 | 0.372 | 0.628 | none | two classes only |
| vitaminc_en (candidate) | 370,653 | 0.501 | 0.143 | 0.356 | val and test the same |

Paraphrase, share of label 1: PAWS 0.442, Quora 0.375 (val 0.350), MRPC 0.671, PAWS swap 0.096 (candidate), PAWS
unlabeled 0.500 (candidate, labels assigned by a model).

Similarity (0 to 1): STS-B train mean 0.540 (val 0.473, test 0.522), `sts_extra_en` 0.358 (defect 1).

QA, unanswerable share: SQuAD 2.0 train 0.340 (val 0.249, test 0.307). SQuAD, HotpotQA, AdversarialQA and Quoref have
none. DuoRC ParaphraseRC 0.155, DuoRC SelfRC 0.010. ROPES test has no answers at all (1.0), so it is unlabelled.

## 3. Shortcut baselines (counting, no neural model)

Paraphrase, AUC of word-set Jaccard against the label (train / val) [`word_overlap_auc`]:

| Source | Train | Val |
|---|---|---|
| PAWS | 0.496 | 0.501 |
| Quora | 0.721 | 0.724 |
| MRPC | 0.759 | 0.746 |

PAWS swap scores 0.497 and PAWS unlabeled 0.500. In PAWS unlabeled every negative has Jaccard of at least 0.5, and in a
20,000-row sample of all its rows the 5th percentile was 0.81, so word overlap carries no signal there. PAWS is the only paraphrase source
where overlap gives nothing, which matches the T191 finding: the pilot head reached 0.505 on PAWS and 0.651 on Quora,
below the overlap baseline on Quora as well.

Similarity, Spearman of Jaccard against the score [`word_overlap_spearman`]: STS-B train 0.588, val 0.653, test 0.565.
Pilot 2 reached 0.046 on STS-B validation.

NLI, validation split, accuracy / macro F1 [`baselines_mixture`]:

| Source | Majority class of the source | Hypothesis only, own source | Hypothesis only, pooled |
|---|---|---|---|
| all_nli | 0.346 / 0.172 | 0.555 / 0.555 | 0.529 / 0.527 |
| anli | 0.334 / 0.167 | 0.373 / 0.366 | 0.322 / 0.307 |
| fever | 0.528 / 0.231 | 0.687 / 0.455 | 0.567 / 0.368 |
| wanli_en | 0.474 / 0.214 | 0.475 / 0.389 | 0.416 / 0.349 |
| scitail_en | 0.617 / 0.254 | 0.779 / 0.514 | 0.751 / 0.487 |
| pooled (33,900 rows) | 0.399 / 0.308 | 0.550 / 0.550 | 0.505 / 0.504 |

"Hypothesis only" is a multinomial naive Bayes on word unigrams of the hypothesis, fitted by counting on the train split.

- Pilot 2 measured NLI macro F1 0.285 (T191). That is below the source-majority baseline (0.308) and far below a
  hypothesis-only word count (0.504).
- With VitaminC added, the pooled hypothesis-only macro F1 drops to 0.430. On VitaminC itself it is 0.409, against a
  majority macro F1 of 0.222 [`baselines_with_vitaminc`]. VitaminC's contrastive revision pairs make the hypothesis cue
  weaker.
- Negation words (not, no, never, ...) [`negation_cue`]:
  - all_nli: in 7.6 % of hypotheses; 65.1 % of those rows are contradiction.
  - FEVER: in 5.4 % of train hypotheses; 81.5 % are contradiction (88.8 % in val).
  - ANLI val: 22.9 % contradiction, so the cue is reversed there.
  - VitaminC: in 1.0 % of hypotheses; 30.3 % contradiction, so no cue.
- SciTail is the strongest artefact. 19,379 of its 24,332 training rows (80 %) share their hypothesis with a held-out
  row, because one hypothesis is paired with many premises and the split is by pair hash
  [`overlap["scitail_en/train"].segment_rows_in_held_out`].

QA [`window`]:
- Share of rows the loader trains on the `[CLS]` "no answer" position at L = 1,024 (unanswerable, answer not found or
  outside the window):
  - In the mixture: SQuAD 0.0, HotpotQA 0.0, AdversarialQA 0.0, SQuAD 2.0 0.340 (only its true unanswerables).
  - Candidates: Quoref 0.024, ROPES 0.117, DROP 0.285, DuoRC SelfRC 0.459, DuoRC ParaphraseRC 0.621.
- Rows whose answer lies outside the window:
  - At 1,024: at most 0.05 % in the mixture sources, and 4.3 % in DuoRC ParaphraseRC.
  - At 512: 3.3 % in Quoref, 10.9 % in DuoRC ParaphraseRC, at most 0.1 % elsewhere.
- Answer text not found verbatim in the context:
  - DROP 22,007 of 77,400 rows (numbers and dates).
  - DuoRC ParaphraseRC 29,405 of 69,524. DuoRC SelfRC 26,596 of 60,721.
  - ROPES 1,277 of 10,924. In all of these ROPES rows the answer is found only in the question, for example "Which
    cup ...? cup B".
- The empty-answer F1 baseline equals the unanswerable share. For SQuAD 2.0 val it is 0.249.

## 4. Truncation

Pair inputs are short, so truncation does not explain the pair-task failure.
- NLI, paraphrase and similarity are cut at 1,024 in at most 0.01 % of rows (FEVER, VitaminC) and at 512 in at most
  0.07 % [`cut`].
- 95th-percentile tokens:
  - Premises: all_nli 42, ANLI 112, FEVER 71, VitaminC 70.
  - Hypotheses: 18 to 27.
  - Paraphrase sentences: 27 to 36.
- QA contexts:
  - HotpotQA: median 1,202 tokens. 77.4 % of training contexts are cut at 1,024, but no answer is lost, because the
    gold span sits early.
  - DuoRC ParaphraseRC: median 1,145, p95 4,164. 58.9 % of contexts are cut.
  - DuoRC SelfRC: 25.4 % cut.

## 5. Duplicates and held-out overlap (exact rows)

Exact pairs from a training split that appear in a held-out split [`overlap`]:

| Source | Rows |
|---|---|
| all_nli | 28 |
| scitail_en | 32 |
| wanli_en | 5 |
| Quora | 30 |
| MRPC | 6 |
| STS-B (official split) | 10 |
| SQuAD | 9,280 (defect 2) |
| anli, fever, paws, hotpotqa, adversarial_qa | 0 |

Candidates against current held-out data:
- PAWS unlabeled train: 751 rows (422 in PAWS val, 329 in PAWS test). They must be removed before use.
- VitaminC val and test: see defect 3.
- PAWS swap, Quoref, ROPES, DROP, DuoRC: 0.

Segment-level overlap with held-out (training rows whose premise, hypothesis, question or context also occurs in
held-out):
- ANLI premise: 69,384 of 162,864 rows. Rounds reuse contexts.
- all_nli premise 868, hypothesis 31,191 (short generic hypotheses).
- SciTail hypothesis 19,379 (section 3).
- SQuAD question 9,294, context 10,626.
- SQuAD 2.0 context 2,068.
- AdversarialQA context 2,862.

Duplicate rows within a training split: all_nli 961, FEVER 4,395, VitaminC 3,404, PAWS unlabeled 2,294, DROP 3,206,
Quora 996.

STS-B validation and test sentences (5,378 distinct sentences) found in other pair sources, by row
[`stsb_heldout_sentence_overlap`]:
- all_nli: train 4,487, val 51, test 54.
- MRPC: train 571, val 32, test 31.
- wanli_en train 14, Quora train 6.
- 0 in ANLI, FEVER, SciTail, PAWS, `sts_extra_en`, VitaminC, PAWS swap and PAWS unlabeled.

None of these rows carries an STS-B score, so they do not leak the G05 label today. They must be filtered before T197
turns NLI or paraphrase pairs into similarity pairs.

## 6. Supply for the new objectives

MLM shards, train / val [`mlm`], summed over the ten MLM sources:

| Measure | Train | Val |
|---|---|---|
| Passages | 15,500,570 | 158,260 |
| Documents | 10,170,378 | 103,436 |
| Documents with at least two passages | 2,122,635 | 21,685 |
| Consecutive passage pairs (`doc#k`, `doc#k+1`) | 5,330,192 | 54,824 |
| Passages with at least two sentences | 15,334,231 | 156,544 |
| Adjacent sentence pairs inside a passage | 315,030,470 | 3,204,316 |
| Passages with at least two paragraphs | 10,360,741 | 105,962 |

Notes on the MLM counts:
- Consecutive passage pairs by source (train): FineWeb-Edu 2,403,271, Gutenberg 1,194,347, OpenWebText 879,149, C4
  563,394.
- `wikipedia_en` rows are whole articles without `#k` passage numbers, so they add 0 consecutive passage pairs. 1,972,159
  of them have at least two paragraphs.
- Passages of every document are stored contiguously and stay in the document's split
  (`documents_contiguous: true` everywhere).
- T194 therefore has about 5.3 M cross-passage pairs and, inside a single passage, two segments for 99 % of the 15.5 M
  passages. Sentence boundaries are counted by a regular expression, so the sentence figures are approximate.

NLI and paraphrase pairs for T197, training splits [`supply`]:

| Source | Entailment positives | Contradiction negatives | Premises with both an entailment and a contradiction |
|---|---|---|---|
| all_nli | 314,314 | 314,090 | 276,973 |
| VitaminC (candidate) | 185,714 | 131,958 | 102,219 |
| ANLI | 52,110 | 41,965 | 7,558 |
| FEVER | 57,592 | 19,547 | 5,860 |
| WANLI | 36,250 | 14,559 | 36 |
| SciTail | 9,056 | 0 | 0 |

Paraphrase:

| Source | Positives | Negatives | Negatives with Jaccard ≥ 0.5 |
|---|---|---|---|
| Quora | 124,002 | 206,350 | 45,707 |
| PAWS | 21,829 | 27,572 | 27,567 |
| PAWS swap (candidate) | 2,930 | 27,467 | 27,458 |
| PAWS unlabeled (candidate, model labels) | 322,826 | 322,826 | 322,826 |
| MRPC | 3,510 | 1,724 | 512 |

## 7. What this means for the next tasks (proposals, not decisions)

- **Similarity (T197 to T199):** first rebuild `sts_extra_en` with SICK `relatedness_score` (1 to 5, scaled by 5), or
  drop SICK. This is a data correction, not training, and it needs the owner's choice because SICK is
  NEEDS_LICENSE_REVIEW (CC-BY-NC-SA-3.0). Relation pairs must exclude the 4,487 all_nli and 571 MRPC training rows that
  contain an STS-B held-out sentence.
- **QA (T200):**
  - Remove the 9,280 SQuAD v1 training rows that are in SQuAD 2.0 held-out, or re-split SQuAD 2.0 against SQuAD v1, before
    any QA figure on `squad_v2_en` is reported.
  - DuoRC ParaphraseRC would put 62 % of its rows on the no-answer position, and DROP 28 %. Neither is a good extractive
    source without a formatter.
  - Quoref needs a rule for its 2.4 % bad offsets. ROPES test is unlabelled.
- **NLI (T196):**
  - Balance by source and label. The source prior alone gives macro F1 0.308, and a hypothesis-only word count gives
    0.504, so the head must beat 0.504 before it shows any use of the premise.
  - Use VitaminC train only, minus the 6 claim hits.
  - SciTail's shared hypotheses make its validation a weak test.
- **Paraphrase (T196, T200):** PAWS and PAWS unlabeled are the only sources where overlap carries no signal. Drop the
  751 overlapping rows from PAWS unlabeled, and keep `label_source: model`.

## 8. Limits

- Counts only. Overlap uses exact matches after normalisation, so near-duplicates and paraphrased leaks are not counted.
- Sentence boundaries come from a regular expression.
- For sources without offsets (ROPES, DROP, DuoRC), the first verbatim occurrence of the answer is taken as its span.
- The naive Bayes baselines are counting models fitted on the training splits and scored on validation. They are a
  lower bound for shortcut strength, not an upper bound.

Reproduce:
`HOME=$(mktemp -d) .venv/bin/python -I scripts/audit_pair_data.py --tokenizer artifacts/tokenizer/english-r1-56k-nd/laris_spm_en_56k_nd.model --out reports/verification/T193-pair-data-audit.json`
(about 10 minutes on 20 cores). Tests: `tests/unit/scripts/test_audit_pair_data.py`.
