# T95 — Stage-1 gate audit (G01-G12)

Date: 2026-11-13 · Sources: `reports/language_encoder/foundation-readiness.json`, `foundation-qualification.json`,
`answer-text-validation-sample.json`, `reports/tokenizer/fertility.json` and `foundation-f07.json`,
`reports/retrieval/foundation*.json`. Nothing was executed; no model or tokenizer was loaded. **The foundation model is
NOT QUALIFIED.**

Status vocabulary: *measured* = a value with a valid protocol exists; *validation-only* = value from the `val` split,
not evidence for a gate; *NOT VERIFIED* = value exists but the protocol or provenance is missing; *missing* = no value.

| Gate | Metric (threshold) | Latest evidence | Status | Protocol / evaluator support |
|---|---|---|---|---|
| G01 | ANLI macro F1 >= 0.85 | 0.404 (val, F04) | validation-only, below gate | evaluator emits `macro_f1`; held-out run missing |
| G02 | ViNLI macro F1 >= 0.78 | 0.538 (val) | validation-only, below gate | as G01 |
| G03 | PAWS accuracy >= 0.88 | 0.696 (val) | validation-only, below gate | evaluator emits `accuracy` |
| G04 | PAWS macro F1 >= 0.88 | none in the F04 report | missing | evaluator now emits `macro_f1` for paraphrase (`test_paraphrase_macro_f1_is_not_positive_class_f1`); needs a new run |
| G05 | STS-B Spearman >= 0.82 | 0.770 (val); sampling diagnostic 0.832 | validation-only | STS-B train/test overlap to fix in T96 |
| G06 | SQuAD EM >= 0.72 | 0.4755 token-span protocol (val); 0.67 answer-text on a 300-sample validation sample | NOT VERIFIED in the readiness report (protocol `token_span`) | normalized-answer-text protocol implemented (`QA_PROTOCOL_VERSION`); needs a run that records it |
| G07 | SQuAD F1 >= 0.83 | 0.6705 token-span (val); 0.761 answer-text sample | NOT VERIFIED | as G06 |
| G08 | ViQuAD EM >= 0.65 | 0.353 token-span (val) | NOT VERIFIED | as G06; ViQuAD offsets fixed in T96 |
| G09 | ViQuAD F1 >= 0.78 | 0.419 token-span (val) | NOT VERIFIED | as G08 |
| G10 | EN fertility <= 1.35 | 1.420 macro (pooled 1.531, worst source 1.543), test split, unseen text, tokenizer `203a85cf` | measured; **FAIL** under the current tokenizer | `benchmarks/fertility.py` implements `unseen_text_tokens_per_word` |
| G11 | VI fertility <= 1.35 | 1.363 macro (pooled 1.325, worst 1.417) | measured; **FAIL** marginally | as G10 |
| G12 | STEM retrieval MRR >= 0.82 and > BM25 | dense MRR 0.034 vs BM25 0.783 on paragraph retrieval; SciFact dev 0.012 vs 0.636 (diagnostics, not gate-eligible) | no gate-eligible human STEM relevance (T98); diagnostics fail | `benchmarks/retrieval.py` implements `held_out_query_relevance` with the BM25 baseline |

Findings:
1. All twelve gates still lack encoder evidence on the held-out test split; the F04/F06 reports are validation or
   diagnostic only and the readiness check correctly rejects them (`val` is not held-out test evidence, no manifest
   identity, no split-isolation record).
2. The three protocols named in the task already have evaluator support in the code: PAWS macro F1, normalized-answer QA
   (answer-text protocol, recorded only when the result carries its provenance) and unseen-text fertility. The gap is
   measurement, not code. No evaluator change was needed.
3. Only G10 and G11 have test-split measurements; both are above 1.35 with the current tokenizer, so tokenizer R1 (T97)
   is a prerequisite, not an option.
4. Readiness rejects seeded faulty reports (`tests/unit/language/test_readiness.py`): validation or train split, missing,
   NaN, infinite or boolean metric, out-of-range score, duplicate measurements, empty or fractional sample count,
   missing or equal baseline, missing manifest identity or split-isolation record, a QA report with the token-span
   protocol, reports from different checkpoints and a partial gate config. T95 added two cases for the protocols the audit
   named: a fertility report with a different protocol and a PAWS report without macro F1.
