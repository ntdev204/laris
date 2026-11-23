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

## All of MATH train (7,500 problems), 2026-11-23

The owner asked to measure all of MATH. The sealed MATH-500 test is not read (only a sealed run ordered by the owner
opens it), so "all of MATH" here is the whole development pool: the 7,500 MATH **train** problems (none matches a
MATH-500 question by normalised text), of which the 500 development items are a seeded sample. Same settings and
protocol as above, after two formaliser fixes found by this run (below). Records:
`data/benchmarks/runs/solver-math-train.jsonl` (outside Git); wall 28.6 s.

| Set | Items | Formalised | Answered (verified) | Correct (`math-equiv-1`) | Precision | Wilson 95 % | Coverage |
|---|---|---|---|---|---|---|---|
| MATH train, all | 7,500 | 339 | 321 | 321 | **100 %** | 98.8-100 | 4.3 % |
| of which the 500 dev items | 500 | 29 | 29 | 29 | 100 % | 88.3-100 | 5.8 % |

Not answered among the formalised: 14 proposals (mostly `solve_for` whose completeness could not be checked), 3 refused
as too large, 1 complex branch (below). By subject, answered/correct: Algebra 100/98, Prealgebra 107/107, Counting &
Probability 31/31, Geometry 23/23, Number Theory 30/30, Precalculus 24/24, Intermediate Algebra 5/5 (after the
fixes). Answered items took 0.08 s median, 0.09 s at the 95th percentile, in the forked worker.

The first pass (before the fixes) answered 323 with 4 scored wrong. Reading them:

- `(-27)^{5/3}`: SymPy's principal branch, `-243 (-1)^(2/3)`, is complex; MATH means the real cube root, -243. Fixed:
  a result with a complex unit when the question has no `i` gives no answer (`complex_branch`).
- `6 \cdot 8\frac{1}{3}`: a mixed number (8 1/3) was read as a product. Fixed: a number directly followed by a
  fraction is refused.
- Two `expand` answers are mathematically right (term by term equal to the gold) but were scored wrong: the frozen
  checker does not parse an expression with more than three powers, and the strings differ only in spelling
  (`5 x^{9}` / `5x^9`). Owner decision (2026-11-23): write the answer as MATH writes it. `math_style` drops
  `\left`/`\right`, the braces of a one-character exponent or subscript, and spaces (keeping the one that ends a
  command before a letter); the protocol is unchanged.

After that change: **321 answered, 321 correct** (precision 100 %, Wilson 98.8-100, coverage 4.3 %); the 500 dev items
stay at 29/29.
