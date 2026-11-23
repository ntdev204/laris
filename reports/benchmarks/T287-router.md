# T287 — The STEM router measured, and a router network only through a held-out gate

Date measured: 2026-11-24. Measured by LARIS on this machine (RTX 5070 Ti, 16 GB), engine vLLM serving Qwen/Qwen3.5-4B
BF16, the same engine and seeds as T275, T278 and T286. Development splits only; no sealed file was read. The model
and the system are **NOT QUALIFIED**: these are development numbers, not gate results. No item text is reproduced;
run records and the router dataset hold features, labels and counts only.

**The router network was not trained.** Training is the owner's (SR-M3); the code, the sealed dataset and the command
are ready (section 6). Its gates are **NOT VERIFIED** and the rule router of T278 stays.

## 1. What was run

Each path ran on each of the 1,925 development items (`scripts/stem_benchmarks.py harness --path P`, code `40b3706e`,
settings in `router_paths` of `configs/stem-benchmarks.json`), with the T286 prompt filter (0 stops):

| Run | Path | What it does |
|---|---|---|
| `path-deterministic` | model-free solver, then brain-only from certain Claims | no model call; answers or abstains (brain snapshot `stem-t285-2`, `5019e63b…`) |
| `path-notes_model` | notes and model | top notes of the main brain in the prompt, draft, retry of a truncated draft, notes check; no solver |
| `path-model_solver` | model and solver | draft, retry, formalisation and SymPy check on every item, notes in the prompt |
| `path-plain_retrieval` | plain retrieval (baseline b) | top notes in the prompt, one call; no router, no retry, no solver, no check |
| `baseline-thinking_off` | bare model (baseline a, T275) | the question alone, one call |
| `harness-filter-dev` | rule router (baseline c, T278 with the T286 filter) | the class decides: computable formalises, knowledge/reasoning check against notes |

Every route decision now carries its features (`options`, `numeric_option_share`, `question_words`), its rule and the
class; the rules and thresholds (0.5 numeric share, 40 question words) are written down in ADR-026 section 4.1.

The label of an item is the set of paths that answered right: a deterministic path counts only when it answered.
`python scripts/stem_benchmarks.py router-report` writes `data/benchmarks/runs/router-report.summary.json`.

## 2. Baselines on the same items (accuracy, Wilson 95 %)

| Benchmark (dev) | Bare model (a) | Plain retrieval (b) | **Rule router (c)** | Notes and model, every item | Model and solver, every item | Oracle router |
|---|---|---|---|---|---|---|
| MATH-500 (500) | 433, 86.6 % [83.3, 89.3] | 429, 85.8 % [82.5, 88.6] | **455, 91.0 % [88.2, 93.2]** | 448, 89.6 % [86.6, 92.0] | 453, 90.6 % [87.7, 92.9] | 470, 94.0 % [91.6, 95.8] |
| MMLU-Pro STEM (1,175) | 938, 79.8 % [77.4, 82.0] | 936, 79.7 % [77.3, 81.9] | **998, 84.9 % [82.8, 86.9]** | 974, 82.9 % [80.6, 84.9] | 984, 83.7 % [81.5, 85.7] | 1,046, 89.0 % [87.1, 90.7] |
| GPQA main minus Diamond (250) | 123, 49.2 % [43.1, 55.4] | 132, 52.8 % [46.6, 58.9] | **134, 53.6 % [47.4, 59.7]** | 147, 58.8 % [52.6, 64.7] | 140, 56.0 % [49.8, 62.0] | 177, 70.8 % [64.9, 76.1] |

Paired against the rule router (exact McNemar, items right under one only):

| Benchmark | vs bare model | vs plain retrieval | vs notes and model | vs model and solver |
|---|---|---|---|---|
| MATH-500 | 33 / 11, p = 0.001 | 37 / 11, p < 0.001 | 23 / 16, p = 0.34 | 14 / 12, p = 0.85 |
| MMLU-Pro STEM | 84 / 24, p < 0.001 | 88 / 26, p < 0.001 | 58 / 34, p = 0.016 | 50 / 36, p = 0.16 |
| GPQA | 26 / 15, p = 0.12 | 25 / 23, p = 0.89 | **16 / 29, p = 0.07** | 17 / 23, p = 0.43 |

