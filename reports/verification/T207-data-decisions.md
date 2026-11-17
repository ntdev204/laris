# T207 — Data decisions before the T202 profile

Implemented 2026-11-17. Reads data and writes files only: no training, no backward step, no tokenizer fit. Owner order 2026-11-17:
"similarity should get more data; for the rest choose the most suitable route". Raw numbers: `T207-mixture-shares.json`, `T207-vitaminc.json`.

## 1. Similarity: no derived graded scores
Measured on SICK (human relatedness mapped to [0, 1], split by the NLI class of the same pair; 4,439 train pairs):

| NLI class | pairs | mean relatedness | std |
|---|---|---|---|
| entailment | 1,274 | 0.892 | 0.087 |
| neutral | 2,524 | 0.491 | 0.234 |
| contradiction | 641 | 0.651 | 0.110 |

A class-constant score would (a) order the classes wrongly (contradiction above neutral: graded similarity is not agreement), (b) ignore a
within-class spread of 0.09 to 0.23, and (c) sit near 0.9 for the positive relations against an STS-B train mean of 0.54 (validation 0.473).
So pairs converted from the T197 relations are **not** added to the graded similarity task; they stay in `relation_pairs_en` for the contrastive
task (T199), where only the relation matters. More graded volume needs a grader: LLM scores with `label_source: llm` (D47), planned as T208 and
waiting for the owner's API key and budget. No public human-graded English set is left (STS12-16, SICK and STS Companion are in use; CxC is not on
HuggingFace; Twitter-URL on HuggingFace is binary).

## 2. Per-dataset sampling weights (new loader option)
`dataset_sampling_weights: {task: {dataset directory: factor}}` multiplies the `rows ** exponent` weight of a dataset, in the plain stream and in the
label-balanced sampler; validated (known task and directory, positive finite factor, train split only). Like the exponents it is applied only with
`--dataset-sampling-ablation`. Weights solved by `scripts/measure_mixture_shares.py` at exponent 0.7:

| task | rule | weight | before | after |
|---|---|---|---|---|
| qa | no-answer share back to the T193 target 0.132 (only SQuAD 2.0 at 0.340 and DuoRC at 0.128 have no-answer rows) | `squad_v2_en` 1.695 | 0.0996 | 0.132 (squad_v2_en share 0.224 -> 0.329) |
| paraphrase | model-labelled `paws_unlabeled_en` capped at 15 % of the task | 0.17 | 0.509 | 0.150 |
| nli | VitaminC (new, BIG-bench canary) at 10 % | `vitaminc_en` 0.375 | 0.228 | 0.100 |

Why this route: a per-source weight keeps the existing sources and restores the audited prior with one number; the alternative (a larger SQuAD 2.0
share through a second exponent) is the same effect with a rule the loader does not have. SQuAD v1 and v2 share paragraphs, so the larger SQuAD 2.0
share repeats contexts; that is a known cost, to be seen in the T205 per-source results.

## 3. VitaminC (owner decision 2026-11-16)
`scripts/build_vitaminc.py` wrote `data/processed/vitaminc_en/train.parquet`: 370,653 raw, 367,422 kept (entailment 183,308, contradiction 131,207,
neutral 52,907), 3,225 exact duplicates and the 6 claims equal to FEVER validation or test hypotheses removed; validation and test unused. The
directory is in `TASK_DATASET_DIRS["nli"]`; under label balancing each label is drawn a third of the time, so the 14 % neutral prior is not
the draw share. The canary record stays: a model trained with it is not evaluated on BIG-bench.

## Not done here
The mixture proper (task shares, floors, schedule) stays in T203. Nothing was profiled: T202 can now run on this data.
