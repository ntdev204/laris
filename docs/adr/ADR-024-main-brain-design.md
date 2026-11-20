---
document_id: "DOC-ADR-024"
title: "ADR-024: Main brain: the brain decides, the model advises"
document_type: "adr"
status: "ACCEPTED"
version: "0.1.0"
created_at: "2026-11-20"
updated_at: "2026-11-20"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - ".claude/spec/spec.md"
  - ".claude/spec/plan/3-brain.md"
  - ".claude/spec/task/3-brain.md"
decision_references:
  - "ADR-004"
  - "ADR-008"
  - "ADR-021"
change_summary: "Accepted by the owner 2026-11-20 (task T162): note types and certainty ladder, write gate, closed action set and inputs of the decision network, abstention, answer assembly, cold-start rule decider, held-out gates, owner runs."
---

# ADR-024: Main brain: the brain decides, the model advises

## Metadata
- **Status:** ACCEPTED on 2026-11-20 by the owner ("Chấp nhận"), including the proposed gate thresholds N1-N8; brain code may now start (SR-K1). Values marked *proposed* were confirmed by the acceptance; none is relaxed without an amendment to this ADR.
- **Requirements:** SR-K1 to SR-K7 · **Task:** T162 · **Builds on:** D48 (open-weight ResearchLLM), ADR-004 (evidence
  provenance), ADR-008 (no capability claim without a held-out measurement), ADR-021 (Rust generation, `Decider` seam)
- **Qualification:** the foundation model and ResearchLLM are NOT QUALIFIED. The system guarantees *faithfulness to its
  sources*, not truth of the world. The decision network can choose wrongly; it is NOT QUALIFIED until it passes the
  gates of section 8, and the rule decider stays in charge until then.

## 1. Context
Programme 2 delivered a loop whose next step is chosen by a `Decider` (SR-H14) that follows the model's proposal under
policy. That is the weak point of an agent built on a language model: the same component that may hallucinate also
decides when to stop, what to trust and what to write down. Programme 3 moves those choices out of the model:

```text
ResearchLLM (advisor) ──proposals──►  Decision network (non-generative)  ──action──►  System (tools)
         ▲                              ▲              │                                │
         └──────── brain context ───────┴── Obsidian main brain ◄── write gate ◄── verified results
```

The advisor proposes (text, plans, claims, tool calls). The brain stores only what is verified and traceable. A
non-generative component chooses among bounded candidates. The system executes and writes verified results back through
exactly one gate.

## 2. Decisions in brief
1. **Single writer.** Only the write gate (section 4) writes the main brain. No tool, advisor, hook or user command bypasses it.
2. **Model text is never knowledge.** A Claim exists only with a resolvable span in an immutable Source. Advisor output is
   a *proposal*; it can become a Claim only by passing verification against a Source.
3. **Closed action set.** The decision network chooses among a fixed, enumerated set (section 5); it never generates text,
   tool arguments or plans.
4. **Abstention is an action.** Below a calibrated confidence the system declines, asks, or verifies; it does not guess.
5. **Rules first.** A deterministic rule decider (section 7) ships first and stays in charge until the network beats it on
   sealed held-out gates and the owner promotes it.
6. **The network is trained by the owner.** The agent writes code and prepares commands; it never trains (AGENTS.md, SR-M3).

## 3. Knowledge notes and certainty ladder

### 3.1 Note types
The main brain is an Obsidian-format vault (SR-L2) held by the server, confidential like the system brain, at a path given
by configuration. The schema of `laris-vault` gains a stricter *main-brain profile*; types outside it are rejected by lint.

