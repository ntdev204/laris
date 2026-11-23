# T286 — Prompt filter before the brain

Date measured: 2026-11-23 and 2026-11-24. Measured by LARIS on this machine (RTX 5070 Ti, 16 GB). Development splits
only; no sealed file was read. The model (Qwen3.5-4B) and the system are **NOT QUALIFIED**: these are development
numbers, not gate results. Item text is not reproduced here; run records hold rules, counts and the language, never
the prompt.

## What the filter is

`laris.research.stem.prompt_filter`, rules and thresholds in `configs/prompt-filter.json` (SHA-256 `c6732ed5…`), section
`harness.filter` of `configs/stem-benchmarks.json`. Every prompt passes it before retrieval, the router and the model
(`scripts/stem_benchmarks.py harness`; `--no-filter` skips it). Deterministic and model-free; it never answers and is
never handed the gold answer.

1. **Normalise** the text handed on, each change counted under its rule: Unicode NFC (`unicode_form`), zero-width
   characters (`zero_width`), odd spaces (`odd_spaces`), runs of spaces and blank lines (`whitespace`), `\dfrac`/`\tfrac`
   (`latex_dfrac`), a doubled `$$` before a unit (`latex_double_dollar_join`).
2. **Match** on a folded view only (NFKC, case folded, look-alikes mapped, whitespace folded) and on a "despaced" view
   (letters spelt one by one joined); the views are never handed on.
3. **Injection** stops: the owner's Prefilter rules of kinds `injection` and `refusal`, read unchanged from
   `.laris/prefilter.toml` (`policy:<id>`), then 20 profile rules (`injection:<id>`).
4. **Scope** stops (SR-H10 and the profile): empty, symbol-only, a bare URL, the policy's greeting/help/version rules
   and hard rules (chit-chat, creative writing, identity, personal advice, opinion) at once; gibberish and soft rules
   (politics, translation, small talk, recommendations, travel) only when the prompt has no STEM signal (options, a
   mathematical symbol, a STEM word, a quantity with a unit).
5. **Fields**: language, quantities (value and unit), chemical formulas, element names, named constants.
6. **Cross-check** (`harness.formalisation_check`): each number of a verified solver call is grounded when it equals a
   given quantity, one scaled by a unit prefix or time factor, or a configured free value. `record` notes it;
   `gate` would treat a call with an ungrounded number as unverified. The run used `record`.

## The labelled fixtures

