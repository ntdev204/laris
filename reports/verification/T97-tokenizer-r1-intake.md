# T97 — Tokenizer R1: intake of the owner's fit

Date: 2026-11-13 · Check: `.venv/bin/python scripts/tokenizer_intake.py` (read-only; exit 0) · The agent fitted nothing in
this task. The fit itself was run on the owner's authorisation of 2026-11-11 (`reports/tokenizer/foundation-r1-candidates.json`).

Candidate: `artifacts/tokenizer/foundation-r1-super/candidate/laris_spm_48k_r1.model` (owner choice B: 48k vocabulary,
digits not split; fitted with `laris train tokenizer --authorized --vocab-size 48000 --no-split-digits`, train split only,
112 s, peak 5.7 GiB RSS).

## Intake result: all checks pass

| Check | Result |
|---|---|
| SHA-256 of model, vocabulary, contract, locked development sample, fit corpus equal the report | pass |
| Vocabulary size 48,000; contract `token_to_id` equals the model piece by piece | pass, 0 differences |
| Special tokens `[PAD] [UNK] [CLS] [SEP] [MASK] [MATH] [GREEK] [UNIT]` keep ids 0-7 of the 32k contract | pass |
| Token and unknown counts on the four development sources recomputed | equal to the report |
| Macro fertility on the development sample (mean of per-source tokens/words) | EN 1.2996, VI 1.1848; both <= 1.35 (margins 0.050 and 0.165); equal to the report |
| Unknown-token rate on the development sample | EN wiki 0.69 %, EN NLI 0.004 %, VI wiki 0.27 %, VI CC100 0.83 % (reported; VI CC100 and EN wiki are the ones to watch) |

## Lineage review (the vocabulary changed)

- Token ids and vocabulary size changed, so no 32k checkpoint can be reused: the encoder must be re-initialised.
  `configs/language_encoder/compact_r1.yaml` already sets `vocab_size: 48000` (warmup 1000, 10,000 steps); the embedding
  grows from about 24.6 M to about 36.9 M parameters (*estimate*: 48,000 × 768), so the memory profile of T99 must be
  redone.
- The fit used only the train partitions of WIKIPEDIA-EN, ALL-NLI, WIKIPEDIA-VI and CC100-VI-CLEAN, none of which T96
  changed (T96 touched STS-B and ViQuAD only), so the r1 data revision does not alter the tokenizer lineage.
- Previously measured fertility (G10 1.420, G11 1.363 with the 32k tokenizer) no longer describes the candidate. The
  candidate's numbers are development-sample only; G10 and G11 are measured once on the held-out sources at T100
  (`python -m language.benchmarks.fertility`, runbook section 5b) and the development margin for EN is only 0.05.
- Digits are not split: numeric tokens in scientific text are longer; the owner took that trade-off on 2026-11-11.

## Owner commands for the remaining steps (nothing here is run by the agent)

1. Nothing more to fit: the candidate is accepted for T99 once the owner confirms this intake.
2. T99 training, with the 48k config and a new profile, are prepared in T99. Do not use `--init-from` with a 32k checkpoint.
3. Held-out fertility (T100, inference only, once): the command of runbook section 5b with
   `--tokenizer-model artifacts/tokenizer/foundation-r1-super/candidate/laris_spm_48k_r1.model`.

Status of the foundation model: NOT QUALIFIED.
