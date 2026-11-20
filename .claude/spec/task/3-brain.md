# LARIS — Tasks 3: Main brain

Version 2.0.0-draft · 2026-11-13 · Implements [plan/3-brain.md](../plan/3-brain.md) for [spec.md](../spec.md).

Status values and rules as in [task/1-model.md](1-model.md).

## Phase 37 — Design gate

### T162 — ADR: brain decides, model advises
- Requirements: SR-K1
- Depends: T161
- Deliverables:
  - ADR fixing note types and certainty ladder, the write gate, the closed action set and inputs of the decision network,
    abstention, answer assembly, the cold-start rule decider, held-out gates and owner runs
- Validation:
  - Owner accepts the ADR
- Status: done
- Note: 2026-11-20: the owner opened the gate ("Thực hiện T162"); the agent drafted `docs/adr/ADR-024-main-brain-design.md` (status PROPOSED; gate thresholds N1-N8 are proposals). The owner accepted the ADR on 2026-11-20 ("Chấp nhận"), thresholds N1-N8 included; ADR-024 is ACCEPTED and T163 may start. Earlier note: Waiting for the owner to open the gate; the dependencies may be waived by the owner for the design only. 2026-11-20 (D48): T118 is superseded (the self-trained model is dropped), so it is no longer a dependency; the brain works with the open-weight LLM of Phase 44.

## Phase 38 — Knowledge base and write gate

### T163 — Knowledge notes and certainty ladder
- Requirements: SR-K2
- Depends: T162
- Deliverables:
  - Note types Source, Claim, Theory, Conflict, Open question in the vault schema; certainty levels; lint rules
- Validation:
  - Schema and lint tests; a Claim without a resolvable span fails
- Status: done
- Note: 2026-11-20: `crates/laris-vault/src/brain.rs` (main-brain profile: `brain_schema`, `Level` ladder, `resolve_span`, `lint_brain`) and `tests/brain.rs` (9 tests: valid vault clean; missing, wrong-hash, out-of-range and unresolved spans; candidate and unknown levels refused; evidence for corroborated, verified and reviewed; edited Source; retracted Source; Conflict and Open question rules; deterministic order). Spans are byte offsets into the Source note body. Lint only proves a span exists and reproduces; meaning, metadata and contradiction checks belong to the write gate (T164, T165).

### T164 — Write gate and consolidation
- Requirements: SR-K3
- Depends: T163
- Deliverables:
  - The only writer of the main brain: level check, contradiction search, Conflict notes, downgrade on retraction
- Validation:
  - Model-only claim refused; retracted source downgrades dependants; contradiction writes a Conflict
- Status: done
- Note: 2026-11-20 (owner: "Thực hiện T164-166"): new crate `laris-brain` (workspace member; no external dependency added; `deny.toml` and spec 5.1 list it). `gate.rs` is the only writer: shape, span (exact quote, or whitespace-folded; offsets and hash recorded), metadata (a document Source is stored only with a `Verified` check; T165 supplies it), support (numbers, polarity, opposite words, content-word coverage `min_support`), evidence for levels above `sourced`, contradiction search (BM25 over Claims and Theories, then the rule check of `text.rs`), write, and an append-only audit `.laris/brain-audit.jsonl` (accepted and refused alike). Model-only text (no Source, quote not in the Source, statement the quote does not support, `candidate` asked for, level above the evidence) is refused and writes nothing. A contradiction writes one Conflict that keeps every side and links it from both Claims; the new Claim stays at its own level. `retract_source` and `supersede_source` run `consolidate`: a Claim or Theory whose Source is retracted leaves to `.laris/retired/` (falls to `candidate`), a corroborated Claim with no surviving corroborator falls to `sourced`, a lost tool run lowers `verified`, `reviewed` stays unless the Source goes, Conflicts with fewer than two sides leave, dead links are pruned, an answered question without answer reopens; the walk is idempotent (second run empty). T163 schema gained `conflict_refs` on Claim and Theory. 14 tests in `crates/laris-brain/tests/gate.rs`, lint clean after each scenario. Measured on 10 seeded contradictions: 7 found, 3 missed (all three use other vocabulary): contradiction-search miss rate 30 % on that fixture; the figure is a fixture measurement, not a guarantee. Limits: NFC normalisation of ADR-024 3.2 is not applied (no approved Unicode crate); only whitespace is folded. Thresholds are `GateSettings` filled by the caller; the server binding that reads them from configuration belongs to the T165 tools.

