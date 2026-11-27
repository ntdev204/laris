# T284 — The STEM profile in the server against the Python harness (development)

Measured 2026-11-27 on **development** items only. No sealed file was read. This is a parity check of the server's
profile against the reference, not a qualification: ADR-026 judges every gate on the sealed test. The model and the
system are **NOT QUALIFIED**.

## Setting

- Configuration: `configs/stem-benchmarks.json` as frozen by T290 (thinking budget computable 56,000, knowledge 2,048;
  conclusion `replace_retry`; self-consistency with 2 samples), unchanged; seed 2752, `seed_offset` 0.
- Engine: one vLLM server (Qwen3.5-4B, FP8, `--max-model-len 65536`) shared by both runs, which ran at the same time.
- Items: 64 development ids drawn with seed 284: 24 MATH (train sample), 24 MMLU-Pro STEM, 16 GPQA (main minus
  Diamond). The list lives outside Git with the run files.
- Reference: `scripts/stem_benchmarks.py harness --ids IDS --run t284-parity-python` (the Python loop).
- Candidate: `scripts/stem_benchmarks.py harness --ids IDS --server-bin --run t284-parity-server` (the server's Rust
  profile through `laris-server stem run`, its deterministic steps through the model service's `stem_check`).
- Comparison: `scripts/stem_benchmarks.py harness-parity t284-parity-python.jsonl t284-parity-server.jsonl`.

## Result

| Benchmark | Items | Same final answer | Same verdict | Same route | Correct, Python | Correct, server | McNemar p |
|---|---|---|---|---|---|---|---|
| MATH (development) | 24 | 24 | 24 | 24 | 22 | 22 | 1.0 |
| MMLU-Pro STEM (development) | 24 | 24 | 24 | 24 | 22 | 22 | 1.0 |
| GPQA (development) | 16 | 13 | 15 | 16 | 10 | 9 | 1.0 |
| All | 64 | 61 | 63 | 64 | 54 | 53 | 1.0 |

- Every server seed equals the runner's formula (generation seed + offset + item hash), 64 of 64.
- The three different answers are all GPQA, two on computable items (one draft right in Python and wrong on the
  server, one wrong in both) and one knowledge item settled by the vote (wrong in both). All three are long thinking
  replies (9,500 to 19,000 generated tokens), where batch composition on a shared engine changes the sampled text.
  This is the engine's own variance, which the T275 parity rule allows.
- One MATH item reached the same, correct answer by a different path (Python: the draft; server: the vote after a
  cut draft), at 61,767 generated tokens against 15,421. Over all items the server generated 748,354 tokens and the
  Python harness 624,614.
- Peak VRAM 14.76 GB (below the 15.5 GB of B4). Times are not compared: both runs shared one engine at once.

## Reading

On these development items the server profile and the Python harness give the same routes and, outside three long
GPQA replies, the same answers on the same seeds; no paired difference in correctness (McNemar p = 1.0). 64 items
cannot show small differences in accuracy; the full development splits (T290) remain the measured figures of the
candidate. The model and the system are NOT QUALIFIED.
