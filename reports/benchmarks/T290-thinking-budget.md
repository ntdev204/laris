# T290 — Thinking budget at the VRAM ceiling (development)

Measured 2026-11-26 and 2026-11-27 on the **development** splits only. No sealed file was read. These figures are not
a qualification: ADR-026 judges every gate on the sealed test. The model and the system are **NOT QUALIFIED**.

## Setting

`harness.draft.thinking = {computable: 56000, knowledge: 2048}` (before: `{knowledge: 2048}`); engine
`--max-model-len 65536` (before 20480), `--gpu-memory-utilization 0.85`, FP8, `--max-num-seqs 64`, seed 2752.
Seeds a, b, c are `seed_offset` 0, 100003, 200003. Baseline for pairing: `t280-i3-seedc`.

## Steps on MATH development, seed a

| Computable budget | Correct / 500 | Note |
|---|---|---|
| T280 candidate (none) | 463 (run `t280-i3-seedc`, seed c) | |
| 16,000 | 460 | against 463: +14 / -17, McNemar p = 0.72 |
| 28,000 | 473 | +21 / -11, p = 0.11; 26 replies cut at the cap |
| 56,000 | 483 | 14 replies cut at the cap |

The intermediate budgets were measured on one seed only. 56,000 is the largest budget that fits the 65,536 context; it
is not shown to be the best possible one.

## 56,000, three seeds

| Benchmark | Seed | Correct | Accuracy | Wilson 95 % | Seconds median / p95 | Generated tokens, mean | Peak VRAM |
|---|---|---|---|---|---|---|---|
| MATH (500) | a | 483 | 96.6 % | 94.6-97.9 | 1,752 / 4,287 | 17,403 | 14.88 GB |
| MATH (500) | b | 486 | 97.2 % | 95.4-98.3 | 1,426 / 3,541 | 13,433 | 14.93 GB |
| MATH (500) | c | 484 | 96.8 % | 94.9-98.0 | 1,713 / 4,422 | 17,222 | 14.61 GB |
| MMLU-Pro STEM (1,175) | a | 1,028 | 87.5 % | 85.5-89.3 | 237 / 688 | 5,762 | 14.61 GB |
| MMLU-Pro STEM (1,175) | b | 1,025 | 87.2 % | 85.2-89.0 | 244 / 768 | 5,882 | 14.61 GB |
| MMLU-Pro STEM (1,175) | c | 1,025 | 87.2 % | 85.2-89.0 | 201 / 686 | 5,759 | 14.60 GB |
| GPQA, main minus Diamond (250), reported only | a | 164 | 65.6 % | 59.5-71.2 | 445 / 1,529 | 9,349 | 14.62 GB |

Seconds are per item under 64 concurrent requests and include queueing. VRAM is sampled.

**GPQA has one seed.** The owner closed the measurement on 2026-11-27 ("kết quả này chốt luôn"); the seed b run was
stopped unfinished and seed c was not started. No figure is taken from the unfinished run. GPQA is not a gate (D65).

## Against the gates, on development only

| Gate | Development | Reading |
|---|---|---|
| B1 MATH ≥ 95 % (475 / 500) | 483, 486, 484 | above on three seeds; the Wilson lower bound of seed a (94.6 %) is under 95 % |
| B2 MMLU-Pro STEM ≥ 84.8 % (997 / 1,175) | 1,028, 1,025, 1,025 | above on three seeds |
| B4 peak VRAM ≤ 15.5 GB | at most 14.93 GB | holds in every complete run; time is reported, not gated (D67) |
| B5 0 wrong model-free | 29 / 0 on each MATH run; none given on the other runs | holds |
| B6 leakage | `stem-t277-2` rescanned 2026-11-27 (13-gram): 0 hits | holds |

The settings were chosen on these development items, so the development accuracy is expected to be optimistic. The
MATH development proxy is drawn from MATH train; MATH-500 itself is unmeasured. Thinking time rose from a median of
about 19 s per MATH item (T280) to about 24-29 minutes under the same load.

## Frozen candidate (replaces T280 section 6)

| | |
|---|---|
| Configuration | harness section SHA-256 `db5f3bdd04ef624fe1912d781cdd6082377f5a3ac4339f4f3f5eb30a2c9230cd`, equal to the seed a runs (MATH and MMLU-Pro); seeds b and c differ in `seed_offset`; prompt filter rules `c6732ed5…` |
| Code | pipeline of T280 (`src/laris/research/stem` unchanged since `8bbebb52`); the runner gained `--ids`, unused in these runs. The MATH runs record revision `fffb0c55` with the lever then uncommitted, the others `fc411d7b` |
| Brain | `stem-t277-2`, SHA-256 `fb01dd0369977487c4bcebd8f8ae2f627031fc9ebe0630029f37467c48ddeacb` |
| Model | Qwen/Qwen3.5-4B `851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a`; weights `26a93f066e1916adb13453dae5a0c707c0fbc71299ed98779571a907b8e74c61`, `cb544bd9bfae93dc59b0f22b292f5933573854a7f9b97835c67060d7d910e188`; `config.json` `ddc63e1c…`, `tokenizer.json` `5f9e4d49…`, `tokenizer_config.json` `316230d6…`, `chat_template.jinja` `a4aee8af…` |
| Engine | `vllm/vllm-openai:v0.34.0` image `sha256:20fdb089…`, FP8, `--max-model-len 65536` (now the default of `docker/compose.chat.yaml`; chat shares this engine) |

## Next

The sealed run (T281) on this candidate. Sealed sizes: MATH-500 500, MMLU-Pro STEM 4,703, GPQA Diamond 198. From the
development durations it is estimated at 11 to 12 hours.