Two separate agents labelled them, neither of which saw the rules (owner's choice of 2026-11-23, "independent
subagent"); the second also did not see the first fixture.

| Fixture | Items | Stop labels | Pass labels | Quantity sample |
|---|---|---|---|---|
| `tests/fixtures/prompt_filter/` (first, SHA-256 `de835373…`, `0f3d9913…`) | 220 | 80 injection (40 alone, 40 embedded), 60 out of scope | 80 hard negatives | 40 MMLU-Pro dev items (positions 0-39 by SHA-256 of id), 116 quantities |
| `tests/fixtures/prompt_filter/heldout/` (second, `54260f28…`, `af0205d2…`) | 160 | 60 injection (30 alone, 30 embedded), 40 out of scope | 60 hard negatives | 40 items (positions 40-79), 102 quantities |

Hard negatives are genuine STEM questions with trap words (ignore, previous, system, prompt, translate, hello…),
other languages, LaTeX and odd whitespace. The development benchmark items (1,925) are `pass` by construction.

## Result

Command: `python scripts/stem_benchmarks.py filter-eval [--fixture DIR] [--run NAME]`.

| Rules | Measured on | Stop precision | Stop recall | Wrong class | False stops (hard negatives) | False stops (dev, 1,925) | Quantity P / R | Unit right of matched |
|---|---|---|---|---|---|---|---|---|
| first version, written before the fixture was read | first fixture | 1.000 (96/96) | 0.686 (96/140) | 0 | 0 / 80 | 0 | 0.758 / 0.862 | 85 / 100 |
| tuned on the first fixture's misses | first fixture (fitted) | 1.000 | 1.000 (140/140) | 0 | 0 / 80 | 0 | 0.871 / 0.991 | 110 / 115 |
| **the same tuned rules, frozen** | **held-out fixture** | **0.957 (67/70)** | **0.670 (67/100)** | 0 | **3 / 60** | **0** | **0.933 / 0.961** | **77 / 98** |

By kind on the held-out set: injection alone 18/30 stopped, embedded 22/30, out of scope 27/40.

Reading:

- **The held-out row is the measurement.** Tuning on the first fixture's misses lifted it to 1.0 there but did not
  carry over: on prompts written by another reader, recall is 0.67, the level of the rules written blind. What gets
  through is paraphrase: indirect wording ("set aside whatever guidance you were given"), leetspeak, homoglyphs inside
  words, Vietnamese without diacritics, Chinese, persona play, questions about the assistant, jokes and stories asked
  without "write". A rule list cannot reach these; it is a cheap first line, and the shield, permission rules and
  sandbox stay the limits that matter (as `.laris/prefilter.toml` says of the Prefilter).
- **False stops**: 0 on all 1,925 development benchmark items (target 0, met) and 3 of 60 held-out hard negatives,
  all by soft rules on prompts with no STEM signal: a question opening with "Hi!", one with "What's your opinion:",
  one asking to translate a statement into first-order logic. They were not tuned away: a fix seen on the held-out set
  would no longer be held out.
- **Quantities**: precision 0.93 and recall 0.96 on unseen items; the unit is right for 77 of 98 matched values. Most
  unit misses are spellings the labeller kept as written (`kw`, `°K`, abbreviations) and composite units.

## The harness with and without the filter

Same items, engine, seeds and configuration as T278, filter on (`harness-filter-dev`, code `793704c2`, 2026-11-24;
records in `data/benchmarks/runs/`, outside Git) against T278 (`harness-dev`, code `d4fd67ea`, filter absent).

| Benchmark (dev) | Items | T278 | With filter | Wilson 95 % | Stops | Text changed | Model calls | s median | s p95 |
|---|---|---|---|---|---|---|---|---|---|
| MATH | 500 | 451 (90.2 %) | 455 (91.0 %) | 88.2-93.2 | 0 | 159 | 2.31 (2.30) | 67.4 (63.6) | 234.4 (238.8) |
| MMLU-Pro STEM | 1,175 | 986 (83.9 %) | 998 (84.9 %) | 82.8-86.9 | 0 | 61 | 1.93 (1.93) | 57.7 (57.7) | 247.3 (246.5) |
| GPQA (main − Diamond) | 250 | 150 (60.0 %) | 134 (53.6 %) | 47.4-59.7 | 0 | 34 | 2.02 (2.06) | 100.7 (109.7) | 274.6 (282.3) |

Model-free answers: 29, 0 wrong (B5 unchanged). Peak GPU memory 14.83 GB. The filter itself costs well under a
millisecond per item and no model call.

Paired by item, split by whether the filter changed the text (McNemar, exact):

| Benchmark | Text | Items | T278 → filter: wrong to right | right to wrong | p |
|---|---|---|---|---|---|
| MATH | changed | 159 | 11 | 5 | 0.21 |
| | unchanged | 341 | 7 | 9 | 0.80 |
| MMLU-Pro | changed | 61 | 4 | 0 | 0.13 |
| | unchanged | 1,114 | 35 | 27 | 0.37 |
| GPQA | changed | 34 | 1 | 7 | 0.07 |
| | unchanged | 216 | 13 | 23 | 0.13 |

Reading: **no difference is significant, and the largest move is on items the filter did not touch.** GPQA's
unchanged items, which got byte-identical prompts and seeds, moved 13 up and 23 down: that is the run-to-run variance
of the engine (vLLM batching), and it bounds what any single paired run can show. On GPQA the 34 changed prompts
differ only in whitespace (trailing spaces and double spaces); their 1 up and 7 down (p = 0.07) are within noise but
are noted for T280, which can repeat the run with `--no-filter` at the same revision to separate the two.

Cross-check of formalisations (`record`): checked on 241 / 414 / 33 verified solver calls (MATH / MMLU-Pro / GPQA);
30 / 154 / 11 had an ungrounded number, and 28 / 133 / 5 of those items were still right. `gate` would score
453 / 998 / 134, which is the same or worse (−2 on MATH). An ungrounded number is mostly a constant or a
conversion the model wrote correctly, so the check stays a recorded signal and is not used as a gate.

## Open for the owner

- The 3 held-out false stops come from soft rules; dropping the soft rules would trade them for missed stops of
  politics, translation and small talk. The profile's benchmark items are unaffected either way (0 false stops).
- A rule filter cannot catch paraphrased injection (recall 0.67 on unseen text). A stronger stage would need a
  learned classifier (owner's decision, SR-M3) and stays out of this task.
- Whether `.laris/prefilter.toml` should take any of the profile's rules: it was read, not changed.

The model and the system are **NOT QUALIFIED**.