| Type | Content | Rules |
| :--- | :--- | :--- |
| **Source** | Verbatim text of a document or tool output, with metadata (identifier such as DOI or URL, retrieval date, `kind`: `document` or `tool_run`) | Immutable; carries a SHA-256 of the text; replacement creates a new Source and marks the old one `superseded`; retraction marks it `retracted` |
| **Claim** | One atomic statement | Carries `source_ref`, a span (`start`, `end`, `span_sha256`) inside that Source, and a `level` (3.2); the quoted span must reproduce byte-for-byte |
| **Theory** | An attributed position ("X argues that ...") | Never asserted as fact; carries the attributing Source span; may be cited only with attribution |
| **Conflict** | Two or more Claims or Theories that cannot all hold | Keeps *both sides* with their spans; never resolved silently; closed only by a human or by a newer Source that both sides' authors do not contradict |
| **Open question** | Something asked and not answered | Links the Claims and Conflicts that bear on it; the system may only answer it from Claims |

A tool run (a computation, a script, a database lookup) is stored as a Source of kind `tool_run`: command, inputs hash,
output text and output hash. This keeps SR-K3's rule ("model-generated text never becomes a Claim without a Source") true
for computed results too.

### 3.2 Certainty ladder
Levels are ordered by what an answer may do with the Claim. Each is a *checkable condition*, recorded with its evidence:

| Level | Condition | Evidence kept |
| :--- | :--- | :--- |
| `candidate` | Proposed (by the advisor or a tool); no verified span yet | Proposer id; **never written to the main brain**, kept in the session only |
| `sourced` | The exact quote is found in the Source after the fixed normalisation (Unicode NFC, whitespace folded) and the metadata (DOI, authors, date) matches the registry | Span offsets and hash; metadata check result |
| `corroborated` | At least two *independent* Sources state the same atomic claim. Independent means different origin: not the same document, not a copy or a mutual citation, not the same dataset release | Both spans; the independence reason |
| `verified` | A tool or computation reproduces or checks the claim (recompute a number, run a check, resolve a DOI) | The `tool_run` Source |
| `reviewed` | A human accepted it | Reviewer identity and date |

A Claim carries the **highest level whose condition holds**; every level above `candidate` requires `sourced`. The gate
raises a level only by evidence and lowers it automatically (section 4). Equivalence of two statements for
`corroborated` is judged by the rule check of section 6.3 on the quoted spans; the advisor may *propose* a pairing but
cannot make it.

### 3.3 Lint
Lint (T163) fails: a Claim without a resolvable span or with a span whose hash differs; a Claim at a level whose evidence
is missing; a Theory without attribution; a Conflict with fewer than two sides; a link to a Source that is `retracted`
from a Claim above `candidate`; an edit of a Source after creation.

## 4. The single write gate

The gate (T164) is the only code path that writes the main brain. It runs on the server; the client and the harness
submit *proposals* to it and get a decision back.

```text
proposal ──► 1 shape check ──► 2 span check ──► 3 metadata check ──► 4 contradiction search ──► 5 write | refuse | Conflict
```

1. **Shape check:** the proposal is a well-formed Claim, Theory or Source; model-only text without a Source is refused.
2. **Span check:** the quote exists in the Source at the stated offsets; hash matches.
3. **Metadata check:** identifiers and dates are verified by the acquisition and verification tools (T165); a mismatch
   refuses the proposal (an unresolved DOI is not accepted as `sourced`).
4. **Contradiction search:** before accepting, the gate retrieves Claims and Theories about the same subject (BM25 and
   TF-IDF, then the entity and number rules of 6.3) and looks for opposing polarity, incompatible numbers or units, and
   incompatible dates. If found, it writes a Conflict that keeps both sides and accepts neither as settled; the new Claim
   is still stored at its own level, linked to the Conflict, and answers must present the conflict (section 6).
5. **Write:** an append-only audit record (who proposed, what the gate checked, what it decided) is written with the note.
   Refusals are logged with the reason and are visible to the user.

**Consolidation.** When a Source is retracted or replaced, the gate walks every dependent Claim and downgrades it (a Claim
whose only Source is retracted falls to `candidate` and leaves the main brain; a `corroborated` Claim with one surviving
Source falls to `sourced`), re-evaluates open Conflicts, and writes the audit trail. The walk is deterministic and idempotent.