### T165 — Acquisition and verification tools for the gate
- Requirements: SR-K3
- Depends: T164
- Deliverables:
  - Tools that search scholarly sources, acquire documents, verify exact quotes, DOIs and metadata, corroborate across
    sources and feed the write gate
- Validation:
  - Fixture runs promote only correctly verified claims; every promotion carries provenance
- Status: done
- Note: 2026-11-20: `crates/laris-brain/src/tools.rs`. The outside world is two traits, `Scholarly` (search, fetch) and `Registry` (resolve an identifier), plus `ToolRunner` for checks; the server binds them to real services from configuration (no endpoint, key or default in code), so **no network adapter exists yet**: the tools are proven on fixtures only, and the server wiring is left to the task that connects the brain to the server. `Tools` offers `search` (deterministic, de-duplicated, skips stored identifiers), `acquire` (fetch, `verify_metadata` against the registry by family names, year and title words, then `Gate::submit_source`; a document that does not resolve or differs is refused), `verify_quote`, `promote_claim` (gate, then `corroborate`, then `Provenance`), `corroborate` (BM25 candidates, `independent`: different identifier, no mutual citation, not the same dataset release; the gate's rule check decides equivalence), `verify_with_tool` (stores the run as a `tool_run` Source, then raises to `verified` only if the output supports the Claim). `SourceProposal` gained `cites` and `dataset`. Tools never write the vault. 4 tests in `tests/tools.rs` on fixtures (good, wrong-year, unresolved, copy that cites the first, fabricated quote): exactly 3 Claims stored, each with provenance (identifier, metadata check, retrieved, span reproduced, proposer, audit sequence), vault lint clean.

### T166 — Answer assembly from accepted claims
- Requirements: SR-K4
- Depends: T164
- Deliverables:
  - Composer from accepted Claims with note ids; rephrase-only use of the advisor; outside-set assertion check
- Validation:
  - Inserted unsupported sentences are rejected; the check's miss rate is reported
- Status: done
- Note: 2026-11-20: `crates/laris-brain/src/answer.rs`. `compose` picks accepted Claims and Theories that match the question (content words only: stop words matched everything), puts a note id and the level on every sentence, presents each open Conflict touching a used note with both sides in the notes' own words, and gives the fixed abstention when nothing is accepted. `assemble` offers each Claim or Theory sentence to a `Rephraser` (rewording only) and keeps the rewording only if `check_sentence` passes and the optional `Judge` does not veto; a judge can veto, never approve; a failed or refused rewording leaves the Claim's own words and is reported. `check_sentence` (ADR-024 6.3): cites accepted notes; every number, name, negation and hedge is in the cited notes; no hedge added or dropped; no opposite word; `min_cover` of the content words in the cited notes. `verify_answer` re-checks a whole answer from the notes (no citation, unknown id, unaccepted note, fake system sentence, altered conflict). Tests `tests/answer.rs` (6): composition, abstention (also after a retraction and above the Claim's level), conflict, advisor limits, inserted sentences rejected. **Miss rate, measured** (`reports/brain/outside-set-check.json`): 16 inserted unsupported sentences, 13 rejected, 3 missed (words kept with roles swapped, names swapped, two Claims spliced) = 18.75 % on this fixture; of 8 faithful rewordings 6 are kept (25 % false-reject: free paraphrase costs the Claim's own wording). The check reads vocabulary, not meaning; the system is faithful to accepted Claims only up to the measured miss rate, and the figure comes from a small hand-made fixture. T164-T166 close Phase 38.



## Phase 39 — Decision network

### T167 — Rule decider v0
- Requirements: SR-K5
- Depends: T166
- Deliverables:
  - Deterministic decider over the closed action set using measured signals, replacing the programme-2 decider behind
    the `Decider` seam
- Validation:
  - Scenario suite passes; every decision is traceable to its signals
- Status: done
- Note: 2026-11-20 (owner: "Thực hiện T167-169"): `crates/laris-brain/src/decide.rs` (closed set `Act` of ADR-024 5.1, `Signals`, `legal` candidates, `RuleDecider`, `Choice`, `Chooser` trait) and `seam.rs` (`BrainDecider`, a core `Decider` that wraps `FollowModel` and lets a `Chooser` pick at the choice points: before asking the model and at the completion check). Rules R1 limit, R2 slot, R3 covered (R3-covered-conflict presents an open Conflict instead of hiding the answer; ADR 7.3 read literally would hold the answer back, the scenario list asks for the Conflict to be presented), R4 verify, R5 retrieve-new/acquire, R7 run-tool/ask-advisor, R6 abstain; thresholds are `RuleSettings`, no default. Each `Choice` carries signals, legal candidates, rule and reason, as one JSON object (`Brain::log`). Tests: `tests/decide.rs` (10: stop on budget/time/steps/cycle, ask on missing slot, abstain on no evidence, verify before answer, Conflict presented, model-only claim refused by the gate and never an answer, acquire/retrieve/advisor order, a 20 000-point grid where every choice is legal, deterministic, traceable and every rule fires) and `tests/seam.rs` (3, through the real `Driver` with replay: covered question answered from the brain without calling the model, advisor text never reaches the user, spent budget stops). Limits: `run_tool`, `retrieve`, `acquire`, `verify` still need the advisor to propose the call (the seam sends a note, the tool gate and policy still decide); `answer`, `abstain` and `ask_user` close the turn through `Action::Stop` with status `completed` and the brain's own text, since core `Finish` takes the model's text. Signals that the system cannot yet measure (`pending_candidates`, `retracted_dependencies`, `missing_slot`, `call`) are filled by the `Brain` implementation of the caller; the server binding belongs to integration (T172). Coverage is the share of the question's content words in accepted notes, a vocabulary measure, not meaning.

### T168 — Decision dataset
- Requirements: SR-K6
- Depends: T167
- Deliverables:
  - Examples (state, candidates, choice, outcome) from event logs with provenance; held-out split sealed; exclusion of
    model-generated text from any ResearchLLM training data drawn from the brain
- Validation:
  - Manifests and checksums; a seeded model-generated example is excluded
- Status: done
- Note: 2026-11-20: `crates/laris-brain/src/dataset.rs` and `cargo xtask decision-data --config FILE (--out DIR --date D [--log FILE]... | --verify DIR)`. An `Example` is (signals, legal candidates, action, outcome) with provenance and a sha256 id over its content. Origins: `log` (decision line from `decision_line` joined with a system-measured `outcome_line`; evidence from a closed set of nine measured kinds) and `scenario` (grid-v1: the same state replayed with every legal candidate against the scenario oracle, 31 488 examples in 4 608 states with the settings of the test configuration). Labels come from outcomes, not from the rule decider's choice (a test shows the same choice labelled good and bad). Excluded and counted in the manifest: a line whose origin is not `log` (a seeded model-generated example is dropped), an outcome judged by a model or resting on evidence outside the closed set, a choice outside the candidates, a decision with no outcome, a malformed line. Splits are by hash of the group (a group never straddles two splits), plus `heldout-unseen-advisor` for a withheld advisor (gate N5); the manifest holds file checksums, counts per split and the scenario share; `seal.json` holds the hash of the sealed ids and files, and `verify` finds an edited file, a wrong id, an example in the wrong split, a group in two splits, a leak into train. `training_text` exports what may reach ResearchLLM from the brain: Source texts that are not retracted and the verified quote of each Claim (a Claim's own statement, Theories, Conflicts and Questions are never exported; a note planted without a Source or span is reported). `Signals` gained `advisor_accept_rate`, `advisor_agreement` and `tool_risk` (ADR 5.3). Tests: `tests/dataset.rs` (8). **Honest limits:** there is no real decision log yet, so the dataset built here is 100 % scenario examples (scenario_share 1.0 in every split); the oracle is written from what each action is for but is still a hand-made model of the world, so labels prove the mechanics and cannot show real-world behaviour; the seal proves a later change, not that the split was made before a model existed (the date is written by the caller; T170 intake must compare it with the run). Output belongs outside Git (`data/`); the command writes nothing unless `--out` is given.

