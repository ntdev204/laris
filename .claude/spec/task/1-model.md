# LARIS — Tasks 1: Model (ResearchLLM)

Version 2.0.0-draft · 2026-11-13 · Implements [plan/1-model.md](../plan/1-model.md) for [spec.md](../spec.md).

Status values: `pending`, `in_progress`, `done`, `blocked` (waiting for the owner). A task is `done` only when every
deliverable and validation item holds and a completion note is written. Run `python scripts/validate_spec.py` after each
task. A task marked **owner run** contains steps only the owner executes; the agent prepares the commands and checks the
returned logs, manifests and reports.

## Phase 19 — Ledger and model decisions

### T92 — Ledger of generation 2
- Requirements: SR-G1
- Depends: none
- Deliverables:
  - `.claude/spec/spec.md` (single specification), `plan/{1-model,2-system,3-brain}.md`, `task/{1-model,2-system,3-brain}.md`
  - `scripts/validate_spec.py` restored from `laris-v1` and extended: several plan and task files, task ids unique across
    files, exactly one known `Owner:` per requirement
- Validation:
  - Validator passes; seeded errors (no owner, two owners, unknown owner, duplicate task id across files) are reported
- Status: done
- Note: Owner authorised commit and merge on 2026-11-13. Validator passes (81 tasks) and reports the four seeded errors
  (no owner, two owners, unknown owner, duplicate task id across files); ruff and mypy pass on the script. Merged into
  `laris-v2` from `feature/T92-rust-ledger`.

### T93 — ADR-020: what ResearchLLM is
- Requirements: SR-M11, SR-M3
- Depends: T92
- Deliverables:
  - `docs/adr/ADR-020-researchllm.md`: the six stages and their gates (training specification section 8); options for the
    stage-6 generative advisor under ADR-002 (decoder on the shared tokenizer, encoder-decoder on the foundation encoder,
    retrieval-conditioned generation), each with parameter count, training-token budget, measured-or-estimated compute on
    the RTX 5070 Ti (16 GB), and the risk that a small self-built generator stays weak as an advisor
  - Stage-6 gate list (faithfulness, citation accuracy, unsupported-claim rate, tool-call validity, plan quality, EN and VI)
    with thresholds the owner sets
  - `docs/adr/README.md` index entry
- Validation:
  - The owner chooses the option and the thresholds in writing; estimates are labelled as estimates
- Status: blocked
- Note: Draft `docs/adr/ADR-020-researchllm.md` (status PROPOSED) with five stage-6 options (A1-A3, B, C), estimates
  labelled, the weak-generator risk, a recommendation (Option C on A2) and proposed gates S6-1 to S6-6. Waiting for the
  owner to choose the option and the thresholds in writing (section 6 of the ADR); it becomes `done` then. Merged into
  `laris-v2` as a draft.

### T94 — Model-block verification on `laris-v2`
- Requirements: SR-G3, SR-M3
- Depends: T92
- Deliverables:
  - One command (script) that runs ruff, mypy and the non-training tests of `src/laris` on `laris-v2`; a list of tests that
    train or profile, excluded and named
  - A no-training guard that fails when a check sets `LARIS_TRAINING_AUTHORIZED` or calls a training entry point
- Validation:
  - The command passes on `laris-v2`; a seeded training call is caught; the result is recorded in a report
- Status: done
- Note: `scripts/verify_model_block.py` passes on `laris-v2` (ruff, mypy on 187 files, 1259 tests); report in
  `reports/verification/T94-model-block-verification.md`. 10 training/profiling test files and 3 obsolete files are
  excluded and named; the seeded cases are in `tests/unit/scripts/test_verify_model_block.py`. Merged into `laris-v2`.

## Phase 20 — Stage 1: foundation EN/VI

### T95 — Stage-1 audit and missing measurements
- Requirements: SR-M6, SR-M12
- Depends: T94
- Deliverables:
  - Gate-by-gate audit of G01-G12 against the latest reports (F04, F06, F07): measured, NOT VERIFIED, or protocol missing
  - Evaluator and readiness support for every missing protocol (PAWS macro F1, normalized-answer QA, unseen-text fertility)
- Validation:
  - Readiness tests with seeded faulty reports (missing metric, validation-only, mixed checkpoints) reject them
- Status: done
- Note: Audit in `reports/verification/T95-stage1-gate-audit.md`. No gate has held-out encoder evidence; G10 (1.420) and
  G11 (1.363) are the only test-split measurements and both fail 1.35 (tokenizer R1, T97). The three named protocols
  (PAWS macro F1, normalized-answer QA, unseen-text fertility) already had evaluator support; the gap is measurement,
  so only two readiness regression cases were added. Foundation model remains NOT QUALIFIED. Merged into `laris-v2`.

### T96 — Frozen data corrections and corpus review
- Requirements: SR-M4
- Depends: T95
- Deliverables:
  - New dataset versions fixing STS-B train/test overlaps and ViQuAD offsets, with lineage and checksums
  - Review of the owner's branch `wip/corpus-acquisition-changes` (`b9a629f`) and a proposal to integrate or drop each file