**Honest limit.** The contradiction search is a retrieval-and-rule check; it will miss contradictions that use different
vocabulary. Its miss rate is *measured* on seeded fixtures (T164, T166 report) and stated, never assumed zero.

## 5. Decision network: closed action set and inputs

### 5.1 What is decided
Mechanical steps of the loop (applying a plan, rejecting a tool call that policy forbids, reflecting on a step result,
retrying) stay in rules: they are not judgement and the policy layer must not be learnable. The network decides at the
**choice points** where the loop today follows the model. The closed action set is:

| Action | Meaning | Maps to today's loop action |
| :--- | :--- | :--- |
| `retrieve` | Search the main brain and project vault for the sub-goal | `RunTool` (retrieval tool) |
| `ask_advisor` | Ask ResearchLLM for a proposal (plan, claim, tool call), with brain context | `AskModel` |
| `run_tool` | Run the advisor's proposed tool call (policy and sandbox still apply) | `RunTool` |
| `acquire` | Search and fetch a source document | `RunTool` (acquisition tool, T165) |
| `verify` | Verify a candidate Claim against its Source (quote, DOI, metadata, corroboration) | `RunTool` (verification tool, T165) |
| `answer` | Assemble the answer from accepted Claims (section 6) | `Finish` |
| `ask_user` | Ask a clarifying question | `Finish` with a question |
| `abstain` | State that the question cannot be answered from accepted Claims, and why | `Finish` with an abstention |
| `stop` | End the turn (budget, timeout, cycle) | `Stop` |

The set changes only by amending this ADR. Safety decisions are not in the set: a `run_tool` the policy forbids is refused
by the policy gate *after* the network chose it, exactly as today, so the network cannot widen what the system may do.

### 5.2 Candidates and scoring
For each decision the system builds the **candidates**: every action in the set that is currently *legal* (for example
`answer` is not a candidate when the accepted-Claim set is empty; `run_tool` needs a proposed call that passes policy
checks). Each candidate carries its arguments from the system (which tool call, which Claim). The network scores
`(state, candidate)` pairs and returns the best action, its candidate and a calibrated confidence in [0, 1]. It chooses
from candidates only; it cannot emit an action that is not in the list.

### 5.3 Inputs (measured signals)
Only numbers and categories computed by the system, never free text:

- **Evidence coverage:** share of the goal's sub-questions with at least one accepted Claim, and the best level reached.
- **Support:** for `answer`, share of planned answer sentences that map to accepted Claims; number of Claims at each level.
- **Conflict state:** open Conflicts touching the question; number of retracted or downgraded dependencies.
- **Verification results:** quote-found rate, NLI-style check and number/entity check outcomes of 6.3.
- **Advisor agreement and track record:** agreement between independent advisor samples (when more than one is drawn), and
  the per-advisor history of proposals accepted vs. refused by the gate (a running, logged rate, never self-reported).
- **Cost and risk:** tokens and money spent against the budget, tool risk class from policy, steps left, time left.
- **Loop history:** repeated actions, failed attempts of the same kind.

The advisor's own stated confidence is **not an input**. The advisor's identity is an input only as a categorical track-record
key; the held-out gates (section 8) include an *unseen advisor* so the network cannot become a model-specific shortcut.

### 5.4 Model form
A small non-generative scorer on tabular features: a multilayer perceptron with a few thousand weights, exported as plain
weights (JSON or a flat binary) and evaluated by a handwritten forward pass in `laris-core`, so Rust inference needs
**no new dependency** (T169). Alternative considered: gradient-boosted trees (stronger on tabular data but need an
inference library, which needs dependency approval and a larger audit surface) and a transformer decision head (opaque,
heavy, would let free text into the decision). Calibration is temperature scaling fitted on the validation split; the
confidence is the calibrated probability that the chosen action matches the outcome label.