### T169 — Decision network code and inference
- Requirements: SR-K5
- Depends: T168
- Deliverables:
  - Network code in the Python model block; export and Rust inference behind the `Decider` seam (dependency approval
    needed); calibration and abstention
- Validation:
  - Non-training tests; identical outputs between Python and Rust inference on fixtures
- Status: done
- Note: 2026-11-20: Python side `src/laris/model/decision/` (`features.py`: 26 state features, one-hot candidate, candidate count = 36 inputs, no free text and no advisor-stated confidence; `network.py`: numpy float64 reference forward, canonical JSON export and load with shape, name and finite checks, a seeded `random_net`, and a `torch` module of the same architecture; `calibration.py`: temperature chosen by a grid search on validation log-loss (no gradient), expected calibration error, abstention threshold = lowest confidence whose kept decisions reach a target precision). Rust side `crates/laris-brain/src/network.rs`: `features` (the same formulas), `Network::from_json` (refuses a file whose feature names, shapes, activations, temperature or threshold are wrong), handwritten forward pass in f64, `NetworkChooser` behind the `Chooser` seam of T167: it scores only the legal candidates, picks the best calibrated probability, and below the sealed threshold returns the rule decider's choice with rule `fallback` and a reason that names both (the fallback is never the advisor's proposal). **No dependency added** (ADR-024 5.4; serde_json was already there). Fixtures `crates/laris-brain/tests/fixtures/decision-net/{net,cases}.json` are written by `scripts/make_decision_net_fixture.py` from a **seeded random, untrained** 2 273-weight network (40 cases, 219 scores); `--check` fails if the files drift. **Parity measured:** maximum absolute difference Python float64 against Rust 8.9e-16 over 219 scores (gate N6 asks 1e-5); torch float32 forward against the numpy reference within 1e-5 in a test. Tests: `tests/unit/model/decision/test_decision_net.py` (12, forward only under `no_grad`; a static test that the package has no `backward`, optimizer or `fit`) and `crates/laris-brain/tests/network.rs` (5: parity, names, refusal of six malformed files, only legal candidates over all 4 608 grid states at three thresholds, fallback and record). Not done here and left to T170: the training loop, the loss, the budget and stop rules and the intake checks; no training was run and the guard still passes. The network has no trained weights, so nothing about decision quality is claimed; it stays NOT QUALIFIED and the rule decider stays in charge. Gate N7 (latency p95 on the reference CPU) is not measured here.

