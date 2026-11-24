# T279 — Cost and response time: the levers of ADR-026 section 8 measured

Date measured: 2026-11-24. Measured by LARIS on this machine (RTX 5070 Ti, 16 GB), engine vLLM 0.34.0 serving
Qwen/Qwen3.5-4B (snapshot `851bf6e8…`), 64 items at once (the B4 load), the T275 seeds. Development splits only; no
sealed file was read. The model and the system are **NOT QUALIFIED**: these are development numbers, not gate
results. No item text is reproduced; run records hold ids, classes, steps, answers and cost.

Owner's choices for this task (2026-11-24): BF16 and FP8 only (bitsandbytes is not in the approved vLLM image; the
T275 4-bit smoke stands as the 4-bit evidence), Qwen3.5-4B only for D64, one full development run per lever.

## 1. Set-up

| | |
|---|---|
| Code | `6e268f3b` (levers, off by default), runs at `3103b5fa` (ledger note only after it); `harness.py` SHA-256 `cb99d58e…`, `cost.py` `757524d8…`; scoring protocol `math-equiv-1` unchanged |
| Reference | `harness-filter-dev` (T286): the rule router of T278 with the prompt filter, BF16, prefix caching, code `793704c2`, harness section `0a2dba0a…`, brain snapshot `stem-t277-2` `fb01dd03…` |
| Noise | the same configuration run twice (T278 `harness-dev` against T286 `harness-filter-dev`; the filter changed whitespace only): −4 / −12 / +16 right on MATH / MMLU-Pro STEM / GPQA, 32 / 66 / 44 items flipped. A difference of this size is engine variance, not a lever |
| Command | `python scripts/stem_benchmarks.py harness --run lever-NAME --lever NAME` (settings in `cost_levers` of `configs/stem-benchmarks.json`, fixed before the runs); tables: `cost-report --reference harness-filter-dev.jsonl RUNS` (paired, exact McNemar); records in `data/benchmarks/runs/` (outside Git) |
| Engine variants | FP8: the same image with `--quantization fp8` (online per-tensor FP8 of the BF16 weights; vLLM names it `fp8_per_tensor` from now on), confirmed in the server log (`quantization=fp8`); no prefix cache: `--no-enable-prefix-caching`. Both started as a one-off container on the same port with the arguments of `docker/compose.chat.yaml` otherwise unchanged; the compose stack stayed BF16 and stopped |

The levers (`laris.research.stem.harness`, `laris.research.stem.cost`):

