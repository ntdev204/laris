---
document_id: "DOC-ADR-026"
title: "ADR-026: STEM benchmark qualification of the system (light model, harness, RAG, deterministic brain)"
document_type: "adr"
status: "ACCEPTED"
version: "0.6.0"
created_at: "2026-11-23"
updated_at: "2026-11-27"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - ".claude/spec/spec.md"
  - ".claude/spec/plan/1-model.md"
  - ".claude/spec/task/1-model.md"
  - "reports/verification/T228-open-llm-selection.md"
decision_references:
  - "ADR-004"
  - "ADR-008"
  - "ADR-024"
  - "ADR-025"
change_summary: "0.6.0 (2026-11-27, owner): amendment A3, the sealed run is optional for closing and handover; the rule for qualification is unchanged (D68). 0.5.0 (2026-11-24, owner): amendment A2, the time limits of B4 are lifted and the thinking budget may rise to what the VRAM ceiling allows (D67). 0.4.0 (2026-11-24, owner): amendment A1, B3 (GPQA Diamond) leaves the gate and is measured and reported only (D65); Phase 49 cancelled (D66). 0.3.0 (T286, T287, 2026-11-24): section 4.1 writes down the prompt filter and the router rules of the evaluation profile with their thresholds, and the gates of a router network, fixed by the owner before any number (configs/stem-router-gates.json); no gate B1-B6 changed. 0.2.0 (T275, 2026-11-23): the owner fixed B2 at 84.8 % and B4 (median at most 60 s and 95th percentile at most 180 s per item under the baseline load, peak VRAM at most 15.5 GB) from the measured baseline; B3 stays open until GPQA is measured with a thinking budget. 0.1.0: accepted by the owner 2026-11-23 (\"Chấp nhận\"). Drafted in task T274 from the owner's choices of 2026-11-23: three world STEM benchmarks as gates, MATH-500 at 95 %, the other thresholds fixed after a measured baseline, a light model carried by the harness, RAG and a deterministic brain; protocol, splits, leakage rules, cost and latency measures."
---

# ADR-026: STEM benchmark qualification of the system

## Metadata
- **Status:** ACCEPTED on 2026-11-23 by the owner ("Chấp nhận"), as drafted; T275 may start. Any change to D57-D64 or to the gates needs an amendment to this ADR.
- **Requirements:** SR-M13, SR-M2, SR-M3, SR-K4 · **Task:** T274 · **Decisions:** D57-D64 · **Builds on:** ADR-008 (no claim without a held-out gate), ADR-004 (provenance), ADR-024 (brain, write gate), ADR-025 (server pipeline)
- **Qualification:** the model (Qwen3.5-4B, the packaged default since T260) and ResearchLLM as a whole are **NOT QUALIFIED**. This ADR defines how a qualification could be earned; it earns none.

## 1. Context

The owner's direction of 2026-11-23: qualify the system on world STEM benchmarks above 95 %, with a *light* model whose
weakness is made up by a strong harness, retrieval and a brain of verified knowledge that can answer correctly without
the model; the model is to understand the question, reason and write. Compute cost and response time are to be
optimised. The agent may change the system until it qualifies, but may not train (SR-M3).

Facts that bound the target (from the T228 report, vendor figures, not measured by LARIS):

- Qwen3.5-4B card: GPQA Diamond 76.2; Qwen3.5-9B: 81.7. No measurement on this machine exists.
- GPQA is built so that search does not help ("Google-proof"); retrieval adds little there. MMLU-family sets carry
  a share of wrong or ambiguous keys (MMLU-Redux estimates several per cent for MMLU), which caps any honest score.
- Computable problems (competition mathematics, quantitative physics and chemistry) can be checked by a computer
  algebra system, so a deterministic solver can carry them.

## 2. Owner's choices (decided 2026-11-23)