- Validation:
  - `data check --verify-sha256` passes; partition isolation re-verified; no test data used for tuning
- Status: done
- Note: Revision `r1` in `data/processed/r1/` (outside Git; originals untouched and re-verified): STS-B cross-split pairs
  removed from train (-9) and val (-3), test unchanged; 9 ViQuAD answer offsets corrected (val 5, test 4), nothing
  dropped. `data check --verify-sha256` passes on both directories and overlaps and offsets were recomputed. Lineage and
  review in `reports/verification/T96-data-corrections*.{json,md}`. The review of `wip/corpus-acquisition-changes`
  proposed integrating all four files with one manifest status fix; the owner approved on 2026-11-13 and branch `feature/T96-corpus-integration` integrated them (S2ORC status `DOWNLOADED`, acquired-samples total 8,315,483). Earlier
  STS-B and ViQuAD validation numbers are not comparable with r1. Merged into `laris-v2`.

### T97 — Tokenizer R1 (owner run)
- Requirements: SR-M5, SR-M3
- Depends: T96
- Deliverables:
  - Prepared F06-R1 commands (corpus preparation, fit, comparison on the locked development sample) with CPU budget
  - Intake check of the owner's fit: checksums, special-token contract, fertility on the development sample
- Validation:
  - The owner approves the budget and runs the fit; the candidate is compared under the frozen protocol; lineage review
    done if the vocabulary changes
- Status: done
- Note: The owner's fit (2026-11-11, 48k vocabulary, digits not split) was taken in, not repeated: `scripts/tokenizer_intake.py`
  passes (checksums, 48,000-piece contract equal to the model, special ids 0-7 unchanged, token and unknown counts and
  development fertility EN 1.2996 / VI 1.1848 recomputed and equal to the report); report in
  `reports/verification/T97-tokenizer-r1-intake.md` with the lineage review (encoder re-initialised, memory profile to
  redo in T99, held-out G10 and G11 still unmeasured). Owner confirmation of the intake is the one open item.

### T98 — Human STEM relevance for G12
- Requirements: SR-M6, SR-M4
- Depends: T95
- Deliverables:
  - D05 retrieval-relevance phase opened with the owner: guideline, units, splits frozen and hashed before labelling;
    annotation tooling and agreement computation (weighted kappa)
- Validation:
  - Owner assigns annotators; agreement ≥ the D05 threshold; the test split is sealed; agents generate no labels
- Status: pending

### T99 — Foundation training rounds (owner run)
- Requirements: SR-M6, SR-M3
- Depends: T97, T98
- Deliverables:
  - Runbook section with the approved curriculum, budget, timeouts and stop rules for the R1 tokenizer encoder
  - Intake check of returned logs, checkpoints and manifests; validation analysis per gate
- Validation:
  - Logs and manifests match; validation results reported per gate; the owner decides on another round or held-out evaluation
- Status: pending

### T100 — Stage-1 held-out evaluation and promotion
- Requirements: SR-M6, SR-M12
- Depends: T99
- Deliverables:
  - Prepared held-out evaluation commands (owner run, once per candidate); readiness report
- Validation:
  - The readiness check exits 0 on held-out reports; the owner records the stage-1 promotion; otherwise the task records
    NOT QUALIFIED and returns to T99
- Status: pending

## Phase 21 — Stage 2: scientific language

### T101 — Scientific datasets and evidence gold
- Requirements: SR-M7, SR-M4
- Depends: T100
- Deliverables:
  - Licensed scientific corpora and SciFact-style NLI data with provenance; D05 evidence gold (claim, passage, span,
    SUPPORT, CONTRADICT, INSUFFICIENT_EVIDENCE) frozen before labelling
- Validation:
  - Manifests and checksums; agreement thresholds met; test sealed
- Status: pending

### T102 — Scientific adaptation pipeline
- Requirements: SR-M7
- Depends: T101
- Deliverables:
  - Objectives, data loaders, evaluator and readiness gates for stage 2 starting from the promoted stage-1 checkpoint
- Validation:
  - Non-training tests (shapes, loaders, evaluator on fixtures) pass
- Status: pending

### T103 — Stage-2 training (owner run)
- Requirements: SR-M7, SR-M3
- Depends: T102
- Deliverables:
  - Prepared commands with budget and stop rules; intake check of the returned artifacts
- Validation:
  - Logs and manifests match; validation analysis per gate
- Status: pending

### T104 — Stage-2 held-out evaluation and promotion
- Requirements: SR-M7, SR-M12
- Depends: T103
- Deliverables:
  - Held-out evaluation commands (owner run) and readiness report
- Validation:
  - SciFact NLI macro F1 ≥ 0.82, evidence precision and recall ≥ 0.80; owner promotion or NOT QUALIFIED
- Status: pending

## Phase 22 — Stage 3: scientific OCR