### T170 — Decision network training (owner run)
- Requirements: SR-K5, SR-K6
- Depends: T169
- Deliverables:
  - Prepared commands with budget and stop rules; intake checks
- Validation:
  - Logs and manifests match; validation analysis
- Status: done
- Note: 2026-11-20: **prepared; waiting for the owner's run.** Nothing was trained, fitted or optimised; no training authorisation was set and the no-training guard still passes. Code: `src/laris/model/decision/evaluation.py` (no loop, no optimiser: reads only `train` and `validation` and refuses the sealed splits by name, checks file checksums against the manifest, scores with the float64 reference, fits temperature and threshold on validation only, validation analysis, the stop rules as pure functions, the run record), `scripts/train_decision_net.py` (the owner's loop: binary cross-entropy on (state, candidate) pairs, Adam, seeded order; requires `LARIS_TRAINING_AUTHORIZED=1` through `assert_training_authorized`; refuses an existing output directory; every tunable from `configs/decision-net-training.json`, nothing defaulted), `scripts/decision_net_intake.py` (read-only intake). Budget and stop rules in the config: `max_epochs` 200, `max_seconds` 1800, `patience` 15 with `min_delta`, `divergence_factor` 3.0, non-finite loss, `max_parameters` 5000 (the 32+32 network has 2 273). Intake fails a run when: the config or dataset manifest differs from the prepared command; `splits_read` is not exactly train and validation; the seal or a sealed file changed, or the manifest or seal is dated after the run started (the date check promised in T168); the log is not one contiguous finite line per epoch or breaks the budget; the stop rules replayed on the log do not give the recorded epoch and reason; the network does not load, differs from the run record, architecture or parameter limit, or names another dataset, config or seed; the recorded validation numbers do not reproduce from the exported weights; temperature and threshold are not the validation fit. Warnings only: the network does not beat the majority-by-action baseline, or validation loss is far above train loss. Commands and the table of rules: `docs/development/DECISION_NETWORK_RUNBOOK.md`. Tests: `tests/unit/model/decision/test_decision_training_prep.py` (19; a fabricated consistent run passes the intake and nine tampered runs fail it by name; the script refuses without authorisation; nothing in them trains). **Checked on real data:** the scenario dataset built by `cargo xtask decision-data` (31 488 examples, `--verify` passes) loads through `load_split` (22 037 train, 2 997 validation); an untrained network scores 3.7 % choice accuracy on it, against 67.7 % for the majority-by-action baseline, which shows the baseline is strong. **Not tested:** the loop in `descend` is the one part no test may run (it takes backward and optimiser steps); it is covered by ruff, mypy and review only, so the owner's first run is its first execution and may need a fix. **Honest limits:** with no real decision log the dataset is 100 % scenario examples, so a network trained on it learns the hand-made oracle and says nothing about real decisions; the intake validation numbers are on the validation split, never held-out performance; the network stays NOT QUALIFIED and the rule decider stays in charge. Closes when the owner returns a run directory and the intake passes; then T171 may start.
- Result: 2026-11-20, run done on the owner's explicit permission given in the session (one command, `LARIS_TRAINING_AUTHORIZED=1` set on that command only, not stored): dataset `data/decision/2026-11-20` (scenario grid-v1, 100 % scenario examples, `--verify` passes), config `configs/decision-net-training.json` unchanged, output `artifacts/decision-net/2026-11-20-seed170` (outside Git). Stopped by `patience` after 68 epochs in 2.2 s (best epoch 53). **Intake PASS, 0 failed, 0 warnings** (`intake.json` in the run directory). Validation: choice accuracy 1.000 against 0.677 for the majority-by-action baseline, log-loss and ECE about 0, kept share 1.0. **Read this honestly:** the scenario oracle is a deterministic function of the features, so a perfect fit shows the pipeline works end to end, not that the network decides well; the fitted temperature sits on the lower grid edge (0.25) and the threshold at about 1.0 because every validation decision was right, so these values are not informative. Nothing is claimed about real decisions; the network is NOT QUALIFIED. Held-out gates N1 to N8 and the comparison with the rule decider are T171; real decision logs are needed before the result means anything.

