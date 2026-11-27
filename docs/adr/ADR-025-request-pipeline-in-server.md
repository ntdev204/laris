---
document_id: "DOC-ADR-025"
title: "ADR-025: Request pipeline in the server"
document_type: "adr"
status: "ACCEPTED"
version: "0.2.0"
created_at: "2026-11-20"
updated_at: "2026-11-27"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - ".claude/spec/spec.md"
  - ".claude/spec/plan/2-system.md"
  - ".claude/spec/task/2-system.md"
  - "docs/architecture/THREAT_MODEL.md"
decision_references:
  - "ADR-004"
  - "ADR-008"
  - "ADR-021"
  - "ADR-024"
change_summary: "Accepted by the owner 2026-11-20 (task T238): stage order, what moves to the server, vault and brain placement, P1 step events and evidence list, failure modes, threat-model changes."
---

# ADR-025: Request pipeline in the server

## Metadata
- **Status:** ACCEPTED on 2026-11-20 by the owner ("Chấp nhận"), as drafted; pipeline code (T239-T243) may now start. Any change to D49-D56 needs an amendment to this ADR.
- **Requirements:** SR-S4, SR-S5, SR-K1 · **Task:** T238 · **Decisions:** D49-D56 · **Builds on:** ADR-021 (D28, D37, D39), ADR-024 (brain, closed action set, rule decider), ADR-004, ADR-008
- **Amends:** D28 (where the loop runs) and D39 (where the evidence check runs), as set out in section 3. Every other ADR-021 decision stands.
- **Qualification:** the foundation model and ResearchLLM (Qwen3.5-9B through the open-weight backend) are NOT QUALIFIED. This ADR moves *mechanics* into the server and makes answers faithful to their sources; it claims no model capability. Results of T243 are system measurements only.

## 1. Context
Today the server's chat route authenticates, reserves quota, composes policy and forwards one request to the model; the client runs the agent loop, the Prefilter (T229), lexical retrieval over a local vault (T230) and the harness (T232, `HarnessModel`), and checks evidence once before display (D39). Two things follow from that:

- Everything that decides *whether and how the model is asked* sits on the machine of a user the server must treat as untrusted (B3 of the threat model). A modified client can skip the Prefilter, the retrieval and the evidence check.
- The main brain (ADR-024) is held by the server (SR-K2, SR-K3). The server owns the knowledge but cannot use it to ground an answer unless the client forwards it, which would copy confidential notes to every client.

The owner's direction of 2026-11-20 ("tích hợp toàn bộ vào hệ thống") is that a request goes client → server, and the server checks, filters, grounds and decides before the model is asked, then returns the answer through the evidence gate. D28 and D39 were fixed on 2026-11-13 for a different reason (tools must run next to the user's files). This ADR keeps that reason and moves everything that does not depend on it.

## 2. Pipeline