- On MATH and MMLU-Pro the rule router beats both the bare model and plain retrieval with a significant paired
  difference. Plain retrieval alone adds nothing over the bare model there (−4 and −2 items).
- On GPQA the rule router is not distinguishable from plain retrieval, and "notes and model on every item" scored 13
  more (not significant, p = 0.07). The GPQA computable class is the reason (section 3).

**B5 (wrong deterministic answers):** model-free 29 answered on MATH, 29 right, 0 wrong; none on the other two.
Brain-only (off by default since T285) answered 16 on MMLU-Pro with 1 right and 1 on GPQA with 0 right, so it stays off.
No baseline row has a wrong model-free answer.

**Cost and latency** (model calls per item, seconds median / p95 per item under the 64-way load):

| Benchmark | Bare model | Plain retrieval | Rule router | Notes and model | Model and solver |
|---|---|---|---|---|---|
| MATH-500 | 1.00, 36.6 / 106.8 | 1.00, 43.1 / 117.8 | 2.31, 67.4 / 234.4 | 1.09, 46.2 / 230.8 | 2.41, 63.3 / 230.2 |
| MMLU-Pro STEM | 1.00, 46.1 / 128.8 | 1.00, 51.9 / 132.6 | 1.93, 57.7 / 247.3 | 1.17, 57.8 / 256.8 | 2.17, 57.4 / 248.1 |
| GPQA | 1.00, 87.4 / 140.9 | 1.00, 89.5 / 146.8 | 2.02, 100.7 / 274.6 | 1.30, 92.7 / 283.5 | 2.34, 102.8 / 270.4 |

Peak VRAM 14.81-14.90 GB over the four path runs. No p95 meets B4 (180 s); cost belongs to T279.

## 3. Routing accuracy, confusion and the oracle

Routing accuracy is the share of answerable items (some path right) on which the rule router's chosen path is right,
read on the forced-path labels.

| Benchmark | Answerable | Chosen path right | Routing accuracy | Oracle |
|---|---|---|---|---|
| MATH-500 | 470 | 453 | 96.4 % | 470 |
| MMLU-Pro STEM | 1,046 | 988 | 94.5 % | 1,046 |
| GPQA | 177 | 142 | 80.2 % | 177 |