| Lever | Setting | What it does |
|---|---|---|
| Solver first | model-free path (T276), on | a computable open-answer item the strict patterns solve is answered without the model |
| Repetition stop | `repetition`: a chunk of 16-512 characters repeated 6 times at the tail, looked at every 256 characters after 1,000 | the reply is streamed and the request ends at a loop; the retry follows as for a cut reply |
| Escalation | `draft.escalate`: thinking budget 4,096 tokens, answer 1,024 | an unparsed or cut draft is asked again with thinking on, in place of the "keep it short" retry |
| Thinking budget per class | `draft.thinking`: 2,048 tokens for every class, answer 1,024 | every draft thinks; per-class results read from the one run |
| Budget forcing | with the two above | a thinking reply that reaches its budget is closed with Qwen's own sentence and `</think>`, and the model writes the answer (raw completion on the chat template) |
| Early exit | `formalise.when: uncertain`, `formalise.review: false` | formalise only a retried or unread draft; on a disagreement the draft stands |
| Self-consistency | 2 more drafts on other seeds, on a disagreement or a retried draft | the draft, the samples (and the solver's answer on a disagreement) vote; a tie keeps the draft |
| FP8, prefix caching | engine settings | see above |

## 2. One lever at a time, against the reference (paired, same items)

Right answers (reference), items gained / lost, exact McNemar p, seconds per item median and p95 (reference in
brackets), generated tokens and model calls per item.

| Benchmark | Run | Right (ref.) | Gained / lost | p | s median (ref.) | s p95 (ref.) | Gen. tokens mean (ref.) | Model calls (ref.) |
|---|---|---|---|---|---|---|---|---|
| MATH (500) | repetition | 457 (455) | 14 / 12 | 0.845 | 62.2 (67.4) | 229.4 (234.4) | 2,185 (2,290) | 2.28 (2.31) |
| | escalate | 441 (455) | 10 / 24 | **0.024** | 73.8 (67.4) | 307.7 (234.4) | 2,438 (2,290) | 2.40 (2.31) |
| | early exit | 447 (455) | 11 / 19 | 0.200 | **36.9** (67.4) | 240.3 (234.4) | 1,658 (2,290) | **1.14** (2.31) |
| | self-consistency | 456 (455) | 12 / 11 | 1.000 | 66.4 (67.4) | 338.5 (234.4) | 2,752 (2,290) | 2.69 (2.31) |
| | thinking 2,048 | 450 (455) | 12 / 17 | 0.458 | 136.3 (67.4) | 268.0 (234.4) | 3,582 (2,290) | 3.27 (2.31) |
| | FP8 | 449 (455) | 14 / 20 | 0.392 | **28.7** (67.4) | **189.3** (234.4) | 2,191 (2,290) | 2.29 (2.31) |
| | no prefix cache | 449 (455) | 13 / 19 | 0.377 | 59.3 (67.4) | 218.4 (234.4) | 2,213 (2,290) | 2.29 (2.31) |
| MMLU-Pro STEM (1,175) | repetition | 984 (998) | 30 / 44 | 0.130 | 59.2 (57.7) | 251.5 (247.3) | 2,073 (2,023) | 1.93 (1.93) |
| | escalate | 975 (998) | 36 / 59 | **0.023** | 67.8 (57.7) | 364.6 (247.3) | 2,304 (2,023) | 2.06 (1.93) |
| | early exit | 995 (998) | 32 / 35 | 0.807 | **47.9** (57.7) | 268.7 (247.3) | 1,935 (2,023) | **1.27** (1.93) |
| | self-consistency | 1,009 (998) | 37 / 26 | 0.207 | 67.1 (57.7) | 486.9 (247.3) | 2,905 (2,023) | 2.21 (1.93) |
| | thinking 2,048 | 975 (998) | 30 / 53 | **0.015** | 131.8 (57.7) | 270.3 (247.3) | 3,310 (2,023) | 2.90 (1.93) |
| | FP8 | 993 (998) | 43 / 48 | 0.675 | **26.7** (57.7) | **200.2** (247.3) | 2,045 (2,023) | 1.92 (1.93) |
| | no prefix cache | 981 (998) | 28 / 45 | 0.060 | 56.0 (57.7) | 239.3 (247.3) | 2,101 (2,023) | 1.95 (1.93) |
| GPQA main − Diamond (250) | repetition | 141 (134) | 19 / 12 | 0.281 | 109.5 (100.7) | 276.6 (274.6) | 3,404 (3,176) | 2.03 (2.02) |
| | escalate | 130 (134) | 20 / 24 | 0.652 | 121.4 (100.7) | 388.3 (274.6) | 3,922 (3,176) | 2.36 (2.02) |
| | early exit | 148 (134) | 23 / 9 | 0.020 | **83.1** (100.7) | 298.5 (274.6) | 3,294 (3,176) | **1.61** (2.02) |
| | self-consistency | 156 (134) | 32 / 10 | **0.001** | 127.3 (100.7) | 533.4 (274.6) | 5,050 (3,176) | 2.62 (2.02) |
| | thinking 2,048 | 142 (134) | 25 / 17 | 0.280 | 163.5 (100.7) | 284.4 (274.6) | 4,282 (3,176) | 3.24 (2.02) |
| | FP8 | 141 (134) | 21 / 14 | 0.311 | **52.9** (100.7) | **205.6** (274.6) | 3,449 (3,176) | 2.05 (2.02) |
| | no prefix cache | 148 (134) | 21 / 7 | 0.013 | 95.0 (100.7) | 265.2 (274.6) | 3,253 (3,176) | 2.03 (2.02) |

Solver first was not rerun: on the 29 MATH items the model-free path answers (29 right, 0 wrong, 0.02 s median),
the model-and-solver path of T287 (`path-model_solver`, no model-free step) was also 29 right, at 2.07 model calls,
717 generated tokens and 28.4 s median per item; the bare model was 28 right.

Offline, from the reference's own records (no engine noise): keeping the draft where the solver review gave the
answer scores 452 / 999 / 134 (reference 455 / 998 / 134); also dropping the solver fallback, 451 / 999 / 134.

### Reading

- **GPQA moves by itself.** The reference configuration rerun gained 16 GPQA items, and the no-prefix-cache run, which
  changes no generation setting, gained 14 (p = 0.013). On GPQA (250 items) only a change well beyond about ±16
  items, or one shown inside a run (below), is read as an effect.
- **Escalation to budgeted thinking loses** on MATH and MMLU-Pro (p ≈ 0.02). The items it acts on are those the
  model writes too long for: 284 of 287 thinking calls reached the 4,096-token budget and were forced, and the
  forced answers were right on 15 / 36 / 13 items against 30 / 59 / 16 for the "keep it short" retry. Rejected.
- **A thinking budget for every draft loses** on MMLU-Pro (p = 0.015), doubles the median time and is not better on
  MATH or GPQA (within noise). Split by router class, the loss is the computable class (MMLU-Pro 724 against 756 of
  883); knowledge and reasoning items moved up a little (MMLU-Pro +6 of 250 and +3 of 42, GPQA +1 of 20 and +4 of
  52), within noise, at about twice the time. No class is given a budget now; a budget for knowledge and reasoning
  items is a candidate for T280 to repeat on more seeds. Rejected as measured.
- **Repetition stop** cut 13 generations (9 of those items right afterwards); accuracy and time within noise. The
  long replies are long, not looping. Not kept (no measured gain; it adds streaming to every call).
- **Early exit** halves the model calls (1.14 / 1.27 / 1.61 per item) and cuts the median time by 45 / 17 / 17 %;
  accuracy within noise (MATH −8, p = 0.20; offline the review alone was worth 3 items). The p95 does not fall: it
  is set by the items whose draft is cut and retried. **Kept.**
- **Self-consistency** raises accuracy inside the run: the vote changed 59 answers, 32 wrong to right and 2 right to
  wrong (MATH 7 / 1, MMLU-Pro 16 / 1, GPQA 9 / 0); GPQA +22 (p = 0.001) is beyond its noise. It costs 0.4-0.6 calls per
  item and doubles the p95 (339 / 487 / 533 s).
- **FP8** halves the median time (28.7 / 26.7 / 52.9 s) and brings the p95 to 189-206 s, with accuracy within noise.
  Peak GPU memory is unchanged (14.8-14.9 GB sampled, as the reference's 14.8 GB): vLLM reserves 85 % of the GPU either way and gives FP8's saving
  to the KV cache, which is where the speed comes from at 64 requests. **Kept** for the evaluation profile.
- **Prefix caching off** saves nothing measurable; it stays on (default of the engine since T282).

## 3. Combinations on the FP8 engine

| Benchmark | Run | Right (ref.) | Wilson 95 % | Gained / lost | p | s median | s p95 | Gen. tokens median | Model calls |
|---|---|---|---|---|---|---|---|---|---|
| MATH | FP8 + early exit + self-consistency | 454 (455) | 87.9-93.0 % | 20 / 21 | 1.000 | 18.6 | 273.8 | 867 | 1.33 |
| MMLU-Pro STEM | | 998 (998) | 82.8-86.9 % | 41 / 41 | 1.000 | 25.8 | 383.0 | 996 | 1.60 |
| GPQA | | 153 (134) | 55.0-67.0 % | 30 / 11 | 0.004 | 51.4 | 398.5 | 1,874 | 2.10 |
| MATH | **FP8 + early exit** | 458 (455) | 88.8-93.7 % | 16 / 13 | 0.711 | 19.2 | 180.6 | 887 | 1.17 |
| MMLU-Pro STEM | | 991 (998) | 82.2-86.3 % | 39 / 46 | 0.515 | 24.1 | 196.0 | 1,009 | 1.28 |
| GPQA | | 147 (134) | 52.6-64.7 % | 29 / 16 | 0.072 | 53.2 | 206.9 | 2,161 | 1.62 |

Peak GPU memory sampled 14.8-14.9 GB in both (whole GPU). Model-free answers: 29, 0 wrong (B5 on development). In the
self-consistency combination the vote changed 59 answers, 30 wrong to right and 2 right to wrong.

## 4. Against B4 (development, for orientation only)

B4: median ≤ 60 s, p95 ≤ 180 s per item under 64 concurrent requests, peak VRAM ≤ 15.5 GB.

| Benchmark | Reference (BF16, T286 rule router) median / p95 | FP8 + early exit | FP8 + early exit + self-consistency |
|---|---|---|---|
| MATH | 67.4 / 234.4 | **19.2 / 180.6** | 18.6 / 273.8 |
| MMLU-Pro STEM | 57.7 / 247.3 | **24.1 / 196.0** | 25.8 / 383.0 |
| GPQA | 100.7 / 274.6 | **53.2 / 206.9** | 51.4 / 398.5 |
| Peak VRAM (sampled) | 14.8 GB | 14.9 GB | 14.8 GB |

With FP8 and early exit every median is within 60 s and the peak memory within 15.5 GB; the p95 is 1-27 s over
180 s on all three. The items that set the p95 are those whose draft is cut at 4,096 tokens and retried (two long
calls); no lever measured here shortens them without losing accuracy (escalation and thinking lost, repetition stop
found few loops). Self-consistency adds 7 right answers on MMLU-Pro and 6 on GPQA over this candidate, and 4 fewer on MATH (inside
its own run, 30 wrong to right against 2 right to wrong) and roughly doubles the p95.

**Candidate carried to T280: solver first + early exit + FP8, prefix caching on, self-consistency off** (owner's
choice 2026-11-24 to measure both; the trade of self-consistency against B4's p95 is left to the owner, with these
numbers). Accuracy of the candidate against the reference is within noise on all three benchmarks; the model calls
fall from 2.31 / 1.93 / 2.02 to 1.17 / 1.28 / 1.62 per item.

## 5. Light-model choice (D64)

Qwen3.5-4B, the owner's default candidate, is the only model measured (owner's choice 2026-11-24): BF16 and FP8 on
the same weights. FP8 is the measured candidate precision of the evaluation profile (accuracy within noise, half the
median time, same reserved memory). At the owner's choice the shared engine of `docker/compose.chat.yaml` (chat and
evaluation, T282) stays BF16 for now; FP8 is a server argument (`--quantization fp8_per_tensor`) to set there when
the owner decides, before a sealed run, so the sealed run measures the deployed precision.

## 6. Limits

- One run per lever; the noise reference is one rerun. Effects of a few items are not read as effects.
- Each lever was measured alone against BF16; FP8 was combined only with the kept levers.
- Seconds are wall times under 64 concurrent requests, so a lever that removes calls also speeds the others.
- Peak memory is the whole GPU sampled every second (desktop included); vLLM's reservation dominates it.
- The runs are the Python harness of the evaluation profile, not the server pipeline (T284).