1. Gate benchmarks: **MATH-500**, **MMLU-Pro (STEM categories)**, **GPQA Diamond**.
2. Thresholds: **MATH-500 ≥ 95 %**; MMLU-Pro STEM and GPQA Diamond get realistic thresholds fixed by the owner after the
   measured baseline (T275), before any tuning of the system on them.
3. Approved: SymPy (computer algebra), download of the three benchmarks, OpenStax textbooks (CC BY 4.0) and NIST CODATA
   constants as brain sources. Exact versions are pinned and shown to the owner before install.
4. Model: a light model; the score must come from the harness, RAG and the brain, and both must be optimised.

## 3. Benchmarks and splits

| Gate set | Source (verified at download, T275) | Items | Licence (to verify on the card) | Development split | Sealed test |
|---|---|---|---|---|---|
| MATH-500 | `HuggingFaceH4/MATH-500` (subset of the MATH test set) | 500 | MIT (MATH) | MATH **train** problems, seeded sample of 500, none whose text matches a MATH-500 problem | all 500 |
| MMLU-Pro STEM | `TIGER-Lab/MMLU-Pro`, categories math, physics, chemistry, biology, engineering, computer science | count recorded at download | MIT | seeded 20 % of the STEM test items, stratified by category; the 70 validation items are few-shot material only | the other 80 % |
| GPQA Diamond | `Idavidrein/gpqa` (gated; terms accepted by the owner) | 198 | CC BY 4.0, with the request not to reveal examples online | GPQA **main** items not in Diamond | all 198 |

- Splits are written once by a seeded script, with SHA-256 of every file, under `data/benchmarks/` (outside Git).
  The sealed files are read only by the sealed run (section 7); the runner refuses them otherwise.
- GPQA text never enters Git, reports, logs sent anywhere, or the brain. Reports carry item ids and scores only.
- Answer options of GPQA are shuffled with a fixed, recorded seed; MMLU-Pro keeps its order.

## 4. What "the system" is when measured

The measured unit is the **whole request pipeline** (ADR-025) in an evaluation profile, not the bare model:
Prefilter → STEM router → deterministic solver → retrieval over the main brain → model with the harness loop → answer
check → final answer. Rules:

- One final answer per item (pass@1). Internal sampling, self-consistency, solver calls and retries are allowed and
  are counted in the cost (section 6); choosing among answers with the gold key is not.
- An abstention, an unparseable answer or a timeout scores **0**.
- **No web, no paper search, no network** during gate runs: the only knowledge is the model's weights and the frozen
  brain snapshot (its hash is recorded). Any tool that reaches the internet is off.
- The evaluation profile may answer without citations (a letter or a number is the answer); the evidence gate stays
  on in normal chat. The brain snapshot, configuration and model files are frozen and hashed before the sealed run.
- Model: the light model chosen in T279 from measurements; the default candidate is Qwen3.5-4B. A larger model is not
  used unless the owner changes decision 4.

### 4.1 Prompt filter and router of the evaluation profile (T286, T287)

Written down here as the rules in force; the thresholds live in configuration only.