One **turn request** is one `POST /v1/laris/chat`. The server runs these stages in order. Each stage ends in `ok`, `skipped` (not configured or not applicable), `stop` (the turn ends here with the stage's answer) or `error`.

```text
client ─P1─► 1 auth ─► 2 policy ─► 3 prefilter ─► 4 retrieval ─► 5 decider ─► 6 model ─► 7 evidence gate ─► 8 assembly ─P1─► client
                         │            │ hit: stop        │ none: abstain        │ abstain/ask: stop        │ fail: retry ≤ N, then abstain
                         └ compose    └ canned answer    └ passages + ids       └ rule + signals logged    └ strip unsupported
```

| # | Stage | What it does | Existing code | Task |
| :-: | :--- | :--- | :--- | :--- |
| 1 | Auth | Version header (426), key, role, quota reservation, body limits (unchanged) | `laris-server` access | done |
| 2 | Policy | Composes system prompt, rules and the one workflow skill for the turn from `.laris/`; leak guard armed | `laris-server` policy | done |
| 3 | Prefilter | Deterministic rules on the **latest user message** (greeting, help, version, fixed refusals, injection patterns); a hit is the answer and the model is **never called** | `PrefilterModel` (T229) | T239 |
| 4 | Retrieval | Lexical retrieval (BM25 / TF-IDF fused, T230) over the server's **main brain**; returns passages with note id, span and hash; the system brain stays progressive disclosure by tool (SR-S5) and is not a retrieval corpus | `VaultSource`, `laris-brain` | T239, T240 |
| 5 | Brain decider | The rule decider (ADR-024 section 7) picks one action from the legal candidates of this stage (section 4) and logs its rule and signals | `laris-brain` decide / seam | T241 |
| 6 | Model | One call to the model service (P2) with the policy, the conversation, the client's tools and the passages as marked, untrusted data | harness prompt, `model.rs` | T239 |
| 7 | Evidence gate | Every claim of the draft must cite a passage that exists in this turn's evidence; unsupported sentences fail the draft; the draft is retried up to `pipeline.max_attempts`, then the turn abstains | `HarnessModel` (T232), outside-set check (ADR-024 6.3) | T239, T241 |
| 8 | Assembly | Builds the answer and the `laris` block: text with citations, evidence list, step list; reasoning stays operator-only (SR-S4) | `answer.rs` composer | T239, T242 |

Stages 3 to 8 are configuration-gated (`pipeline.*`, no hardcoded tunable). With every stage off the route behaves as today; this is the migration path and the rollback.

### 2.1 Order, and why
- **Prefilter before retrieval and the model:** a hit costs no retrieval and no tokens; a hostile or trivial message never reaches the model. It sees only the latest *user-authored* message of a turn; a continuation after a tool result (the last message has role `tool`) skips stage 3, because tool output is data, never a user request.
- **Policy before Prefilter:** the canned texts and rules live in `.laris/` (integrity-locked) and are applied under the same lock as the prompt.
- **Retrieval before the decider:** the decider's inputs are measured signals (ADR-024 5.3); coverage is one of them.
- **Gate after the model, once:** see D52. A turn that streams a free answer is gated before the first token is sent (section 2.2).

### 2.2 Buffering
The evidence gate needs the whole draft. When retrieval returned passages (the answer is *grounded*), the server buffers the model's draft, checks it, retries if needed and then sends the checked text; the client sees step events while it waits (section 5). When the decider chose a **free** answer (no coverage is required: small talk the Prefilter did not catch, tool planning, an answer that cites no source) the model stream is forwarded unbuffered as today and carries no evidence claim. The buffer is bounded by `pipeline.max_draft_chars` and by the model concurrency limit (SR-S6); exceeding it is `error`, not truncation.

A tool-call proposal from the model (the model asks to run a client tool) is not buffered and not gated by stage 7: it is passed to the client, whose policy and sandbox decide (B2: model output is a proposal).

## 3. What stays on the client, what moves

| Part | Where | Reason |
| :--- | :--- | :--- |
| Agent loop (plan, step, reflect, stop), event log, `/rewind`, checkpoints | **Client** (D28 stands) | The loop must drive tools that touch the user's files |
| Tool execution, sandbox, permissions, hooks, approvals, redaction before send | **Client** | Same reason; B1/B2 |
| Project vault and local retrieval tool over the user's own notes | **Client** | Private research (A5); never copied to the server (D40 spirit) |
| Learning data derived from the event log | **Client** (D40 stands) | Privacy |
| Prefilter, main-brain retrieval, brain decider, model call, evidence gate for server-held evidence, answer assembly | **Server** (moves) | Cannot be skipped by a modified client; uses confidential server data |
| System prompt, rules, workflows, system brain | **Server** (unchanged) | Confidentiality (A1) |
| Main brain, write gate, ingestion, retraction | **Server** (T240) | SR-K2, SR-K3 |
| Evidence check for statements grounded in **local** tool output or the project vault | **Client** | The server never sees local results |

**D28 amended.** The agent *loop* stays on the user's machine. The *per-request pipeline* around every model call runs on the server. The server still runs no loop and executes no tool for the user; a model proposal to run a tool is returned to the client exactly as today. The ladder is unchanged: each rung is reached by server and system together.

**D39 amended.** The evidence check is performed **once per piece of evidence, by the side that holds it**. The server gates statements that cite server-held passages and returns them in the evidence list; the client gates statements that cite its own tool results or project notes. A displayed sentence is never checked twice by the same rule: the server marks each evidence entry with `origin: server`, and the client gate skips entries of that origin and checks only the rest. The client never trusts an `origin: server` entry it did not receive from the server over the pinned connection (B3), and the server ignores any `evidence` or `steps` field in a *request* (section 5).

## 4. Decider at this stage

The decider is the ADR-024 seam; T241 puts the rule decider (section 7) behind it. In the server turn the legal candidates are a subset of the closed set; the set itself is **not changed** by this ADR.

| Action | At stage 5 | Effect |
| :--- | :--- | :--- |
| `answer` | legal when accepted Claims or passages cover the question at the required level | Stage 6 drafts from them and stage 7 gates the draft; if the Claims are enough and `pipeline.compose_without_model` is on, the composer answers without the model (T241 scenario "answer from accepted claims without calling the model") |
| `abstain` | legal when no coverage exists and nothing else is legal | Turn ends with an abstention and the reason code; no model call |
| `ask_user` | legal when a required slot is missing (closed test) | Turn ends with a question |
| `retrieve` | legal while retrieval budget remains | One more retrieval with a rewritten query (lexical, no model) before stage 6 |
| `ask_advisor` | the default when coverage is partial or the request is a free or agentic one | Stage 6 |
| `stop` | hard limit holds (budget, time, cycle) | Turn ends; the reason is logged |
| `run_tool`, `acquire`, `verify` | **not decided by the server pipeline.** A `run_tool` proposal is returned to the client; `acquire` and `verify` stay remote tools (T165) the model or the client calls through `/v1/laris/tools/{name}` | Safety stays outside the decider (ADR-024 5.1) |

The decision network stays **off** (not promoted, T171); a configuration value cannot turn it on without the owner's promotion. The server is **stateless between requests**: the loop counters the decider needs (steps used, attempts) come from the client in `laris.turn`, are clamped to server limits, and are inputs only, never authority. A forged counter can make the server stop earlier or later within its own hard caps, never skip a stage.

## 5. Where the vault and the main brain live

**D50 (proposed).** One **shared main brain per server**, in one Obsidian-format vault on the server's disk (configuration path), covered by the integrity and leak controls of SR-S5.

- **Writers:** only the write gate (ADR-024 4). Ingestion and retraction are `admin` operations. Clients cannot write it, and there is no per-user write path.
- **Readers:** the pipeline reads it for retrieval. A caller needs the permission `brain.read` (new, default on for the `user` role); without it stage 4 is `skipped` and the answer is not grounded in it.
- **What leaves the server:** only the cited Claim wording and spans an answer uses, with note ids and levels in the evidence list. No route returns a note or a vault listing to a client; the leak guard keeps comparing replies with policy and system-brain text and is extended with a per-answer budget of main-brain characters (`pipeline.max_evidence_chars`) so a prompt cannot dump the vault one answer at a time (TM-33).
- **Per-user private vaults on the server:** not built. They would copy private notes to the server, split corroboration (ADR-024 3.2 needs independent Sources in one place) and multiply storage. The user's own notes stay in the client's project vault and reach a turn through a local tool, as they do today.
- **System brain** (policy guidance) is a different store with a different job (SR-S5: progressive disclosure to the model by tool); it is not merged with the main brain and is never a retrieval corpus.

## 6. Protocol P1

Additions are optional fields of the `laris` block of the response, so a client that does not know them ignores them (the `extra` map already carries unknown fields). There is no generation-1 compatibility to keep (D43); the schema is regenerated and checked (T242), and `X-Laris-Protocol` is bumped so an old client gets 426 instead of silently losing the stages.

```text
laris: {
  brain:    [titles]                        // existing: system-brain notes consulted
  steps:    [{ stage, outcome, ms, code? }] // new: stage ∈ {prefilter, retrieval, decider, model, gate, assembly}
                                            //      outcome ∈ {ok, skipped, stop, error}; code = rule id or reason, never message text
  decision: { action, rule }                // new: the action the decider chose and the rule that fired
  evidence: [{ id, origin, level, title, start, end, sha256 }]  // new: server-held evidence cited by the answer
}
```

- `steps` are sent as SSE `laris`-only chunks as each stage ends, so the client can show "checking the knowledge base", "asking the model". Event order is fixed: steps (in stage order), then `evidence` and `decision` once, then text chunks, then usage, then `[DONE]`.
- `evidence` carries ids, level, source title, offsets and hash — enough for the client to show a source and to verify the span through the existing retrieval route if the user asks; the text of a note is not in it beyond what the answer already quotes.
- A request that carries `steps`, `decision` or `evidence` has them dropped (the client cannot assert evidence for itself).
- A Prefilter hit and an abstention are normal answers: `choices` carries the text, `steps` shows where the turn stopped.

## 7. Failure modes

| Failure | Behaviour | Reported as |
| :--- | :--- | :--- |
| Model service down or slow (stage 6) | No retry beyond the existing bounded one; typed `error` event; quota reservation released; a Prefilter hit or a compose-without-model answer is still served | `steps[model].outcome = error`, code `model_unavailable`; trace outcome `midstream_error` or `error` |
| Vault missing, empty or unreadable (stage 4) | Stage is `skipped`; the decider sees zero coverage and cannot choose `answer` from the brain; free answers continue, a question that requires grounding abstains with `no_evidence` | `steps[retrieval]` = `skipped` or `error`; never a silent ungrounded answer presented as grounded |
| Policy lock fails | Server does not start (unchanged, TM-04) | startup error |
| Evidence gate rejects every attempt | Abstain with `unsupported_draft`; the draft text is not sent | `steps[gate].outcome = stop` |
| Draft larger than the buffer | `error`, nothing truncated | code `draft_too_large` |
| Prefilter rules file missing or invalid | Server does not start when `pipeline.prefilter` is on (fail closed); with it off the stage is `skipped` | startup error |
| Client disconnects while buffering | The draft is discarded, quota settled for tokens actually used, trace outcome `client_gone` | trace |
| One stage panics or times out | The turn ends with `error` for that stage; no later stage runs; the process stays up | `steps[stage].outcome = error` |

Stage timeouts and the attempt limit are configuration (`pipeline.stage_timeout`, `pipeline.max_attempts`), not constants.

## 8. Audit and quota
Each stage and its time are recorded in the trace row of the request (route, key id, stage, outcome, ms, rule id, evidence ids, counts) **without message text, passages or draft text** (SR-S7). A Prefilter hit and an abstention cost no completion tokens; the request itself is still counted against the key's request quota. Buffered drafts that fail the gate count their tokens (the model was called).

## 9. Threat-model changes
New rows for `docs/architecture/THREAT_MODEL.md`, added by T239-T243 with their test ids (the tests are created by the owning task):

| Id | Threat | Attacker | Control | Task | Test id |
| :--- | :--- | :--- | :--- | :--- | :--- |
| TM-31 | A modified client skips the Prefilter, retrieval or the gate | X4 | Stages run on the server; `steps`, `decision` and `evidence` in a request are dropped; the client gate ignores `origin: server` entries it did not receive from the server | T239, T242 | SEC-PIPE-01 |
| TM-32 | A retrieved passage carries instructions (injection through the main brain or a poisoned Source) | X1, X6 | Passages are marked untrusted data, folded to one line, redacted; an instruction-like passage cannot change the stage order or the decider; the gate checks the draft against passages, not the reverse | T239 | SEC-PIPE-02 |
| TM-33 | Bulk reading of the main brain through answers | X8 | `brain.read` permission, per-answer evidence budget, per-key quota; no route returns notes; leak guard extended | T240 | SEC-PIPE-03 |
| TM-34 | Unbounded buffering or retry loops exhaust memory or the model | X4 | `max_draft_chars`, `max_attempts`, model concurrency limit, stage timeouts; counters from the client are clamped | T239 | SEC-PIPE-04 |
| TM-35 | Forged loop counters or session id steer the decider | X4 | Counters are inputs clamped to server hard caps; they never skip a stage or widen the legal set | T241 | SEC-PIPE-05 |
| TM-36 | Client writes the main brain | X4, X2 | Only the write gate writes; no client write route; ingestion and retraction need `admin` | T240 | SEC-BRAIN-01 (existing, extended) |
| TM-37 | Stage rules (Prefilter, decider thresholds) learnable or editable at run time | X8, X5 | Rules and canned texts in `.laris/` under the integrity lock; thresholds are configuration; the network stays off | T239, T241 | SEC-INT-01 (existing, extended) |
| TM-38 | Audit or step events carry message text | X8, X5 | Step `code` is a rule id or reason code; test scans rows and events for the request text | T239, T242 | SEC-KEY-02 (existing, extended) |

The server already receives every user message; the pipeline does not widen what the server *sees*. It widens what the server *does with it*, so the controls above are on what stays out of logs and what a key may read. The honest limit stays (ADR-024 sections 4 and 6.3): retrieval, contradiction and outside-set checks are filters with a measured, non-zero miss rate. The pipeline guarantees faithfulness to accepted sources up to that rate, not truth.

## 10. Decisions (accepted)

| ID | Decision | Choice | Alternative rejected, reason |
| :--- | :--- | :--- | :--- |
| D49 | Pipeline location | The per-request pipeline (Prefilter, retrieval, brain decider, model call, evidence gate, assembly) runs in the server for every chat turn; the loop stays on the client (amends D28) | Whole loop on the server: tools would run away from the user's files; pipeline on the client: skippable, no access to the main brain |
| D50 | Main brain placement | One shared vault on the server, read by `brain.read`, written only by the gate; no per-user server vaults | Per-user vaults: private notes copied to the server, split corroboration, storage multiplied |
| D51 | Stage order | auth, policy, prefilter, retrieval, decider, model, gate, assembly, as in section 2 | Retrieval before Prefilter: pays retrieval for trivial and hostile messages |
| D52 | Evidence check | Once per evidence, by the side that holds it; server entries carry `origin: server` (amends D39) | Server only: cannot see local results; both sides on everything: duplicate logic (ADR-004) |
| D53 | Grounded answers | Buffered, gated, then streamed; free answers and tool-call proposals stream unbuffered and claim no evidence | Stream-then-retract: unsupported text would already be on the user's screen |
| D54 | Decider | Rule decider behind the ADR-024 seam; closed set unchanged; `run_tool`, `acquire`, `verify` not decided by the server pipeline; network off | Network on the server now: not promoted, no held-out result |
| D55 | P1 | Optional `laris.steps`, `decision`, `evidence`; the request side drops them; `X-Laris-Protocol` bumped | Separate events endpoint: two connections, ordering problems |
| D56 | Rollout | Every stage is configuration-gated and off by default until T243 passes; all off equals today's behaviour | Switch on at once: no rollback |
| D69 | STEM profile (A1) | A stage after the Prefilter and the research tools; entry by a runner item, or automatic for a first STEM question of a chat; loop in Rust, SymPy and the rule set behind the model service's `stem_check`; network tools off | An explicit STEM mode in each client: the owner chose automatic |

### 10.1 Amendment A1 (owner, 2026-11-27, T284): the STEM evaluation profile as a stage

The harness measured in Python (T278-T280, T285-T287, frozen candidate of T290) runs inside the pipeline, so the
system that is measured is the one deployed, and the web client, the terminal client and the benchmark runner are
answered alike under one configuration (`configs/stem-benchmarks.json`: its `baseline` and `harness` sections, read
unchanged, and a `server_profile` section for what only the server needs).

- **Place.** After the Prefilter and after the server's research tools (a research turn stays a research turn);
  before retrieval over the main brain. A turn it takes never reaches the policy gateway: network tools are off.
- **Entry (D69).** A request that carries an item (`laris.stem`: id, question, options; the runner) always enters.
  With `LARIS_SERVER__STEM_PROFILE=auto` (the owner's choice, 2026-11-27: "Automatic") a chat turn enters when it is
  the first question of its conversation, has no attached documents and passes the prompt filter with a STEM signal;
  lettered trailing lines (`A.`, `B)`, `(C)`, in order, at least two) are read as options. Any other turn, a filter
  stop included, goes on through the pipeline as before. `request` takes only runner items; `off` (the default
  outside `docker/compose.chat.yaml`) turns the stage off.
- **What runs where.** The loop (router, notes, draft with the thinking budget per class, conclusion of a cut reply,
  retries, formalisation, self-consistency, review, notes check) is Rust (`laris-server::stem`). The engine is the vLLM
  server of T282, the chat template rendered by the engine itself (`/tokenize`, `/detokenize`). The solver is the
  remote tool `solve_stem`; the deterministic steps that need SymPy or the T286 rule set (prompt filter, model-free
  patterns, repair, solver answer, answer equivalence, cross-check) are the remote tool `stem_check` of the model
  service, which runs the reference's own Python code and is not offered to the chat model. Retrieval reads the frozen
  snapshot (`harness.retrieval.snapshot`) through `MainBrain`, mounted read-only; a missing or different snapshot stops
  the server.
- **Display.** Each step ends in a step event of stage `stem` whose code names the step and its outcome, never text;
  both clients list them. The answer is the visible text of the reply the draft was read from, then one answer line
  (`server_profile.chat.answer_line`: the answer and where it came from). The record of the turn (route, steps,
  answers, cost, configuration and snapshot hashes; no item text) goes in `laris.stem`. While a step runs the server
  sends an empty keep-alive event every `server_profile.heartbeat_ms`.
- **Parity.** `scripts/stem_profile_fixtures.py` runs the Python harness on scripted scenarios and the Rust tests
  replay them call for call; on development items `scripts/stem_benchmarks.py harness --server-bin` (or `--server`)
  and the Python harness are compared by `harness-parity`. The Python harness stays the reference.
- **Not a qualification.** The profile answers without citations; the evidence gate of normal chat is unchanged. The
  model and the system are NOT QUALIFIED until gates B1-B6 pass on the sealed test (ADR-026).

## 11. Alternatives considered
- **Keep the engine on the client (the 2026-11-13 position).** Fails the owner's goal: a modified client skips every check, and the main brain cannot ground answers without being copied out.
- **Move the whole agent loop to the server.** Rejected for D28's reason: tool runs, files and approvals belong on the user's machine; a server loop would need a remote file and sandbox protocol and would hold user data.
- **A separate pipeline service between server and model service.** Rejected: another process and protocol for logic that shares the server's auth, quota, policy and trace; the pipeline is a module of `laris-server` behind the existing backend seam.
- **Stream while checking and retract on failure.** Rejected: P1 has no retraction, and a user may act on text that is withdrawn.
- **Run retrieval on the client against a downloaded vault.** Rejected: copies the confidential main brain to every client.

## 12. Consequences
- `laris-server` depends on `laris-policy` (already), `laris-brain` and `laris-retrieval`; Cargo and `cargo deny` need no new external crate. T239 adds the adapter from the server backend to the `Model` seam used by `PrefilterModel` and `HarnessModel`.
- Grounded answers are slower (buffered, one or more draft attempts) and more often abstain; that is the intended cost of faithfulness (ADR-024 11).
- The client loses nothing it needs: it keeps the loop and tools, drops its own Prefilter and harness for chat turns when the server reports the pipeline (the code stays for headless runs against a server without it and for tests).
- Compose and the runbook gain pipeline configuration and a vault mount (T243).
- If the owner changes a decision here, the spec table (D49-D56), the affected tasks and this ADR change together in one task.

## 13. Risks
- **Latency of buffering** on a slow model: mitigated by step events, a draft cap and stage timeouts; measured in T243.
- **Server becomes a single point of control:** an outage of the pipeline blocks grounded answers. Mitigated by the stage switches (rollback to today's route) and by serving Prefilter hits without the model.
- **Over-abstention** from a strict gate: measured in the cognitive evaluation (T172 repeated in T243); thresholds are configuration.
- **Shared vault, shared mistakes:** a wrong accepted Claim reaches every user; mitigated by retraction and consolidation (ADR-024 4) and the `reviewed` level for high-stakes Claims.
- **Not qualified:** a pass of the scenario and smoke tests proves mechanics and the system's faithfulness to sources; it does not qualify any model.

## 14. Validation
- SR-K1 / T238: the owner accepts this ADR; **no pipeline code before it**.
- Each later task cites the section it implements: T239 sections 2, 7, 8; T240 section 5; T241 section 4; T242 section 6; T243 sections 2, 7, 9 and the exit criteria of Phase 47.
- Accepted 2026-11-20: spec decisions D49-D56 and the D28/D39 amendments are recorded in the spec; the THREAT_MODEL rows of section 9 are added by the owning tasks.
