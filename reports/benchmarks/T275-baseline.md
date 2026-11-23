# T275 — Bare-model baseline on the STEM development splits

Date measured: 2026-11-23. Measured by LARIS on this machine (RTX 5070 Ti, 16 GB). Development splits only; no
sealed file was read (`data/benchmarks/sealed_runs.jsonl` does not exist). This is a baseline of the **bare model**
(one prompt, one answer, no harness, no retrieval, no solver). It is **not** a qualification: the model
(Qwen3.5-4B) and the system are **NOT QUALIFIED**. Item text is not reproduced here; GPQA text never is.

## Set-up

| | |
|---|---|
| Model | `Qwen/Qwen3.5-4B`, BF16, no quantisation |
| Engine | vLLM 0.34.0 server (`vllm/vllm-openai:v0.34.0`), 64 concurrent requests, `--max-num-seqs 64`, prefix caching, max length 12,288, 85 % of the GPU (`configs/stem-benchmarks.json`) |
| Prompt | zero-shot; MATH: "reason step by step, final answer in `\boxed{}`"; multiple choice: "Answer: X" on the last line |
| Sampling | thinking off: temperature 0.7, top-p 0.8, top-k 20, at most **4,096** new tokens; thinking on: 0.6 / 0.95 / 20, at most **8,192**; per-item seed from the item id |
| Scoring | pass@1; extraction and equivalence protocol `math-equiv-1` (`answers.py` SHA-256 `60f09b90…df1d1e`); an unparsed or truncated answer scores 0 (ADR-026 section 4) |
| Splits | `math500` dev = 500 seeded MATH **train** problems; `mmlu_pro_stem` dev = seeded 20 % of the MMLU-Pro STEM test items (6 categories); `gpqa_diamond` dev = GPQA **main minus Diamond** (250). Split seed 275, option shuffle seed 2751 (manifest in `data/benchmarks/manifest.json`) |

Cost columns: seconds are the wall time of one request **under the load of 64 concurrent requests** (latency under
load, not single-request latency); peak VRAM is the GPU memory the vLLM server holds from its start. The
`batch_size` field of the run summary is the transformers setting and does not apply to this engine.

## Thinking off (full development splits, 1,925 items, 30.5 min wall, 3.06 M generated tokens)

| Benchmark (dev) | Items | Correct | Accuracy | Wilson 95 % | Unparsed | Truncated at 4,096 | s/item median | s/item p95 | Gen. tokens median | Peak VRAM GB |
|---|---|---|---|---|---|---|---|---|---|---|
| MATH | 500 | 433 | **86.6 %** | 83.3-89.3 | 50 | 55 | 36.6 | 106.8 | 863 | 14.9 |
| MMLU-Pro STEM | 1,175 | 938 | **79.8 %** | 77.4-82.0 | 124 | 160 | 46.1 | 128.8 | 972 | 14.9 |
| GPQA (main − Diamond) | 250 | 123 | **49.2 %** | 43.1-55.4 | 71 | 81 | 87.4 | 140.9 | 2,001 | 14.9 |

Every unparsed answer was a truncated one (0 unparsed among answers that ended). Accuracy among the answers that
ended before the limit: MATH 428/445 (96.2 %), MMLU-Pro STEM 922/1,015 (90.8 %), GPQA 121/169 (71.6 %). The
token limit is the largest single source of loss; whether a truncated answer was a long solution or a repetition
loop was not classified (outputs are not stored).

Per category (thinking off):