### T105 — OCR data, gold and design
- Requirements: SR-M8, SR-M4
- Depends: T104
- Deliverables:
  - Design note (model family under ADR-002, input resolution, layout classes); licensed page images; D05 OCR text and
    layout gold
- Validation:
  - Gold agreement (CER ≤ 0.5 %, IoU ≥ 0.92) between annotators; test sealed
- Status: pending

### T106 — OCR pipeline
- Requirements: SR-M8
- Depends: T105
- Deliverables:
  - Model code, loaders, CER and layout evaluators, readiness gates; a tool route for ingestion (SR-H13)
- Validation:
  - Non-training tests on fixtures
- Status: pending

### T107 — OCR training and held-out evaluation (owner run)
- Requirements: SR-M8, SR-M12
- Depends: T106
- Deliverables:
  - Prepared training and evaluation commands; intake checks; readiness report
- Validation:
  - CER ≤ 1.5 % clean and ≤ 3.0 % degraded, layout IoU ≥ 0.88 on held-out data; owner promotion or NOT QUALIFIED
- Status: pending

## Phase 23 — Stage 4: manuscript learning

### T108 — Discourse data and gold
- Requirements: SR-M9, SR-M4
- Depends: T107
- Deliverables:
  - Discourse-role guideline and D05 gold on OCR output; splits by topic and paper cluster
- Validation:
  - Agreement kappa ≥ 0.85; test sealed
- Status: pending

### T109 — Manuscript-learning pipeline
- Requirements: SR-M9
- Depends: T108
- Deliverables:
  - Model heads, loaders, evaluator and readiness gates coupled to the stage-3 OCR output
- Validation:
  - Non-training tests on fixtures
- Status: pending

### T110 — Stage-4 training and held-out evaluation (owner run)
- Requirements: SR-M9, SR-M12
- Depends: T109
- Deliverables:
  - Prepared commands; intake checks; readiness report
- Validation:
  - Discourse-role macro F1 ≥ 0.82 on held-out data; owner promotion or NOT QUALIFIED
- Status: pending

## Phase 24 — Stage 5: integration in the model service

### T111 — Serve all qualified models
- Requirements: SR-M10, SR-M1
- Depends: T110
- Deliverables:
  - Model service loading the promoted stage 1-4 models through the GPU queue, with embeddings, NLI, extraction, OCR and
    discourse behind P2 and tool routes
- Validation:
  - Contract tests with the real models (inference only); queue respects the configured VRAM budget in tests
- Status: pending

### T112 — Full-load VRAM measurement (owner run)
- Requirements: SR-M10
- Depends: T111
- Deliverables:
  - Prepared measurement command and report template
- Validation:
  - Owner-measured full-load VRAM ≤ 15.0 GB on the RTX 5070 Ti; report recorded
- Status: pending

## Phase 25 — Stage 6: ResearchLLM advisor and specialists

### T113 — Stage-6 design review
- Requirements: SR-M11
- Depends: T112
- Deliverables:
  - Update of ADR-020 with the measured stage 1-5 results: final advisor architecture, size, data mix, compute budget and
    the frozen stage-6 gates
- Validation:
  - Owner accepts the update before T114
- Status: pending

### T114 — Advisor training data
- Requirements: SR-M11, SR-M4
- Depends: T113
- Deliverables:
  - Licensed research text, instruction and dialogue data with provenance; tool-use traces from scripted scenarios;
    owner-approved use of locally collected learning data; held-out research tasks sealed
- Validation:
  - Manifests and checksums; no evaluation item in training data (overlap scan)
- Status: pending

### T115 — Advisor model and chat backend
- Requirements: SR-M11, SR-M1
- Depends: T114
- Deliverables:
  - Generator code under ADR-020, decoding with tool-call output in the P2 format, chat backend in the model service
    replacing the placeholder when qualified
- Validation:
  - Non-training tests: shapes, decoding on a tiny random-weight model, P2 contract tests
- Status: pending

### T116 — Advisor training (owner run)
- Requirements: SR-M11, SR-M3
- Depends: T115
- Deliverables:
  - Prepared pretraining and fine-tuning commands with budgets and stop rules; intake checks
- Validation:
  - Logs and manifests match; validation analysis per stage-6 gate
- Status: pending

### T117 — Reasoning and verification specialists
- Requirements: SR-M11
- Depends: T116
- Deliverables:
  - Specialist heads or models (claim verification, contradiction, plan checking) per ADR-020, prepared owner runs
- Validation:
  - Non-training tests; owner-run results reported per gate
- Status: pending

### T118 — Stage-6 held-out evaluation; the model is finished
- Requirements: SR-M11, SR-M12
- Depends: T117
- Deliverables:
  - Held-out evaluation commands (owner run) and readiness report for every stage-6 gate
- Validation:
  - All stage-6 gates pass on held-out data, EN and VI; the owner records "the model is finished"; otherwise NOT QUALIFIED
- Status: pending
