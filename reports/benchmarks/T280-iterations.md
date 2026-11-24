# T280 — Development iterations and the frozen candidate

Date measured: 2026-11-24. Measured by LARIS on this machine (RTX 5070 Ti, 16 GB), engine vLLM 0.34.0 serving
Qwen/Qwen3.5-4B in online FP8, 64 items at once (the B4 load), the T275 development splits. **No sealed file was
read.** The model and the system are **NOT QUALIFIED**: these are development numbers, not gate results. No item text
is reproduced (GPQA text is never in Git, reports or the brain); run records hold ids, classes, steps, answers and
cost and stay in `data/benchmarks/runs/` (outside Git).

## 1. Set-up

| | |
|---|---|
| Reference | `combo-fp8-early-sc` (T279, the owner's evaluation profile): rule router + prompt filter, solver first (model-free), early exit, self-consistency (2 samples on a disagreement or a retried draft), FP8, prefix caching; 454 / 998 / 153 right on MATH (500) / MMLU-Pro STEM (1,175) / GPQA main − Diamond (250) |
| Noise | the same configuration rerun: −4 / −12 / +16 (T278 vs T286); in this task three seeds of one configuration differ by up to 14 / 8 / 10 right and flip 44 / 110 / 64 items; an unchanged MATH configuration moved +14 (23 / 9, McNemar p = 0.02) between two runs (section 5). A single paired p-value near 0.02 is therefore not enough on its own |
| Command | `python scripts/stem_benchmarks.py harness --run NAME [--lever L ...] [--bench B] [--path P] [--no-filter]`; levers in `cost_levers` of `configs/stem-benchmarks.json`, fixed before each run; paired comparison by exact McNemar |
| Seeds | per item `generation_seed + seed_offset + hash(id)`; `seed_offset` 0 (a), 100,003 (b, lever `seed_b`), 200,003 (c, lever `seed_c`) |

## 2. Error analysis of the reference (development)

| Source of loss | MATH | MMLU-Pro STEM | GPQA |
|---|---|---|---|
| Wrong answers | 46 | 177 | 97 |
| Items whose draft and retry were both cut at 4,096 tokens | 32 (7 right, 13 no answer) | 85 (19 right, 37 no answer) | 42 (10 right, 17 no answer) |
| Model-free answers (B5) | 29, 0 wrong | — | — |

- **Model / budget:** the largest single loss is a reply cut at its token cap with no readable answer, twice (draft and
  the "keep it short" retry). These items also set the p95 (two full 4,096-token calls each).
- **Extraction:** the cut items above are a missing answer, not a misread one; the extractors were not changed.
- **Solver:** every wrong MATH item is in the computable class; the solver fallback after a draft was right 1 / 10
  times on MATH.
- **Retrieval / router:** weak areas are MMLU-Pro engineering (133 / 194) and GPQA chemistry (43 / 90). The open
  questions from T286 / T287 (filter whitespace on GPQA, notes vs solver on GPQA) are measured in section 4.

Change motivated: when a reply is cut, **conclude** it, i.e. continue the model's own unfinished turn with a closing
sentence and the answer opening (`$\boxed{` or `Answer:`) and let it write only the answer (96 / 16 tokens). Code
`laris.research.stem.harness` (`conclude`, `ConcludeCall`, `Trace.concluded`), tests
`tests/unit/stem/test_iterations.py`.

## 3. Iterations (full development, against the reference)

Right answers, items gained / lost against the reference, exact McNemar p, seconds per item median / p95, model calls
and generated tokens per item.

| Iteration | Levers | Bench | Right | Gained / lost | p | s median / p95 | Calls | Gen. tokens |
|---|---|---|---|---|---|---|---|---|
| ref. | profile of T279 | MATH | 454 | | | 18.6 / 273.8 | 1.33 | 2,206 |
| | | MMLU-Pro | 998 | | | 25.8 / 383.0 | 1.60 | 2,951 |
| | | GPQA | 153 | | | 51.4 / 398.5 | 2.10 | 5,076 |
| 1 (`t280-i1-conclude`, code `40e1ba47`) | conclude after the retry | MATH | 456 | 14 / 12 | 0.845 | 19.1 / 362.1 | 1.57 | 2,424 |
| | | MMLU-Pro | 1,017 | 53 / 34 | 0.053 | 26.8 / 406.2 | 1.69 | 2,835 |
| | | GPQA | 160 | 25 / 18 | 0.360 | 57.2 / 401.0 | 2.64 | 5,353 |
| 2 (`t280-i2-conclude-first`, seed a) | conclude in place of the retry | MATH | 463 | 19 / 10 | 0.136 | 19.1 / 279.3 | 1.48 | 1,968 |
| | | MMLU-Pro | 1,014 | 46 / 30 | 0.085 | 26.7 / 318.7 | 1.68 | 2,462 |
| | | GPQA | 148 | 22 / 27 | 0.568 | 57.3 / 332.3 | 2.54 | 4,413 |
| 2, seed b (`t280-c-seedb`, code `df87ee97`) | same | MATH | 462 | 19 / 11 | 0.200 | 19.3 / 308.3 | 1.58 | 2,145 |
| | | MMLU-Pro | 1,006 | 45 / 37 | 0.440 | 26.0 / 314.1 | 1.63 | 2,371 |
| | | GPQA | 158 | 25 / 20 | 0.551 | 58.0 / 336.5 | 2.57 | 4,502 |
| 2, seed c (`t280-c-seedc`) | same | MATH | 449 | 15 / 20 | 0.500 | 19.5 / 303.8 | 1.48 | 2,020 |
| | | MMLU-Pro | 1,007 | 42 / 33 | 0.356 | 26.7 / 324.1 | 1.70 | 2,507 |
| | | GPQA | 151 | 23 / 25 | 0.885 | 57.2 / 333.7 | 2.54 | 4,448 |
| **3** (`t280-i3-seedc`, code `8bbebb52`) | 2 + thinking 2,048 on the knowledge class | MATH | 463 | 19 / 10 | 0.136 | 19.3 / 300.7 | 1.50 | 2,047 |
| | | MMLU-Pro | 1,011 | 51 / 38 | 0.203 | 41.9 / 324.0 | 1.94 | 2,795 |
| | | GPQA | 149 | 20 / 24 | 0.652 | 65.7 / 339.8 | 2.60 | 4,454 |

- Iteration 1 concluded 14 / 54 / 21 right items against 14 / 29 / 16 left unanswered before, but kept both cut calls,
  so p95 rose (362 / 406 / 401 s). Iteration 2 concludes the cut draft at once: same accuracy within noise, p95 down by
  about 60-80 s on MMLU-Pro and GPQA, fewer generated tokens. Iteration 2 was carried.
- Peak VRAM sampled 15.0 GB in every run (B4 limit 15.5 GB). Model-free 29 answered, 0 wrong (B5) in every run.

## 4. The open items of T286 / T287 / T279

### 4.1 GPQA: the prompt filter's whitespace changes (T286: 1 up, 7 down, p = 0.07)

Iteration 2 on GPQA with and without the filter (`--no-filter`), seeds a and b, paired on the same items.

| Seed | Items with text changed by the filter (34): without → with | Items unchanged (216) | Right with / without |
|---|---|---|---|
| a | 1 / 4 (p = 0.38) | 16 / 25 | 148 / 160 |
| b | 4 / 3 (p = 1.00) | 12 / 19 | 158 / 164 |

Pooled on the changed items 5 up / 7 down (p = 0.77): no sign that the whitespace normalisation hurts; the filter
stays. The unchanged items moved as much (pooled 28 / 44, p = 0.08) with no difference in their prompt: the runs
without the filter were GPQA alone, the runs with it the full development mix, and vLLM batches differ with the load.
Engine variance between runs of different composition is of the size of a single lever; comparisons in this report
pair runs of the same composition where the claim depends on it.

### 4.2 GPQA: notes vs solver by router class (T287: notes 102, solver 97 on computable)

Forced paths (`--path notes_model`, `--path model_solver`) with iteration 2, seeds a and b, against the rule router
(iteration 2 itself); pooled over the two seeds:

| Class (items × 2 seeds) | Rule | Notes every item | Solver every item | Solver → notes gained / lost (p) | Rule → notes (p) |
|---|---|---|---|---|---|
| computable (356) | 216 | 208 | 222 | 35 / 49 (0.16) | 37 / 45 (0.44) |
| knowledge (40) | 26 | 25 | 27 | 2 / 4 (0.69) | 2 / 3 (1.00) |
| reasoning (104) | 64 | 64 | 60 | 13 / 9 (0.52) | 6 / 6 (1.00) |
| all (500) | 306 | 297 | 309 | 50 / 62 (0.30) | 45 / 54 (0.42) |

No path is better than another beyond noise in any class; the T287 lead of notes on computable items does not repeat
(solver 222, notes 208). The rule router stays. The Phase 57 exit criterion "the router beats the bare model and plain
retrieval" still holds on MATH and MMLU-Pro and is still not shown on GPQA.

### 4.3 Thinking budget on knowledge / reasoning (T279: thinking on every draft lost on computable items)

Lever `thinking_kr` (2,048 thinking tokens, answer 1,024, on knowledge and reasoning items only) with iteration 2 on
MMLU-Pro and GPQA, seeds a and b, paired with iteration 2 of the same seed:

| Seed | Bench, class (items) | Iter. 2 | + thinking | Gained / lost | p | p95 s of the class |
|---|---|---|---|---|---|---|
| a | MMLU-Pro knowledge (250) | 203 | 214 | 15 / 4 | 0.019 | 88 → 150 |
| b | MMLU-Pro knowledge (250) | 196 | 213 | 21 / 4 | 0.001 | 78 → 149 |
| a | MMLU-Pro reasoning (42) | 38 | 35 | 0 / 3 | 0.25 | 61 → 151 |
| b | MMLU-Pro reasoning (42) | 37 | 38 | 1 / 0 | 1.00 | 74 → 159 |
| a | GPQA knowledge + reasoning (72) | 43 | 45 | 3 / 1 | — | — |
| b | GPQA knowledge + reasoning (72) | 47 | 45 | 3 / 5 | — | — |

Thinking paid on the knowledge class only; reasoning showed no gain. Iteration 3 (lever `thinking_k`, knowledge
only) on seed c, full development, paired with iteration 2 seed c: MMLU-Pro knowledge 207 → 205 (11 / 13), MATH
449 → 463 (23 / 9, p = 0.02) with no change to any MATH setting (engine variance, see section 1). Pooled over the three
seeds the knowledge class gained 47 and lost 21 (p = 0.002); its p95 rises to about 150-175 s and the MMLU-Pro median
from 27 to 42 s. Kept, as the only lever of this task with a gain pooled beyond noise.

How far the 2,048 budget is from enough (thinking calls of `thinking_kr`, two seeds): 71 % of MMLU-Pro knowledge
calls reached the budget and were closed (82 % right), the rest ended on their own (94 % right); on GPQA 93-94 % reached
it. Items that think longer are also the harder ones, so the 94 % is not what a larger budget would reach. A larger
budget was discussed with the owner and not run in this task; the server context (20,480 tokens per request, 190,691
KV tokens shared at 64 concurrent; the model allows 262,144) is not the limit, the time and the shared KV cache are.

## 5. Answers concluded after a cut: guesses, not knowledge

A concluded answer is the model's best guess at the moment the cap cut it. On development they are right about half the
time; the other answers are right far more often:

| Run | MATH concluded / rest | MMLU-Pro concluded / rest | GPQA concluded / rest |
|---|---|---|---|
| iteration 2, seed a | 29 / 55 · 434 / 445 | 87 / 163 · 927 / 1,012 | 28 / 79 · 120 / 171 |
| iteration 2, seed b | 43 / 65 · 419 / 435 | 77 / 150 · 929 / 1,025 | 34 / 79 · 124 / 171 |
| iteration 2, seed c | 20 / 51 · 429 / 449 | 86 / 167 · 921 / 1,008 | 34 / 79 · 117 / 171 |
| iteration 3, seed c | 34 / 57 · 429 / 443 | 119 / 207 · 892 / 968 | 29 / 79 · 120 / 171 |

The benchmarks score pass@1 with abstention as 0 (D59), so a guess never costs points there; in use, a guess said with
the confidence of an answer is a hallucination. Every run record carries `concluded`, so a concluded answer can be
shown as uncertain or withheld; doing so in the chat route is a decision for the owner and a programme-2 task, not part
of this evaluation profile.

## 6. The frozen candidate (for T281)

| | |
|---|---|
| Code | `77546576` (branch `feature/T280-dev-iterations`); measured at `8bbebb52` as iteration 3, whose settings it holds as the defaults |
| Configuration | `configs/stem-benchmarks.json`, harness section SHA-256 `3dddd9ab…` (`3dddd9aba2dd6ede91936c3da26f7be14ea18fdf3d2f2dbe296f7d97f134cb4d`); equal to the run `t280-i3-seedc` (`b965d80c…`) except `seed_offset` 0 and the text of `conclude.note`; prompt filter rules `c6732ed5…` |
| Pipeline | rule router + prompt filter, solver first (model-free), notes for knowledge / reasoning, formalise only an uncertain computable draft, no review, conclude a cut draft in place of the retry (`conclude.replace_retry`), conclude cut self-consistency samples, self-consistency 2 samples on a disagreement or a retried draft, thinking off except a 2,048-token budget on the knowledge class; max 4,096 new tokens; scoring `math-equiv-1` |
| Brain | snapshot `stem-t277-2`, SHA-256 `fb01dd0369977487c4bcebd8f8ae2f627031fc9ebe0630029f37467c48ddeacb` |
| Model | Qwen/Qwen3.5-4B, revision `851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a`; `model.safetensors-00001-of-00002` `26a93f06…8e74c61`, `-00002-of-00002` `cb544bd9…7d910e188`, `config.json` `ddc63e1c…`, `tokenizer.json` `5f9e4d49…`, `tokenizer_config.json` `316230d6…`, `chat_template.jinja` `a4aee8af…` (SHA-256) |
| Engine | `vllm/vllm-openai:v0.34.0` image `sha256:20fdb089…`, `--dtype bfloat16 --quantization fp8 --max-model-len 20480 --gpu-memory-utilization 0.85 --max-num-seqs 64 --enable-prefix-caching --seed 2752` |
| Development result | MATH 463 / 500 (92.6 %), MMLU-Pro STEM 1,011 / 1,175 (86.0 %), GPQA 149 / 250 (59.6 %); seconds median 19.3 / 41.9 / 65.7, p95 300.7 / 324.0 / 339.8; peak 15.0 GB; model-free 29, 0 wrong |

## 7. Against the gates, on development only

| Gate | Development (candidate) | Reading |
|---|---|---|
| B1 MATH ≥ 95 % | 449-463 / 500 over the iteration-2/3 runs (89.8-92.6 %) | short by 12-26 items; not reachable by the levers of T279 / T280 |
| B2 MMLU-Pro STEM ≥ 84.8 % | 1,006-1,014 / 1,175 (85.6-86.3 %) | above on development, within about 1 point |
| B3 GPQA | 148-158 / 250 (main − Diamond) | threshold open |
| B4 median ≤ 60 s, p95 ≤ 180 s, VRAM ≤ 15.5 GB | p95 300-340 s on all three; GPQA median 65.7 s; 15.0 GB | p95 fails; GPQA median now over by 6 s (the knowledge thinking) |
| B5 0 wrong model-free | 29 / 0 | holds |
| B6 leakage | snapshot `stem-t277-2` scanned in T277 | to be rescanned on the sealed run (T281) |

ADR-026 section 10: B1 does not reach 95 % with the light model after T280. The options go to the owner: a larger
model (against D64 / decision 4), more solver coverage of MATH, a longer thinking budget with B4 relaxed or measured
apart, or a recorded FAIL of B1. None is taken without the owner. The sealed run (T281) is the owner's order.

The model and the system are **NOT QUALIFIED**.