| Benchmark | Category | Items | Accuracy | Wilson 95 % |
|---|---|---|---|---|
| MATH | Algebra | 115 | 95.7 % | 90.2-98.1 |
| MATH | Counting & Probability | 48 | 85.4 % | 72.8-92.8 |
| MATH | Geometry | 52 | 75.0 % | 61.8-84.8 |
| MATH | Intermediate Algebra | 90 | 84.4 % | 75.6-90.5 |
| MATH | Number Theory | 58 | 82.8 % | 71.1-90.4 |
| MATH | Prealgebra | 82 | 93.9 % | 86.5-97.4 |
| MATH | Precalculus | 55 | 76.4 % | 63.7-85.6 |
| MMLU-Pro STEM | biology | 143 | 88.8 % | 82.6-93.0 |
| MMLU-Pro STEM | chemistry | 226 | 85.0 % | 79.7-89.0 |
| MMLU-Pro STEM | computer science | 82 | 70.7 % | 60.1-79.5 |
| MMLU-Pro STEM | engineering | 194 | 58.8 % | 51.7-65.5 |
| MMLU-Pro STEM | math | 270 | 84.8 % | 80.0-88.6 |
| MMLU-Pro STEM | physics | 260 | 83.8 % | 78.9-87.8 |
| GPQA | Biology | 59 | 61.0 % | 48.3-72.4 |
| GPQA | Chemistry | 90 | 32.2 % | 23.5-42.4 |
| GPQA | Physics | 101 | 57.4 % | 47.7-66.6 |

## Thinking on (stopped by the owner after 121 items)

The plan was a seeded, stratified 25 % of each development split (479 items). The owner stopped the run after 121
items (117 MATH, 4 MMLU-Pro STEM) because most answers were cut at the limit; it is reported as it stands.

| Items | Correct | Truncated at 8,192 | Correct among answers that ended | s/item median (MATH) | Gen. tokens median (MATH) |
|---|---|---|---|---|---|
| 121 | 70 (57.9 %) | 59 | 62/62 | 306.2 | 8,192 |

Reading: with an 8,192-token budget, thinking on fails by running out of budget, not by reasoning wrongly; the
answers that ended (median 3,100 tokens) were all right. The items that end early are likely the easier ones, so
62/62 is an upper-biased figure. This is a measure of "thinking on with an 8,192-token cap", not of the model's
thinking ability.

## Engine parity

128 MATH development items were scored with both engines (transformers BF16 in-process, then vLLM): 126 and 124
correct, the same verdict on 124. The difference is within sampling noise; the engine change does not shift the
baseline.

## What follows from it (for T278-T279)

- Budget forcing: close the thinking at a budget and let the model write its answer, so a long thought gives an
  answer instead of 0.
- Escalation: thinking off first; thinking (with a budget) only for answers that are truncated, missing or
  inconsistent across samples.
- Repetition detection to stop loops early; a larger budget only where escalation needs it.
- Solver first for computable problems (T276).

## Gate thresholds (ADR-026 section 6, proposal rule: dev baseline + 5, capped at the vendor figure + 5; owner's decisions of 2026-11-23)

| Gate | Baseline used | Proposal | Status |
|---|---|---|---|
| B1 MATH-500 | — | ≥ 95.0 % (fixed in ADR-026) | fixed |
| B2 MMLU-Pro STEM | 79.8 % (thinking off) | 84.8 % (no vendor MMLU-Pro figure in the T228 report to cap it) | **fixed by the owner: ≥ 84.8 %** |
| B3 GPQA Diamond | 49.2 % (thinking off, GPQA main − Diamond) | not proposed: the thinking-off figure is far below the vendor 76.2 (Diamond, thinking mode not stated), so baseline + 5 would be too lax; to be fixed after GPQA is measured with a thinking budget | open |
| B4 cost and latency | thinking off: median 36.6-87.4 s per item under load, p95 106.8-140.9 s, median 863-2,001 generated tokens, 14.9 GB | median ≤ 60 s, p95 ≤ 180 s per item under the same load, peak VRAM ≤ 15.5 GB | **fixed by the owner** |

## Records (outside Git)

`data/benchmarks/runs/baseline-thinking_off.jsonl` (1,925 records) and `.summary.json`,
`data/benchmarks/runs/baseline-thinking_on.jsonl` (121 records), `data/benchmarks/runs/parity-transformers-thinking_off.jsonl`
(128 records), `data/benchmarks/provenance.json`, `data/benchmarks/manifest.json`. Records hold item ids, the
extracted answer (a letter for multiple choice), scores and cost; no question or option text.
