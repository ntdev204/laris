# T208 — Graded similarity labels from an LLM grader (D47)

2026-11-17. Grader: Claude Sonnet subagents of the working session, blind shards of 150 pairs (`id`, `sentence1`, `sentence2` only; no source,
relation or overlap), STS rubric 0-5 in steps of 0.5, judged by reading, no code. No training, no model weights. Tool: `scripts/llm_similarity.py`;
raw numbers `T208-calibration.json`, `T208-graded-pairs.json`; fixture tests `tests/unit/language/test_llm_similarity.py`.

## Calibration (before any new row was used)
300 random STS-B **train** pairs graded blind: **Spearman 0.914** against the human scores, mean absolute error 0.099 (on the [0, 1] scale), mean 0.543
against 0.505 (the grader leans 0.04 high). Caveat: STS-B is public and may be known to the grader, so 0.914 is an upper estimate on unseen pairs.

## New pairs
`select` drew candidates from the T197 relation pairs (entailment, paraphrase_duplicate, contradiction, paws_non_paraphrase, adjacent_sentences) and
neutral all_nli pairs, 3 to 60 words, equal-count bins of word overlap (Jaccard) so the scores spread, leakage-guarded against STS-B validation and test
(exact and eight-word window), duplicates removed: 6,000 pairs in 40 shards. **3,000 were graded** (shards 000-019, in random order); shards 020-039 are
prepared and ungraded, to be graded if T205 shows the extra rows help.

`data/processed/similarity_llm_en/train.parquet` (outside Git): 3,000 rows, columns `sentence1`, `sentence2`, `score` ([0, 1]), `source` (`llm:<origin>`),
`label_source: llm`. Leakage rescan (second implementation): 0 exact, 0 window hits. Label mean **0.526** (STS-B train 0.54, validation 0.473), std 0.252;
histogram in half points 0: 39, 0.5: 198, 1: 314, 1.5: 294, 2: 311, 2.5: 355, 3: 391, 3.5: 436, 4: 364, 4.5: 231, 5: 67.

Mean score per origin relation: paraphrase_duplicate 0.756, entailment 0.698, paws_non_paraphrase 0.543, neutral 0.492, adjacent_sentences 0.284,
contradiction 0.232. This is the measurement that makes class-constant derived scores wrong (SICK's contradiction mean is 0.651; all_nli contradictions are
far less similar), and shows why the graded rows need a grader.

## Use and limits
- In `TASK_DATASET_DIRS["similarity"]` (train only, no validation split). The share against `stsb` (5,734) and `sts_extra_en` (14,429) is a T203 decision;
  the rows are 3,000 of about 23,000 (13 %) at plain row counts.
- Reports that use them say `label_source: llm`; they are never human similarity data. STS-B validation and test stay the only gate data (G05).
- One grader, one pass: no inter-grader agreement was measured. A second pass over a sample (for example 300 pairs) would give one.