- **Prompt filter** (T286, `configs/prompt-filter.json`): every prompt passes it before retrieval, the router and the
  model. It normalises the text (each change named), stops injected instructions and out-of-scope prompts by named
  rule (the owner's Prefilter rules of kinds injection and refusal, read from `.laris/prefilter.toml`, then the
  profile's rules), and extracts language, quantities, formulas and constants as fields. A stop scores 0. It never
  answers and is never handed the gold answer.
- **Router rules** (T278, `harness.router` of `configs/stem-benchmarks.json`), read from the item's shape only:
  1. no options -> `computable` (`open_answer`);
  2. options with a digit in at least `numeric_option_share` (0.5) of them -> `computable` (`numeric_options`);
  3. a question of at most `knowledge_max_question_words` (40) words -> `knowledge` (`word_options_short_question`);
  4. otherwise -> `reasoning` (`word_options_long_question`).
  Every decision records its rule and its features (options, numeric option share, question words).
- **Paths per class**: `computable` without options tries the model-free solver first (a verified result is the
  answer, B5); `computable` then drafts and formalises, and the solver checks the draft; `knowledge` and `reasoning`
  draft with notes of the frozen snapshot and the notes check. The brain-only answer (T285) is off until B5 holds on
  development.
- **A router network** (T287) may replace the rules only through the gates the owner fixed on 2026-11-23, before any
  routing number (`configs/stem-router-gates.json`), on a held-out 30 % of the development pool sealed by hash before
  training: N1 a gain of at least 1 point over the rule router with a paired bootstrap 95 % lower bound above zero
  (2,000 resamples, seeded); N2 no more wrong model-free or brain-only answers than the rule router; N3 expected
  calibration error at most 0.05; N4 below confidence 0.6 the network abstains to the rule router, and it never
  overrides a model-free or brain-only answer. It reads features only (no free text), is trained by the owner only
  (SR-M3), and replaces the rules only when every gate passes and the owner promotes it.

## 5. The deterministic brain ("answers without the model")

- **Solver layer** (Python model block, SymPy, served as a remote tool, SR-M2): units and dimensional analysis,
  CODATA constants, exact and numeric algebra, calculus, equation solving, linear algebra, number theory,
  stoichiometry. A solver result is *verified* only when it is re-checked by an independent route (substitution back,
  numeric evaluation at random points, unit consistency); otherwise it is a proposal.
- **Verified knowledge** enters the main brain only through the write gate (SR-K3) with provenance: source, licence,
  location, hash. Certainty is that of the source and of the check; the system guarantees faithfulness to sources and
  to the computation, not truth of the world (ADR-024).
- **Model-free answers**: when the router can map a question to a solver call or an accepted claim without the model,
  the brain answers alone. Its gate is precision, not coverage: a model-free answer that is wrong fails B5.

## 6. Gates

| Gate | Measure on the sealed test | Threshold |
|---|---|---|
| B1 | MATH-500 accuracy (answer equivalence by SymPy plus normalised string, protocol frozen in T275) | ≥ 95.0 % |
| B2 | MMLU-Pro STEM accuracy, micro-averaged over items | **≥ 84.8 %** (fixed by the owner 2026-11-23: bare-model dev baseline 79.8 %, thinking off, + 5 points; T275 report) |
| B3 | GPQA Diamond accuracy | **removed from the gate by amendment A1 (D65); measured and reported only.** Was: open, fixed by the owner after GPQA is measured with a thinking budget (the thinking-off dev baseline, 49.2 %, is far below the model's vendor figure; T275 report) |
| B4 | Cost and latency on this GPU (RTX 5070 Ti, 16 GB): median and 95th-percentile seconds per item, generated tokens per item, peak VRAM | per benchmark, under the baseline's load (64 concurrent requests): **median ≤ 60 s, p95 ≤ 180 s per item, peak VRAM ≤ 15.5 GB** (fixed by the owner 2026-11-23); generated tokens reported |
| B5 | Model-free answers of the brain: share wrong among those it gave, on all three sealed sets | 0 wrong; coverage reported |
| B6 | Leakage: 13-gram overlap between the brain snapshot (and few-shot material) and every benchmark question and option | 0 hits |

- Each accuracy is reported with a 95 % Wilson interval. A gate passes on the point estimate; the interval is shown so
  that a pass on 198 GPQA items is read with its uncertainty.
- B1-B3 are separate gates; the system is qualified on STEM only when B1-B6 all pass. A partial pass is reported as
  such ("qualified on MATH-500"), never as qualification on STEM.
- No threshold is changed after the sealed run without a new ADR.

## 6.1 Amendment A1 (owner, 2026-11-24, before any sealed run)

- **D65.** B3 is removed from the gate. GPQA Diamond is still run on the sealed set with the same cost record and a
  Wilson interval, and is reported next to the gates, but it neither passes nor fails the system. The gates are
  B1, B2, B4, B5, B6. The threshold of none of them is changed (B1 stays at 95.0 %).
- Wording that follows: the system may be called **"qualified on MATH-500 and MMLU-Pro STEM"** when B1, B2, B4-B6 all
  pass; it must not be called qualified on GPQA, and the GPQA figure must be shown. A partial pass is reported as
  such. The agent never writes "qualified" before the sealed result and the owner's record say so.
- **D66.** Phase 49 (T245-T248, a model family with per-request choice) is cancelled: one light model (D64).
- Sealed runs: the owner authorises the agent to set `LARIS_STEM_SEALED_ORDER` once per frozen candidate (at most
  three) when the candidate's development result is stable over three seeds; every result is reported, failures
  included.

### Amendment A2 (owner, 2026-11-24, before any sealed run)

- **D67.** B4 keeps **peak VRAM ≤ 15.5 GB** and drops its median and p95 time limits (60 s / 180 s). Median and p95
  seconds, generated tokens and model calls per item are still measured and reported with every result; they no
  longer pass or fail the system. Any chat-side latency promise is a separate matter of the product, not of this gate.
- The thinking budget (and the token caps of the draft, conclusion and samples) may be raised as far as the VRAM
  ceiling allows. The engine's VRAM is fixed by `--gpu-memory-utilization` and the weights; a longer context or
  budget uses the preallocated KV cache, so it costs time and concurrency, not memory. Every value is fixed on
  development before a sealed run and written into the frozen candidate.
- The gates are now B1, B2, B4 (VRAM only), B5, B6.

### Amendment A3 (owner, 2026-11-27, before any sealed run)

- **D68.** The sealed run (T281) is optional: it may be run or left out, and closing or handing over the project does
  not wait for it. Gates, thresholds and wording are unchanged: without a sealed result and the owner's record, the
  model and the system are **NOT QUALIFIED**, and development figures are reported as development figures.

## 7. Development and the sealed run

- All tuning (prompts, routing, retrieval, solver, sampling, thinking budget, quantisation) uses the development splits
  only. The sealed test is run **once per frozen candidate**, on the owner's order; at most three candidates are
  sealed-run in this phase, and every sealed result is reported, including failures.
- Running the model for evaluation is inference and is allowed to the agent; no training, fine-tuning, adapter,
  backward step or optimiser-bearing profile is run (SR-M3). Learning data stays outside Git.

## 8. Cost and response time

Measured on the development splits, per item: wall time, prompt and generated tokens, model calls, solver calls,
peak VRAM. Levers to compare (T279): route computable items to the solver before the model; a thinking budget per
router class; early exit when the solver's verified answer and the model's draft agree; self-consistency only when
the first answer is uncertain; quantisation (BF16 / 8-bit / 4-bit) of the light model; prompt prefix caching.
A lever is kept only when its measured accuracy change on development is not negative beyond noise, or the owner
accepts the trade.

## 9. Decisions

| ID | Decision | Choice | Alternative not taken |
|---|---|---|---|
| D57 | Gate benchmarks | MATH-500, MMLU-Pro STEM, GPQA Diamond | One benchmark only: no picture of knowledge vs reasoning |
| D58 | Thresholds | B1 ≥ 95 %; B2, B3, B4 fixed by the owner after the T275 baseline and before tuning | 95 % on all: GPQA Diamond at 95 % is far above every figure in the T228 report (best 82.3) and near the noise of its own keys |
| D59 | Measured unit | The whole pipeline in an evaluation profile, pass@1, abstention scores 0 | Bare model: does not measure the harness and brain |
| D60 | Closed book | No network or web tools during gate runs; frozen, hashed brain snapshot | Open web: answers could be found online, the score would not measure the system |
| D61 | Splits | Development from MATH train, a seeded 20 % of MMLU-Pro STEM, GPQA main minus Diamond; sealed test run once per frozen candidate | Tuning on test: invalidates the gate |
| D62 | Deterministic brain | SymPy solver as a remote tool plus verified notes through the write gate; model-free answers gated on precision (B5) | Model-only: no correctness guarantee |
| D63 | Leakage | 13-gram scan, zero hits (B6); GPQA text never in Git, reports or the brain | Trusting source separation without a scan |
| D64 | Model size | Light model (default candidate Qwen3.5-4B), chosen in T279 from measured accuracy, latency and VRAM | 9B or larger: against the owner's decision 4 |

## 10. Consequences

- New tasks T275-T281 (Phase 57, programme 1). New requirement SR-M13.
- A failure of B2 or B3 at the owner's threshold is a measured result, not a reason to change the threshold.
- If B1 cannot reach 95 % with the light model after T280, the options are reported to the owner (a larger model,
  more solver coverage, or a recorded FAIL); none is taken without the owner.

## 11. Risks

- Router errors send a conceptual question to the solver: guarded by the solver's verification and by the model's
  review of a solver answer against the question.
- Answer-equivalence checking can wrongly accept or reject: the checker is tested on fixtures and frozen before the
  baseline.
- Thinking mode makes long outputs: B4 makes the cost visible; a cap that lowers accuracy is reported, not hidden.
- GPQA has 198 items: one item is about 0.5 point; the interval is reported.

## 12. Validation

- 2026-11-23 (T275): B2 and B4 fixed by the owner from the measured baseline (`reports/benchmarks/T275-baseline.md`); B3 open.
- 2026-11-23 (T277): the live OpenStax STEM editions are CC BY-NC-SA 4.0 (repository metadata and the openstax.org
  catalogue agree); within choice 3 the owner took each book from the newest git commit at which it was CC BY 4.0
  (18 books pinned in `configs/stem-brain.json`; Calculus 1-3 and Organic Chemistry never were CC BY and are not used).
  The snapshot build leaves out every text block that shares a 13-word sequence with a benchmark item (B6).

- 2026-11-24 (T286, T287): section 4.1 records the filter, the router rules and the network gates; reports
  `reports/benchmarks/T286-filter.md` and `T287-router.md`.

- 2026-11-24 (T279): the levers of section 8 measured on development (`reports/benchmarks/T279-cost.md`): solver
  first, early exit and FP8 kept (accuracy within noise); escalation to budgeted thinking and a thinking budget for
  every draft rejected (accuracy lower beyond noise); repetition stop and prefix caching off without measured gain;
  self-consistency raises accuracy at about twice the p95, left to the owner. Candidate p95 180.6 / 196.0 / 206.9 s,
  over B4's 180 s; medians 19.2 / 24.1 / 53.2 s and peak memory 14.9 GB within B4.
- 2026-11-24, owner's decisions on T279: (1) self-consistency is kept: its p95 cost (274 / 383 / 399 s with FP8 and
  early exit) is accepted as the trade for its accuracy (section 8); B4 itself is unchanged and is still judged on the
  sealed run; (2) one precision, FP8, for chat and evaluation: the vLLM server of `docker/compose.chat.yaml` serves
  online FP8. The evaluation profile is now solver first + early exit + self-consistency on FP8.

- Accepted 2026-11-23: spec decisions D57-D64 and SR-M13 are recorded in the spec.


- The owner accepts or changes this ADR; spec decisions D57-D64 and SR-M13 follow it.
- `python scripts/validate_spec.py`, `cargo xtask spec` and `python scripts/validate_docs.py` pass.

- 2026-11-24 (T280): development iterations (`reports/benchmarks/T280-iterations.md`): concluding a cut reply in place
  of the retry and a 2,048-token thinking budget on the knowledge class kept; frozen candidate code `77546576`, harness
  section `3dddd9ab…`, brain `stem-t277-2`, Qwen3.5-4B `851bf6e8…` in FP8. On development B1 stays below 95 %
  (89.8-92.6 %) and B4's p95 is not met; under section 10 the options are the owner's. Concluded answers are guesses
  (about half right) and are recorded per item.
