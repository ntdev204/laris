# T276 — Deterministic STEM solver: the model-free path on the development splits

Date measured: 2026-11-23. Measured by LARIS on this machine (CPU only; no model, no GPU). Development splits only; no
sealed file was read. This measures the **solver's model-free path alone** (strict question patterns, then the
solver), not the system: the model (Qwen3.5-4B) and the system are **NOT QUALIFIED**. Item text is not reproduced
here.

## Set-up

| | |
|---|---|
| Solver | `laris.model.solver` (tool `solve_stem`), SymPy 1.14.0, mpmath 1.3.0, CODATA 2022 table SHA-256 `77fb90e6…3f67e67` |
| Settings | `configs/default.yaml` `model_service.solver_*`: forked worker per call, 10 s, 2 GiB, checks at 50 digits, 6 seeded points (seed 276) |
| Path | `laris.research.stem.formalise` (SHA-256 `c8e5d832…`): a MATH question is formalised only when the **whole** question matches one of 11 patterns and its LaTeX uses only the converter's subset; the item is **answered** only when the solver's status is `verified` |
| Scoring | protocol `math-equiv-1` of T275 (`answers.py` SHA-256 `60f09b90…`), pass@1 against the gold answer |
| Command | `python scripts/stem_benchmarks.py solver` (records in `data/benchmarks/runs/solver-dev.jsonl`, outside Git) |

## Result

| Benchmark (dev) | Items | Formalised | Answered (verified) | Correct | Precision | Wilson 95 % | Coverage |
|---|---|---|---|---|---|---|---|
| MATH | 500 | 29 | 29 | 29 | **100 %** | 88.3-100 | 5.8 % |
| MMLU-Pro STEM | 1,175 | 0 | 0 | — | — | — | 0 % |
| GPQA (main − Diamond) | 250 | 0 | 0 | — | — | — | 0 % |

By pattern (MATH): evaluate 17/17, gcd 3/3, expand 2/2, solve for one variable 2/2, remainder 2/2, base conversion
1/1, sum of proper divisors 1/1, largest prime factor 1/1. Every formalised item was verified; none was refused or
left a proposal.

Cost: the 29 answered items took 0.015 s median and 0.05 s at the 95th percentile (worker included), with 0 generated
tokens. On the same 29 items the bare model of T275 (thinking off, 64 concurrent requests) answered 28 correctly
(one truncated at 4,096 tokens), 20.0 s median per item and 20,581 generated tokens in total.

## Reading

- The model-free path is precise on what it accepts (29 of 29) and covers little (5.8 % of MATH dev). B5 asks for no
  wrong model-free answer on the sealed sets; 29 is too few to bound that rate tightly (the interval's lower end is
  88.3 %), so the patterns stay strict.
- MMLU-Pro and GPQA questions are prose with options: no pattern applies, by design. Their solver use goes through the
  router's formalisation by the model (T278), where the solver's `verified` status is a check of a draft, not an
  answer on its own.
- One converter fault was found while measuring and fixed before this run: `\cdots` was read as `\cdot` followed by a
  letter. The item was refused anyway (a free letter), so no wrong answer was produced; a test now covers it.
- Atomic weights are not shipped (no approved source), so stoichiometry gives masses only from molar masses the caller
  supplies.