### 5.5 Abstention
The network returns `abstain`-like behaviour in two ways: it may choose the `abstain`, `ask_user` or `verify` action when
they score best, and a **confidence threshold** turns any low-confidence choice into a fallback to the rule decider's
cautious action (never to the advisor's proposal). The threshold is a configuration value fixed on validation data to meet
the abstention gate, then sealed with the model manifest. A decision below threshold and the fallback are both recorded.

## 6. Answer assembly from accepted claims

### 6.1 Composer
The final answer is built from accepted Claims (level `sourced` or above, no unresolved retraction) selected by the
`answer` action: the composer orders them, adds a note id (`[[Claim-...]]`) to every sentence, and states open Conflicts
and the level of each used Claim. The advisor may **rephrase only**: it receives the Claims and the structure, and returns
wording.

### 6.2 What the answer may not do
An answer may not contain a sentence that is not mapped to a Claim, a Theory (attributed), a Conflict (presented as such)
or a system statement (an abstention, a question). A Claim at `sourced` is presented with its source; `candidate` text is
never presented as fact.

### 6.3 Outside-set check
After rephrasing, a deterministic check compares each sentence with the Claims it cites: every number, unit, date,
named entity and negation in the sentence must occur in the cited Claims (after normalisation), and no cited-Claim
polarity may flip; comparatives, quantifiers and hedges are matched against a closed lexicon. A sentence that fails is
dropped and the original Claim wording is used instead. An optional advisor-as-judge pass may add a veto but **never an
approval**. The check is a filter, not a proof: its **miss rate is measured** on fixtures with inserted unsupported
sentences (T166) and reported; the system is described as "faithful to accepted Claims up to the measured miss rate".

## 7. Cold start: the rule decider

The rule decider v0 (T167) is deterministic, ordered, and replaces the programme-2 decider behind the `Decider` seam. It
exists because there is no decision data at the start and because it is the baseline the network must beat.

1. If a hard limit holds (budget, time, cycle) → `stop`.
2. If the question is unclear by a closed test (missing required slot) → `ask_user`.
3. If accepted Claims cover the goal at or above the required level and no open Conflict touches them → `answer`.
4. If a covered Claim is `candidate` only → `verify`.
5. If the brain has no sufficient coverage and acquisition is allowed → `acquire`, then `retrieve`.
6. If still no coverage and nothing else is legal → `abstain`.
7. Otherwise → `ask_advisor` (for a plan or a tool call), then `run_tool` if the call is legal.

The thresholds (required level, coverage fraction, retry bounds) are configuration, not code. Every decision stores the
signals and the rule that fired, so it is traceable (SR-K5 acceptance). A scenario suite (T167) with a placeholder
advisor must pass: stop on budget, ask on missing slot, abstain on no evidence, verify before answer, present a Conflict,
refuse a model-only claim.

## 8. Held-out gates for the network

All gates are measured on a **sealed held-out set** (sessions the training and validation data never touched, hashed
before any model exists) against the rule decider on the same set. Missing measurement is NOT VERIFIED, never a pass
(ADR-008). Thresholds are *proposed*; the owner confirms them at acceptance.

| Gate | Statement | Proposed threshold |
| :--- | :--- | :--- |
| N1 | Decision accuracy against the outcome labels | ≥ rule decider + 3 points, 95 % bootstrap lower bound above the rule decider |
| N2 | Unsupported `answer` rate (answered when the accepted set did not support it) | ≤ 1 % and not above the rule decider |
| N3 | Calibration (expected calibration error) | ≤ 0.05 |
| N4 | Abstention: abstains when it should; does not over-abstain | recall of required abstentions ≥ 0.90, over-abstention ≤ rule decider + 5 points |
| N5 | Unseen advisor: N1 and N2 hold when one advisor was withheld from all training data | both hold |
| N6 | Python/Rust parity on fixtures | max absolute difference ≤ 1e-5 |
| N7 | Latency per decision on the reference CPU | p95 ≤ 10 ms |
| N8 | Safety invariants | zero decisions outside the legal candidate list; zero policy bypass |

A network that misses any gate is not promoted and the rule decider stays; this is an acceptable outcome, not a failure
of the programme. Promotion is the owner's decision in T171, recorded in the task note.

The cognitive evaluation (T172, SR-K7) is a **report, not a gate**: unsupported-claim pass-through, faithfulness to
sources, abstention calibration, constraint recall after N turns and false completion rate, measured with at least two
advisors. Results are stated as system measurements; no model is described as qualified by them.

## 9. Decision data and owner runs

### 9.1 Dataset (T168)
Examples are `(state features, candidate list, chosen action, outcome)` from event logs. Labels come from **outcomes**
(the Claim was accepted by the gate; the answer passed the outside-set check; the user did not retract), not from the
rule decider's own choices, so the network does not merely imitate its teacher. Where logs are scarce the scenario suite
generates counterfactual examples by replaying a scenario with each legal candidate against a placeholder or recorded
advisor; these are labelled `source: scenario` and prove mechanics, not real-world behaviour, and the held-out set is
reported with the share of scenario examples.

Rules: ResearchLLM or network training data drawn from the brain uses only Sources and verified Claims, never
model-generated text (SR-K6); no text produced by Claude or another proprietary model is distilled into training data
(D48); every example has provenance and a checksum; the held-out split is sealed before training; a seeded
model-generated example must be excluded by test.

### 9.2 Owner runs
The agent writes the code, tests that do not train, and prepares commands; the owner executes: training (T170, with a
budget and stop rules in the command), held-out evaluation (T171) and the cognitive evaluation (T172). Intake checks
reject logs and manifests that do not match the prepared commands. The agent never enables training authorisation.

## 10. Alternatives considered
- **Let the advisor decide (programme-2 behaviour, extended with prompts).** Rejected: the component that may hallucinate
  would still decide when to stop and what to trust.
- **Network chooses and generates (a second language model as controller).** Rejected: generative, unauditable, and the
  failure this ADR exists to remove.
- **Rules only, forever.** Kept as the safe default and baseline; a learned scorer is attempted because rules do not adapt
  to the measured track record of advisors, but promotion is conditional on the gates.
- **Knowledge as embeddings only.** Rejected: no span, no provenance, no retraction handling (ADR-004).
- **Separate stores for Claims and Sources.** Rejected: one Obsidian vault keeps the format of SR-L2 and the owner can read
  and audit it by hand.

## 11. Consequences
- `laris-vault` gains the main-brain profile (T163); the server gains the gate and the brain tools (T164, T165); the
  harness gains the composer and checks (T166) and the rule decider behind the `Decider` seam (T167).
- The network (T169) adds Python training code to the model block and a dependency-free forward pass in `laris-core`.
- Answers become shorter and more often abstain; that is the intended cost of faithfulness.

## 12. Risks
- **Retrieval-based contradiction and outside-set checks have a nonzero miss rate.** Mitigation: measure and report it; the
  advisor-as-judge may only veto; `reviewed` level for high-stakes Claims.
- **Little real decision data.** Mitigation: scenario-generated examples are labelled and reported; promotion may never happen.
- **Sources can be wrong.** The brain guarantees an answer matches its sources, not that the sources are right;
  `corroborated`, `verified` and `reviewed` reduce but do not remove this.
- **Gate or schema drift.** Mitigation: the audit record and the integrity lock; changes to the closed action set, the
  ladder or the gates need an ADR amendment.
- **Learnable policy.** Mitigation: safety stays outside the action set and outside the network (N8).

## 13. Validation
- SR-K1: the owner accepts this ADR; no brain code before it.
- Each later task cites the section it implements (T163 section 3, T164 section 4, T165 sections 3 and 4, T166 section 6,
  T167 section 7, T168-T169 sections 5 and 9, T170-T171 section 8, T172 section 8).