### T171 — Held-out gates and promotion of the network
- Requirements: SR-K5
- Depends: T170
- Deliverables:
  - Held-out evaluation (owner run) against the rule decider on the gates of the ADR
- Validation:
  - Gates pass and the owner promotes the network; otherwise the rule decider stays
- Status: done
- Note: 2026-11-20: `crates/laris-brain/src/gates.rs` (`states`, `evaluate`, `Limits`; gates N1 to N8 against the rule decider on the states of a split, a missing measurement is `NOT VERIFIED`), `cargo xtask decision-gates --dataset DIR --dataset-config FILE --net FILE --gates FILE --out REPORT [--scores-out FILE] [--parity FILE]` (verifies the dataset seal first and refuses to measure if it does not hold; reads the sealed split through `dataset::read_split`, which checks the manifest checksum; writes the report with the hashes of the held-out file, manifest, network and both configs; exit 1 unless every gate passes), `scripts/decision_net_parity.py` (gate N6: numpy float64 reference against the Rust score of every held-out example), thresholds of the ADR in `configs/decision-net-gates.json` (nothing defaulted). Definitions: accuracy is the share of states where the chosen action's outcome label is good; N1 needs a gain of at least 3 points and a paired bootstrap lower bound (2000 resamples over states, seeded) above zero; an unsupported `answer` is an `answer` whose label is not good; N3 is the error over every (state, legal candidate) probability against its label; required abstentions are the states where `abstain` is labelled good. Tests: `tests/gates.rs` (7: grouping, an untrained network fails N1 and passes N8, a missing measurement is not a pass, a network that always falls back to the rules gains exactly 0 and fails N1, the unseen-advisor split is measured when it exists, broken groups are refused, calibration error formulas) and `tests/seam.rs::a_chooser_cannot_bypass_the_tool_gate_or_the_composer` (a chooser forced to every act: the advisor's text never reaches the user). Nothing trains or tunes. Commands: `docs/development/DECISION_NETWORK_RUNBOOK.md` section 5.
- Result: 2026-11-20, one measurement on the sealed held-out split of `data/decision/2026-11-20` (939 states, 6 454 examples, 100 % scenario; report `reports/brain/T171-decision-net-gates.json`, network `2026-11-20-seed170`). **NOT PROMOTED; the rule decider stays in charge.** N1 **FAIL**: network 1.000 and rule decider 1.000, gain 0.0 points, bootstrap interval [0, 0]; the rule decider already agrees with the scenario oracle on every held-out state, so a gain of 3 points cannot exist on this data. N2 PASS (0 of 77 answers unsupported, both deciders). N3 PASS (pair ECE 0.0004; 4 decisions fell back to the rules). N4 PASS but on **3** required abstentions only (recall 1.0, over-abstention 0 for both): too few to mean much. N5 **NOT VERIFIED**: the dataset has no withheld advisor (no advisor-labelled example exists). N6 PASS (max absolute difference 1.1e-15 over 6 454 scores). N7 PASS (p95 0.0104 ms, max 0.0133 ms, Intel Core i5-14600KF, release build); the specification does not define the reference CPU, so the owner confirms this machine or repeats the run. N8 PASS (0 of 939 decisions outside the legal list; policy bypass by the seam test above). **Read this honestly:** the oracle and the rule decider were written from the same idea of what each action is for, so on scenario data the rules are the oracle and the network can at best copy them; this result does not show the network is bad, it shows this data cannot show it is better. To promote, real decision logs (outcomes measured by the system, more than one advisor, one withheld) are needed so that N1 and N5 can be measured; until then the network stays NOT QUALIFIED and unused. The held-out file was read for the parity step and the final report from one unchanged file (same checksum); no network, threshold or dataset was changed after seeing a number.

## Phase 40 — Integration and evaluation

### T172 — Cognitive evaluation with ResearchLLM
- Requirements: SR-K7
- Depends: T171
- Deliverables:
  - End-to-end cognitive loop with ResearchLLM as advisor; evaluation with more than one advisor: unsupported-claim
    pass-through, faithfulness, abstention calibration, constraint recall, false completion
- Validation:
  - Report produced and reviewed by the owner; results stated as system measurements
- Status: pending
