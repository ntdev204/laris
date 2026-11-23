# T278 — STEM router and harness: the evaluation profile on the development splits

Date measured: 2026-11-23. Measured by LARIS on this machine (RTX 5070 Ti, 16 GB). Development splits only; no sealed
file was read. This measures the **harness of the evaluation profile in Python** (ADR-026 section 4), not yet the
server pipeline (that is T284). The model (Qwen3.5-4B) and the system are **NOT QUALIFIED**: these are development
numbers, not gate results, and no sealed run took place. Item text is not reproduced here; records hold ids, classes,
steps, answers (a letter or a value) and cost.

## Set-up

| | |
|---|---|
| Code | revision `d4fd67ea` (`harness.py` SHA-256 `112d03fa…`, `router.py` `6598c684…`); scoring protocol `math-equiv-1` (`answers.py` `60f09b90…`), unchanged since T275 |
| Configuration | `configs/stem-benchmarks.json`, section `harness` (SHA-256 of the section `d6101f12…`) |
| Engine | vLLM 0.34.0, `Qwen/Qwen3.5-4B`, BF16, max length 20,480 (the T282 server), 64 items at once; thinking off with the T275 settings (temperature 0.7, top-p 0.8, top-k 20, 4,096 tokens); the draft of an item uses the same seed as T275 |
| Brain | snapshot `stem-t277-2`, SHA-256 `fb01dd03…ddeacb`, through `laris-server brain retrieve` (top 5, 600 characters each) |
| Solver | `laris.model.solver` (the `solve_stem` tool), 10 s and 2 GiB per call, at most 8 calls at once |
| Closed book | no web, no paper search; the only knowledge is the weights and the frozen snapshot |
| Command | `python scripts/stem_benchmarks.py harness --run harness-dev`; tables: `harness-report`; records in `data/benchmarks/runs/harness-dev.jsonl` (outside Git) |
| Comparison | `baseline-thinking_off.jsonl` of T275, the bare model on the same items |

What the harness does per item (`laris.research.stem.harness`):

1. **Router** (item shape only, never the gold answer): `computable` = an open answer (MATH) or at least half of
   the options hold a digit; else `knowledge` (question of at most 40 words) or `reasoning`.
2. **Model-free** (MATH): the strict patterns and solver of T276; a `verified` answer ends the item without the model.
3. **Notes** (knowledge, reasoning): five passages of the snapshot are put before the T275 prompt.
4. **Draft** with the T275 prompt; an unparsed or truncated draft is asked once more with "keep the reasoning short"
   and another seed.
5. **Formalisation** (computable): the model writes one solver call; mechanical repairs (`repair`: the formula of
   `name = formula`, renaming names the solver keeps such as `E`, `I`, `lambda`, writing `substitutions` into an
   operation that does not read them, dropping unread fields); a `verified` result is compared with the draft
   (MATH: `math-equiv-1`; options: the one option within 2 %). Agreement ends the item; disagreement asks the model to
   review; with no readable draft the solver's value or option is the answer (`solver_fallback`).
6. **Notes check** (multiple choice with notes): when exactly one option has all its content words in one passage
   and the draft chose another, the model reviews against those passages.

## Result

| Benchmark (dev) | Class | Items | Harness | Wilson 95 % | T275, same items | Gained | Lost | Model calls | Solver calls | s median | s p95 | Gen. tokens median |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| MATH | all (computable) | 500 | **451 (90.2 %)** | 87.3-92.5 | 433 (86.6 %) | 30 | 12 | 2.30 | 0.89 | 63.6 | 238.8 | 1,305 |
| MMLU-Pro STEM | all | 1,175 | **986 (83.9 %)** | 81.7-85.9 | 938 (79.8 %) | 80 | 32 | 1.93 | 0.54 | 57.7 | 246.5 | 1,057 |
| | computable | 883 | 740 (83.8 %) | 81.2-86.1 | 699 (79.2 %) | 62 | 21 | 2.20 | 0.72 | 66.5 | 261.3 | 1,225 |
| | knowledge | 250 | 211 (84.4 %) | 79.4-88.4 | 207 (82.8 %) | 12 | 8 | 1.11 | 0 | 35.7 | 99.0 | 704 |
| | reasoning | 42 | 35 (83.3 %) | 69.4-91.7 | 32 (76.2 %) | 6 | 3 | 1.12 | 0 | 34.3 | 92.0 | 851 |
| GPQA (main − Diamond) | all | 250 | **150 (60.0 %)** | 53.8-65.9 | 123 (49.2 %) | 38 | 11 | 2.06 | 0.27 | 109.7 | 282.3 | 2,177 |
| | computable | 178 | 104 (58.4 %) | 51.1-65.4 | 80 (44.9 %) | 30 | 6 | 2.40 | 0.38 | 139.0 | 293.0 | 2,846 |
| | knowledge | 20 | 14 (70.0 %) | 48.1-85.5 | 12 (60.0 %) | 4 | 2 | 1.10 | 0 | 58.2 | 196.0 | 834 |
| | reasoning | 52 | 32 (61.5 %) | 48.0-73.5 | 31 (59.6 %) | 4 | 3 | 1.23 | 0 | 49.3 | 234.9 | 1,042 |