Right answers per path within each class (items; the rule router's choice in bold):

| Benchmark, class | Items | None right | Model-free | Brain-only | Notes and model | Model and solver | Bare model |
|---|---|---|---|---|---|---|---|
| MATH, computable | 500 | 30 | **29** (of 29 answered) | 0 | 448 | **453** | 433 |
| MMLU-Pro, computable | 883 | 96 | 0 | 0 | 728 | **742** | 699 |
| MMLU-Pro, knowledge | 250 | 28 | 0 | 1 | **212** | 205 | 207 |
| MMLU-Pro, reasoning | 42 | 5 | 0 | 0 | **34** | 37 | 32 |
| GPQA, computable | 178 | 53 | 0 | 0 | 102 | **97** | 80 |
| GPQA, knowledge | 20 | 5 | 0 | 0 | **13** | 14 | 12 |
| GPQA, reasoning | 52 | 15 | 0 | 0 | **32** | 29 | 31 |

Read with the noise:

- **The labels are one seeded run each, and the engine is not repeatable at this load.** The rule router and the
  forced path ran the same settings on the same items with the same seeds, yet disagreed on 5.5 % of MATH computable
  items (14 / 12), 6.6 % of MMLU-Pro computable (36 / 22) and **15.2 % of GPQA computable (10 / 17)**. That is why the
  chosen path scores 453 / 988 / 142 on the labels against 455 / 998 / 134 in the rule router's own run.
- **The oracle is an upper bound inflated by that noise:** taking the best of three noisy samples per item rewards
  luck. The 3.0 / 4.1 / 14.4-point gaps between oracle and rule router are not what a router could win.
- The one place where a different choice looks better than its noise is **GPQA computable**: notes and model 102,
  model and solver 97, a 5-item gap inside the 27-item flip of the same configuration. MMLU-Pro reasoning (37 vs 34)
  and GPQA knowledge (14 vs 13) are within one to three items. No class gives a change of rule a measured, significant
  basis. Any change is left to T280 with repeated seeds.

## 4. The router network: dataset and gates

The gates were fixed by the owner on 2026-11-23, before any routing number (`configs/stem-router-gates.json`,
SHA-256 `daa01805…`, committed in `96b3dfbe` before the label runs): held-out share 30 % by seeded hash of the item
id (seed 287), five cross-fitting folds on the rest; N1 a gain of at least 1 point over the rule router with the
paired-bootstrap 95 % lower bound above 0 (2,000 resamples, seed 287); N2 no more wrong model-free or brain-only
answers than the rule router; N3 ECE at most 0.05 (10 bins); N4 below confidence 0.6 the network abstains to the rule
router, and it never overrides a model-free or brain-only answer.

`python scripts/stem_benchmarks.py router-dataset --out data/benchmarks/router/2026-11-24` (outside Git):

| File | Items | SHA-256 |
|---|---|---|
| `pool.jsonl` (training pool, folds 0-4) | 1,376 | `501e4b16e7c6…36d0dd` |
| `heldout.jsonl` (sealed) | 549 | `d1c2f82180ce…57fd1e66` |

Features only (`routing.FEATURES`, 10: open answer, options, numeric share, log question words, quantities, quantities
with a unit, formulas, elements, constants, English), all known before any model call. The two "deterministic path
answered" flags were removed during the task: the network is asked only after those steps found nothing, so their
outcome at training time would not exist at serving time. The router report above covers all development items for
the rule router, the held-out part included; that report is the T287 measurement, the held-out labels were not used
to choose anything, and the network has not seen them.

`router-gates` without a network: **N1-N4 NOT VERIFIED, verdict "NOT VERIFIED: no trained network"**, exit 1.

What to expect, stated before the owner trains: the features read the item's shape only, the labels carry the
engine noise of section 3, and the per-class differences are within it. A pass of N1 (+1 point, lower bound above 0
on 549 items) would need a network that finds structure the classes do not show. A failure is the likely outcome and
leaves the rule router in place.

## 5. Verdict

- Rule router (T278 with the T286 filter) stays: it is the best measured choice on MATH and MMLU-Pro, ahead of the bare
  model and plain retrieval with significant paired differences, and model-free answers stay at 0 wrong.
- On GPQA nothing separates the rule router from plain retrieval; "notes and model" for GPQA computable items is the
  candidate for T280, to be measured with repeated seeds before any rule changes.
- The Phase 57 exit criterion "the router beats the bare model and plain retrieval on development" holds on
  MATH-500 and MMLU-Pro STEM and **does not hold yet on GPQA**; it stays open for T280.
- Network: NOT TRAINED, NOT VERIFIED, NOT PROMOTED. The model and the system are NOT QUALIFIED.

## 6. Owner commands

```bash
python scripts/train_stem_router.py --owner-run --dataset data/benchmarks/router/2026-11-24 \
    --config configs/stem-router-training.json --out data/benchmarks/router/2026-11-24/net.json
python scripts/stem_benchmarks.py router-gates --dataset data/benchmarks/router/2026-11-24 \
    --net data/benchmarks/router/2026-11-24/net.json --report reports/benchmarks/T287-router-gates.json
```

Training is CPU, numpy, seconds; it reads `pool.jsonl` only and checks it against the manifest. Promotion, after a
pass, is setting `harness.router.network` to the network file; it is the owner's decision. See
`docs/development/STEM_ROUTER_RUNBOOK.md`.
