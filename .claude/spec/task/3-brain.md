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
- Status: blocked
- Note: 2026-11-20: the owner opened the gate ("Thực hiện T162"); the agent drafted `docs/adr/ADR-024-main-brain-design.md` (status PROPOSED; gate thresholds N1-N8 are proposals). Blocked only on the owner's acceptance of the ADR (SR-K1); no brain code before it. Earlier note: Waiting for the owner to open the gate; the dependencies may be waived by the owner for the design only. 2026-11-20 (D48): T118 is superseded (the self-trained model is dropped), so it is no longer a dependency; the brain works with the open-weight LLM of Phase 44.

## Phase 38 — Knowledge base and write gate

### T163 — Knowledge notes and certainty ladder
- Requirements: SR-K2
- Depends: T162
- Deliverables:
  - Note types Source, Claim, Theory, Conflict, Open question in the vault schema; certainty levels; lint rules
- Validation:
  - Schema and lint tests; a Claim without a resolvable span fails
- Status: pending

### T164 — Write gate and consolidation
- Requirements: SR-K3
- Depends: T163
- Deliverables:
  - The only writer of the main brain: level check, contradiction search, Conflict notes, downgrade on retraction
- Validation:
  - Model-only claim refused; retracted source downgrades dependants; contradiction writes a Conflict
- Status: pending

### T165 — Acquisition and verification tools for the gate
- Requirements: SR-K3
- Depends: T164
- Deliverables:
  - Tools that search scholarly sources, acquire documents, verify exact quotes, DOIs and metadata, corroborate across
    sources and feed the write gate
- Validation:
  - Fixture runs promote only correctly verified claims; every promotion carries provenance
- Status: pending

### T166 — Answer assembly from accepted claims
- Requirements: SR-K4
- Depends: T164
- Deliverables:
  - Composer from accepted Claims with note ids; rephrase-only use of the advisor; outside-set assertion check
- Validation:
  - Inserted unsupported sentences are rejected; the check's miss rate is reported
- Status: pending

## Phase 39 — Decision network

### T167 — Rule decider v0
- Requirements: SR-K5
- Depends: T166
- Deliverables:
  - Deterministic decider over the closed action set using measured signals, replacing the programme-2 decider behind
    the `Decider` seam
- Validation:
  - Scenario suite passes; every decision is traceable to its signals
- Status: pending

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