Wall time 46.7 min for 1,925 items (T275: 30.5 min); peak GPU memory sampled every second 15.05 GB (whole GPU,
desktop included). The model-free path answered 29 MATH items, **29 right, 0 wrong** (as in T276).

### Where the change comes from

The draft of an item that needed no retry used the T275 prompt and seed; those drafts score as T275 did within engine
variance (first drafts right: MATH 397 / MMLU-Pro 933 / GPQA 122 against T275 on the same items about 405 / 938 /
123), so the gain is not the prompt.

| Step | MATH | MMLU-Pro STEM | GPQA |
|---|---|---|---|
| Model-free (no model) | 29 answered, 29 right | — | — |
| Retry of an unparsed or truncated draft | 58 items, 25 right (T275: 16; 42 of them truncated in T275) | 147 items, 50 right (T275: 39) | 83 items, 28 right (T275: 15) |
| Notes in the prompt (no retry) | — | 286 items, 241 right (T275: 236) | 59 items, 41 right (T275: 41) |
| Formalisation verified by the solver | 274 of 471 asked | 420 of 883 | 33 of 178 |
| Draft and solver agree | 77 items, 76 right | 105 items, 104 right | 3 items, 2 right |
| Review after a disagreement | 141 items: 3 wrong to right, 3 right to wrong | 32 items: no change of verdict | 2 items: no change |
| Solver's answer with no readable draft | 12 items, 1 right | — | — |
| Notes check and review | — | 26 items: 3 wrong to right, 0 right to wrong | 1 item: no change |
| Mechanical repairs applied | 27 | 111 | 14 |

Reading:

- **The retry is the step that pays**: without it the harness would score its first drafts (MATH 397 + 29
  model-free, MMLU-Pro 933, GPQA 122, about T275's level); the retries add 25, 50 and 28 right answers. It acts on the largest loss of
  T275, truncation at 4,096 tokens; it is a budget lever, which T279 measures against budget forcing and escalation.
- **Notes in the prompt change nothing measurable** (+5 of 286 and 0 of 59, within noise), consistent with the weak
  retrieval proxy of T277. The notes check gained 3 of 26 with no loss: small, positive.
- **The solver is a confidence signal, not yet a corrector.** When the model's formalisation and its draft agree the
  answer is right 99 % of the time (182 of 185); when they disagree, the review changes verdicts in both directions
  (net 0 on MATH) at the price of one more call on 141 MATH items. A disagreement usually means a wrong
  formalisation, not a wrong draft. This is the input that T279's early exit and self-consistency on uncertainty need.
- **Formalisation coverage is the limit of the solver path**: 58 % of MATH, 48 % of MMLU-Pro computable items and 19 %
  of GPQA computable items reached a verified result; the rest was refused (mostly `invalid_arguments`: functions
  the solver does not know, several formulas in one call, prose instead of JSON) or not formalised.

### Cost and response time (B4 settings, development only)

| Benchmark | s median (T275) | s p95 (T275) | B4 limits |
|---|---|---|---|
| MATH | 63.6 (36.6) | 238.8 (106.8) | median ≤ 60, p95 ≤ 180 |
| MMLU-Pro STEM | 57.7 (46.1) | 246.5 (128.8) | |
| GPQA | 109.7 (87.4) | 282.3 (140.9) | |

The harness costs 1.9 to 2.3 model calls per item, so latency rose: under this load only the MMLU-Pro median is
within the B4 median, and no p95 is within 180 s. Peak memory (15.05 GB) is within 15.5 GB. Cost is T279's subject:
the review after a disagreement (141 calls on MATH for no net gain) and the formalisation call on items whose draft
is already sure are the first candidates.

### Against the gates (for orientation only; gates are measured on the sealed tests)

MATH dev 90.2 % against B1 95 %; MMLU-Pro STEM dev 83.9 % (81.7-85.9) against B2 84.8 %; GPQA has no threshold yet
(B3 open). B5 on development: 0 wrong model-free answers. Nothing here is a qualification.

## Limits

- One run, one seed per call; engine variance between two vLLM runs on the same seeds is a few items per benchmark
  (T275 parity: 124 of 128 same verdict), so differences of a few items are noise.
- The attribution table counts a retried item's first draft as wrong; a truncated first draft that held a right
  answer would be counted to the retry.
- Router thresholds (50 % numeric options, 40 words) were set before the run and not tuned.
- The run is the Python harness; the server pipeline (T284) has to show the same answers before a sealed run counts
  as measuring the deployed system.

## Found while measuring

- `docker/laris.sh` ignored `LARIS_ENGINE_PORT` from the shell (by design: settings come from `docker/laris.env`), so
  the documented `LARIS_ENGINE_PORT=38100 docker/laris.sh up` never opened the port. Owner decision 2026-11-23: one
  port, set only in `docker/laris.env`; the runner reads the same line (commit `51ef8aa6`). Checked: `docker/laris.sh
  up` then binds `127.0.0.1:38100`.
- The summary took its code revision at the end of the run (`51ef8aa6+changes`); corrected to the revision the
  process ran (`d4fd67ea`) and the runner now takes it at the start.
