# LARIS — Plan 1: Model (ResearchLLM)

Version 2.0.0-draft · 2026-11-13 · Implements [spec.md](../spec.md) sections 5.3, 7.7 and 7.8; tasks in
[task/1-model.md](../task/1-model.md). Highest priority of the three programmes (spec section 2).

## 1. How this programme works

- Agents prepare: code, data pipelines, configurations, evaluators, readiness checks, exact owner-run commands with
  budget, timeout and expected outputs. Agents never train, fit, profile with an optimiser, or set
  `LARIS_TRAINING_AUTHORIZED` (SR-M3).
- The owner runs every owner-run step and returns logs, manifests and reports; the next task checks them first.
- A stage starts only after the previous stage passed all its gates on held-out data and the owner recorded the
  promotion. Validation results guide development; they never qualify a stage.
- While a task waits for the owner (a run, labels, a decision), the agent may work on programme 2 system and server
  phases (spec section 2), one task per branch.
- Each task ends with ruff, mypy, the non-training tests of the model block, the spec validator and a pull request into
  `laris-v2`.

## 2. Phases

### Phase 19 — Ledger and model decisions
Goal: the ledger exists, ResearchLLM is defined, and the model block can be verified on `laris-v2` without training.
Tasks: T92, T93, T94
Exit criteria:
- The validator passes on the spec and all plan and task files.
- ADR-020 fixes what ResearchLLM is (D44): stages, the stage-6 advisor architecture options, size, data and compute
  envelope on the target GPU, and its gates.
- One command runs the model block's non-training checks on `laris-v2`.

### Phase 20 — Stage 1: foundation encoder (English since D46)
Goal: the foundation encoder passes its English gates (G01, G03-G07, G10, G12; G02, G08, G09, G11 withdrawn by D46) on held-out data.
Tasks: T95, T96, T97, T98
Exit criteria:
- Every gate G01-G12 has a valid measurement protocol (no NOT VERIFIED left).
- Data corrections are frozen with lineage; the tokenizer meets G10 and G11; human STEM relevance exists for G12.
- The readiness check exits 0 on held-out reports and the owner records the promotion.

### Phase 41 — Stage 1 re-scope to English (D46, ADR-022)
Goal: gates and data match an English-only foundation encoder; Vietnamese is left to a translation layer.
Tasks: T173, T174, T175, T176, T177, T178, T179, T180, T181, T182, T183, T184, T190, T191
Exit criteria:
- Withdrawn gates are recorded, none relaxed or marked passed.
- English replacement data (MLM text, similarity beyond STS-B, NLI, paraphrase, QA, retrieval; at least 20 GB) is acquired with provenance, leakage-checked against STS-B, and partitioned.
- Every normative document and configuration that mentioned Vietnamese in stage 1 is amended or marked historical; withdrawn gates stay listed.
- A new English tokenizer and encoder exist from an owner run.

### Phase 42 — NLP techniques: TF-IDF, word embeddings, NER token classification
Goal: TF-IDF and word vectors are reusable model-block functions, and the existing encoder gets a token-classification
(NER) head trained on a public dataset whose licence the owner approved; stage-1 checkpoints and gates stay unchanged.
Tasks: T185, T186, T187
Exit criteria:
- The NER data licence review is written and the owner has chosen the source; nothing is downloaded before that
  (CoNLL-2003 English needs the Reuters/NIST agreement and is not used without it).
- TF-IDF and word vectors (static from the token embedding table, contextual from encoder states) are tested without
  new dependencies and without training.
- The NER head lives in a wrapper around the encoder, so stage-1 checkpoints load unchanged; label alignment and the
  entity-level F1 evaluator are tested on fixtures.
- The NER fine-tune and its held-out evaluation are owner runs; the result is reported as "measured on" the chosen
  test split. NER has no qualification gate: adding one needs an ADR and a spec amendment.

### Phase 43 — Pair-task remediation: self-supervised two-segment objectives, contrastive similarity, mixed batches, staged training
Goal: the encoder body learns to compare two segments and the four pair tasks get data and objectives that can teach it,
before any main run. Owner direction 2026-11-14: no training now, solve the data problem first; 2026-11-15: combined route
(two-segment self-supervision, contrastive similarity without bought labels, mixed batches, two-stage schedule), planned step by step.
Tasks: T192, T193, T194, T195, T196, T197, T198, T199, T200, T201, T202, T203, T204, T205, T206, T207, T208, T210, T211, T212, T213, T216, T218, T219
Execution order (each step needs the previous ones; no step before T204 trains): T192 data on disk (done) -> T193 audit (done) -> T206 data corrections (done) ->
T194 two-segment builder (done) -> T195 order head (done) -> T196 balanced NLI and paraphrase (done) -> T197 relation pairs (done) -> T198 bi-encoder head (done) ->
T199 contrastive objective (done) -> T200 paraphrase and QA data (done) -> T201 mixed batches (done) -> T207 data decisions (done) -> T202 owner profile (done, tasks_per_step 2) -> T208 LLM similarity labels (done) -> T203 mixture and schedule (done, proposal) -> T209 owner profile on a shared GPU, T210 Colab A100 transfer -> T211 device ceiling and A100 speed profile -> T212 stage-1 rerun on the corrected data (done) -> T213 prefetching loader ->
T204 owner stage-2 and control runs (done) -> T205 analysis and decision (done) -> T216 longer stage-2 run (done: stopped at step 1,040 by the owner, QA not measured) -> T218 interim model for the first system version (owner decision 2026-11-20: first version runs on the stage-2 checkpoint; the foundation stays NOT QUALIFIED) -> T219 plan of the 100,000-step extended run in five chunks (budget 48-52 h) -> T220 resume check -> T221-T225 chunks 1-5 (gate at T222) -> T226 analysis and decision.
Exit criteria:
- Extra raw data is on disk with provenance and licence status (T192) and the audit (T193) states per source the label prior, shortcut baselines, truncation, duplicates and held-out overlap.
- Two-segment inputs (pair-format MLM and sentence order) exist behind options that default to off (T194, T195), and NLI and paraphrase batches can be source- and label-balanced (T196).
- Similarity gets relation pairs and a bi-encoder head without bought labels, with a zero-hit leakage rescan against STS-B validation and test (T197 to T199); STS-B stays the only gate data.
- QA and paraphrase formatters and re-weighting exist and are measured (T200); mixed batches exist behind `tasks_per_step` (T201, done; estimate only until the T202 owner profile).
- No task before T204 runs training, tokenizer fitting or a backward step; T202 and T204 are owner runs started only on the owner's order. The foundation model stays NOT QUALIFIED.

### Phase 44 — ResearchLLM on an open-weight LLM (D48)
Goal: an open-weight reasoning LLM, with a Prefilter, lexical retrieval, a harness loop and the Obsidian brain, replaces the self-trained model.
Tasks: T227, T228, T229, T230, T231, T232, T233, T234, T235
Exit criteria:
- The chat route answers from a third-party open-weight model chosen by the owner; answers cite vault passages or abstain.
- The self-trained model code is removed; learning export is kept. No model is declared qualified by this phase.
