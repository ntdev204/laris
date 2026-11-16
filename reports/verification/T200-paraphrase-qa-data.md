# T200 — Paraphrase and QA data fixes

Measured 2026-11-16 by `scripts/build_qa_paraphrase_data.py` (tokenizer for encoding only; no training, no backward step,
no tokenizer fit). Raw numbers: `T200-paraphrase-qa-data.json`. Formatters: `src/laris/research/corpus/splits/partitioners/pair_sources.py`
(10 fixture tests in `tests/unit/language/test_pair_sources.py`).

## Policy
- Every new source is written as `train.parquet` only. A val or test file would enter the evaluator's gate averages (they weight
  datasets by rows), so none is written; the raw validation splits are untouched.
- A row is kept only when its answer can be pointed at in the context. A row that cannot is dropped and counted, never relabelled
  "no answer". The only unanswerable rows are DuoRC rows the source marks `no_answer`.
- Held-out guard (rule of T197: normalised exact match or an eight-word window): QA contexts against the val and test of squad,
  squad_v2_en, adversarial_qa_en and hotpotqa (6.24 M windows); paraphrase sentences against the val and test of paws,
  quora_duplicates, mrpc_en and stsb.

## QA
| source | raw | kept | answered | unanswerable | main drops |
|---|---|---|---|---|---|
| duorc_en (ParaphraseRC + SelfRC) | 130,245 | 87,173 | 75,995 | 11,178 (12.8 %) | answer not in plot 35,394; held-out overlap 1,938; answer outside the 1,024 window 5,740 |
| ropes_en | 10,924 | 9,650 | 9,650 | 0 | answer only in the question 1,252; overlap 22 |
| quoref_en | 19,399 | 17,392 | 17,392 | 0 | overlap 2,002; outside window 5; 395 wrong offsets repaired from the answer text |
| drop_en | 77,400 | 25,441 | 25,441 | 0 | not a span (number or date) 48,205; not in passage 863; overlap 2,886; outside window 5 |

- DuoRC is read on the train splits of both variants; answers are matched in the plot (exact, then ignoring case, with the text taken
  from the plot). ROPES context is situation then background. DROP keeps span answers only: a computed number found by chance in
  the passage would be a false label.
- Answer outside the 1,024-token window: the loader trains such a row on the no-answer position, so they were dropped
  (DuoRC 5,740, others 5 each). After that the share of rows on the no-answer position equals the true unanswerable share in every source.
- At 512 tokens, 15.3 % of DuoRC and 2.8 % of Quoref answers lie outside the window (relevant only if a run uses 512).
- Repeated answers (first occurrence used): DuoRC 40,717 of its kept answered rows before the window drop, ROPES 3,709, DROP 7,003.
  The offset may point at another occurrence of the same text; the answer text is right.

## Re-weighting against the audited target
Audit target (T193): the mixture's no-answer share. Pool of the four earlier sources at row weight 1: 0.132 (only SQuAD 2.0, 0.340 of its
train). With the new sources: 0.1156 (51,202 of 442,809 rows). Every lower `qa` sampling exponent lowers it further (0.9: 0.110, 0.7: 0.100,
0.5: 0.088), because the new sources are answered rows and only SQuAD 2.0 and DuoRC carry no-answer rows. The loader has one exponent per
task, no per-source weights, so this task cannot restore 0.132 without changing the loader's mixture rule: the choice (per-source weights or
a larger SQuAD 2.0 share) is passed to T203 with these figures. No row weight was changed here.

## Paraphrase (word-order sources)
| source | raw | kept | label 0 / 1 | `label_source` | drops |
|---|---|---|---|---|---|
| paws_swap_en | 30,397 | 30,220 | 27,308 / 2,912 | human | duplicate pair 2; held-out overlap 175 (window) |
| paws_unlabeled_en | 645,652 | 624,587 | 311,993 / 312,594 | **model** | duplicate pair 4,707; held-out overlap 16,358 (15,042 window, 1,316 exact) |

Duplicates are against each other and `paws/train`. The unlabeled labels come from a classifier: any report that uses them states
`label_source: model`. Both are in `TASK_DATASET_DIRS["paraphrase"]`; `paws_unlabeled_en` is 624 k rows against 49 k in `paws`, so at the
default exponent it dominates the task: T203 sets the exponent.

## Leakage rescan (independent code path: a second hash function for QA, word tuples without hashing for paraphrase)
QA contexts checked: duorc 9,551, ropes 1,361, quoref 3,436, drop 4,665 — 0 window hits. Paraphrase pairs: swap 30,220 and unlabeled 624,587 —
0 exact and 0 window hits.
