---
document_id: "DOC-ADR-026"
title: "ADR-026: STEM benchmark qualification of the system (light model, harness, RAG, deterministic brain)"
document_type: "adr"
status: "PROPOSED"
version: "0.1.0"
created_at: "2026-11-23"
updated_at: "2026-11-23"
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
change_summary: "Drafted in task T274 from the owner's choices of 2026-11-23: three world STEM benchmarks as gates, MATH-500 at 95 %, the other thresholds fixed after a measured baseline, a light model carried by the harness, RAG and a deterministic brain; protocol, splits, leakage rules, cost and latency measures."
---

# ADR-026: STEM benchmark qualification of the system

## Metadata
- **Status:** PROPOSED on 2026-11-23 (task T274). The owner's choices (section 2) are decided; the protocol in sections 3-8 waits for the owner's acceptance. No benchmark is downloaded and no code is written before acceptance.
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
| B2 | MMLU-Pro STEM accuracy, micro-averaged over items | fixed by the owner after T275 (proposal: bare-model dev baseline + 5 points, capped at the vendor figure + 5) |
| B3 | GPQA Diamond accuracy | fixed by the owner after T275 (same proposal rule) |
| B4 | Cost and latency on this GPU (RTX 5070 Ti, 16 GB): median and 95th-percentile seconds per item, generated tokens per item, peak VRAM | reported for every candidate; thresholds fixed by the owner after T275 |
| B5 | Model-free answers of the brain: share wrong among those it gave, on all three sealed sets | 0 wrong; coverage reported |
| B6 | Leakage: 13-gram overlap between the brain snapshot (and few-shot material) and every benchmark question and option | 0 hits |

- Each accuracy is reported with a 95 % Wilson interval. A gate passes on the point estimate; the interval is shown so
  that a pass on 198 GPQA items is read with its uncertainty.
- B1-B3 are separate gates; the system is qualified on STEM only when B1-B6 all pass. A partial pass is reported as
  such ("qualified on MATH-500"), never as qualification on STEM.
- No threshold is changed after the sealed run without a new ADR.

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

- The owner accepts or changes this ADR; spec decisions D57-D64 and SR-M13 follow it.
- `python scripts/validate_spec.py`, `cargo xtask spec` and `python scripts/validate_docs.py` pass.
