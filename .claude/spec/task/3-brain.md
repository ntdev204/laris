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
- Status: pending

### T169 — Decision network code and inference
- Requirements: SR-K5
- Depends: T168
- Deliverables:
  - Network code in the Python model block; export and Rust inference behind the `Decider` seam (dependency approval
    needed); calibration and abstention
- Validation:
  - Non-training tests; identical outputs between Python and Rust inference on fixtures
- Status: pending

### T170 — Decision network training (owner run)
- Requirements: SR-K5, SR-K6
- Depends: T169
- Deliverables:
  - Prepared commands with budget and stop rules; intake checks
- Validation:
  - Logs and manifests match; validation analysis
- Status: pending

### T171 — Held-out gates and promotion of the network
- Requirements: SR-K5
- Depends: T170
- Deliverables:
  - Held-out evaluation (owner run) against the rule decider on the gates of the ADR
- Validation:
  - Gates pass and the owner promotes the network; otherwise the rule decider stays
- Status: pending

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
