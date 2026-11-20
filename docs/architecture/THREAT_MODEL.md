---
document_id: "DOC-ARCH-THREAT-001"
title: "LARIS Generation-2 Threat Model"
document_type: "architecture"
status: "DRAFT"
version: "0.2.0"
created_at: "2026-11-18"
updated_at: "2026-11-19"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/adr/ADR-021-rust-generation.md"
  - "docs/adr/ADR-004-evidence-provenance-first-class.md"
decision_references:
  - "ADR-004"
  - "ADR-021"
change_summary: "First version (task T122): assets, attackers, trust boundaries, 30 threats each with a control and a test id."
---

# LARIS Generation-2 Threat Model

Implements requirement SR-G5 and expands section 9 of the ledger specification (`.claude/spec/spec.md`). It covers the
Rust system (loop, harness, prompt), the Rust server and client, the model service boundary and the main brain. Task
T154 turns every row into an automated test in CI.

Status of this document: the controls and tests below are **planned**. Nothing in the tables is implemented or measured
yet, except where section 5 says otherwise; a row becomes real when its owning task is done and its test id exists and
passes. The foundation model is NOT QUALIFIED, and this document makes no claim about model capability.

## 1. Scope and trust boundaries

```text
 hostile input ──►  user machine (client: loop, harness, prompt, TUI)
 (documents,          │  B1: project folder, documents and tool output are DATA
  notes, folders)     │  B2: model output is a PROPOSAL, never an authority
                      ▼
                    P1 over HTTPS (B3: network boundary, the client is untrusted by the server)
                      ▼
                    Caddy ──► laris-server (policy, brain, keys, traces)
                      │  B4: internal network only below this line
                      ├──► PostgreSQL
                      └──► model service (Python, weights)  (B5: P2, no direct client access)
```

In scope: confidentiality of server-only policy and brain, integrity of the evidence chain, key and quota abuse,
confinement of agent commands, supply chain of the Rust and Python builds, poisoned training and brain data.

Out of scope (spec section 9): a local administrator (root) on the user's machine or on the server host; physical
access; defects of the operating system kernel beyond the sandbox mechanisms LARIS configures.

## 2. Assets

| Id | Asset | Why it matters |
| :--- | :--- | :--- |
| A1 | System brain and policy (`.laris/prompts`, `rules`, `workflows`, `brain`, `LARIS.md`) | Confidential; server-only; integrity locked |
| A2 | Main brain (programme 3 vault of Sources and Claims) | Must hold only sourced knowledge |
| A3 | Credentials: API keys, master secret, database password, signing key | Compromise gives full access or forged releases |
| A4 | Keys database and quotas | Billing, abuse control, audit |
| A5 | User files and project vaults | Private research; must not be modified or read outside permission |
| A6 | Datasets, checkpoints, model weights | Costly; must keep lineage and sealed splits |
| A7 | Collected learning data | Private; must never leave the machine or enter Git |
| A8 | Evidence chain (cited spans) | Basis of every research answer (ADR-004) |
| A9 | Release artefacts and installer | Executed on user machines |

## 3. Attackers

| Id | Attacker | Capability assumed |
| :--- | :--- | :--- |
| X1 | Hostile document or note | Text the model reads: PDF, Markdown, web text, tool output |
| X2 | Manipulated model | The model or a remote tool returns adversarial or false output |
| X3 | Hostile project folder | Planted `.laris`, settings, hooks, skills, symlinks, huge files |
| X4 | Hostile network client | Holds no key or a low-privilege key; crafts requests, floods, reads slowly |
| X5 | Compromised container | Code execution inside one container of the compose stack |
| X6 | Poisoned data source | Tampered dataset, brain note or learning example |
| X7 | Supply-chain attacker | Malicious or typosquatted dependency, tampered release |
| X8 | Curious user of the server | Valid key; tries to extract policy, brain text or other users' data |

## 4. Threats, controls and tests

Test ids are `SEC-<area>-<nn>`. A test id names a test that the owning task creates; T154 collects them in one suite (section 5).
Requirement ids refer to `.claude/spec/spec.md`. "Task" is the task that builds the control and its test.

### 4.1 Confidentiality of policy and brain (A1, A2)

| Id | Threat | Attacker | Control | Req | Task | Test id |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| TM-01 | Chat reply leaks system prompt, rules or workflow text | X8, X2 | Policy composed on the server only; outbound leak guard compares replies with policy text | SR-S4 | T146 | SEC-LEAK-01 |
| TM-02 | Reasoning reaches a client | X8 | Reasoning kept for the operator; absent from chat bodies and events | SR-S4 | T146 | SEC-LEAK-02 |
| TM-03 | System brain note text copied into answers or audit | X8 | Progressive disclosure within budgets; only note ids in audit and `LarisMeta` | SR-S5, SR-S7 | T147 | SEC-LEAK-03 |
| TM-04 | Policy file edited on disk, server runs altered rules | X5, X7 | `integrity.lock` verified at start; a changed policy file stops the server; policy mounted read-only | SR-S4, SR-S8 | T146 | SEC-INT-01 |
| TM-05 | Policy or weights baked into an image and distributed | X7, X5 | Images hold no policy and no weights; both mounted read-only at run time | SR-S8 | T153 | SEC-DEP-01 |

### 4.2 Keys, quotas and the HTTP surface (A3, A4)

| Id | Threat | Attacker | Control | Req | Task | Test id |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| TM-06 | Database dump reveals usable API keys | X5, X8 | Digest-only storage with a master secret held outside the database | SR-S2 | T143 | SEC-KEY-01 |
| TM-07 | Key or secret printed in a log, error or trace | X5, X8 | No key printed; no message content in logs or traces | SR-S1, SR-S7 | T141 | SEC-KEY-02 |
| TM-08 | Parallel requests exceed a quota | X4 | Quota reserved atomically and settled in one transaction; overshoot bounded by one reservation | SR-S2 | T143 | SEC-QUOTA-01 |
| TM-09 | Revoked or expired key keeps working | X4 | Expiry and revocation checked on every request; admin routes need an admin role | SR-S2 | T143 | SEC-KEY-03 |
| TM-10 | Oversized, malformed or length-less body exhausts memory | X4 | Bodies validated before work; explicit 400, 411 and 413 | SR-S1 | T141 | SEC-HTTP-01 |
| TM-11 | Request flood or slow client holds connections | X4 | 429 limits, timeouts, bounded model concurrency, streaming with backpressure | SR-S1, SR-S6 | T141, T144 | SEC-HTTP-02 |
| TM-12 | Forged `X-Forwarded-For` evades per-address limits | X4 | Client address taken from the header only through trusted proxies | SR-S1 | T141 | SEC-HTTP-03 |
| TM-13 | Mid-stream failure exposes internals or leaves the client hanging | X4, X2 | Mid-stream errors become a typed `error` event; a model failure never leaks its raw message | SR-P1, SR-S6 | T144 | SEC-HTTP-04 |
| TM-14 | Role escalation through an admin or tool route | X4, X8 | Roles and permissions checked per route; `/tools/{name}` limited to registered tools | SR-S2, SR-S6 | T143, T149 | SEC-KEY-04 |
| TM-15 | Interception or impersonation of the server on the network | X4 | TLS through Caddy; certificate pinning in the client; protocol version check | SR-H12, SR-S8 | T128, T153 | SEC-NET-01 |

### 4.3 Hostile content and the agent (A5, A8)

| Id | Threat | Attacker | Control | Req | Task | Test id |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| TM-16 | A document instructs the model to run commands or leave the sandbox | X1, X2 | Tool output and documents marked untrusted; injected requests refused by policy; permission rules gate every call | SR-H4, SR-H10 | T136 | SEC-INJ-01 |
| TM-17 | Secret in a file or tool output reaches the model or server | X1 | Redaction before anything leaves the machine | SR-H10 | T136 | SEC-INJ-02 |
| TM-18 | Hook command or hook output is hostile | X3, X1 | Hooks declared only in global settings; timeout and malformed-output handling; hook output untrusted | SR-H5 | T133 | SEC-PERM-01 |
| TM-19 | Planted project settings, skills or commands run code | X3 | Folder trust; project commands and skills only in trusted folders; planted settings ignored | SR-H5 | T133 | SEC-PERM-02 |
| TM-20 | Write outside permission (path traversal, symlink, `deny` bypass) | X2, X3 | Permission modes and rules, deny wins; canonical paths; a denied path is never written | SR-H5, SR-H4 | T132, T133 | SEC-PERM-03 |
| TM-21 | Agent command escapes the allowed roots | X2, X1 | OS sandbox on Linux, macOS and Windows; writes outside allowed roots fail | SR-H6 | T134, T135 | SEC-SBX-01 |
| TM-22 | Python environment corrupted or built twice concurrently | X3, X5 | `~/.laris/.venv/` built once under a lock and repaired after deletion | SR-H6 | T135 | SEC-SBX-02 |
| TM-23 | Fabricated citation or unsupported claim shown as evidence | X2 | Evidence gate: every cited span must exist in retrieved or returned evidence; unsupported statements marked; checked once before display | SR-H7 | T137 | SEC-EVID-01 |
| TM-24 | A destructive tool call cannot be undone | X2 | Checkpoints before edits and `/rewind` | SR-H4 | T132 | SEC-PERM-04 |
| TM-25 | Remote tool result trusted as local fact | X2, X1 | Remote tool output gets the same untrusted marking and output limits as local tools | SR-H4 | T132, T149 | SEC-INJ-03 |

### 4.4 Local data (A5, A7)

| Id | Threat | Attacker | Control | Req | Task | Test id |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| TM-26 | Collected learning data leaves the machine or enters Git | X8, X6 | Derived from the local event log only when `learning.collect` is on; absent from P1 requests and from the repository | SR-H11 | T138 | SEC-DATA-01 |
| TM-27 | A crash or concurrent writer corrupts a vault or project database | X5, X3 | Atomic vault writer; SQLite WAL with migrations; two writers lose nothing | SR-L2, SR-H9 | T127, T129 | SEC-DATA-02 |

### 4.5 Brain, data and supply chain (A2, A6, A9)

| Id | Threat | Attacker | Control | Req | Task | Test id |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| TM-28 | Model-generated text becomes knowledge in the main brain | X2, X6 | Single write gate; a Claim needs a resolvable Source span; model-only claims refused; dependants downgraded on retraction; on the server the gate is reached only by `brain.manage` (admin) and no client write route exists | SR-K3, SR-K2 | T164, T240 | SEC-BRAIN-01 |
| TM-29 | Poisoned or leaked data enters training or a held-out split | X6 | Sealed test splits and data checksums; manifests with provenance; a seeded model-generated example is excluded; agents never train | SR-M3, SR-M4, SR-K6 | T168 | SEC-DATA-03 |
| TM-30 | Unapproved or malicious dependency, or a training call, enters the build | X7 | `cargo deny` allow-list from T119; vendoring; the no-training guard; signed releases | SR-G2, SR-G3, SR-C6 | T121, T159 | SEC-SUP-01 |

### 4.6 Request pipeline (ADR-025)

| Id | Threat | Attacker | Control | Req | Task | Test id |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| TM-31 | A modified client skips the Prefilter, retrieval or the gate | X4 | Stages run on the server; `steps`, `decision` and `evidence` in a request are dropped | SR-S4 | T239, T242 | SEC-PIPE-01 |
| TM-32 | A retrieved passage carries instructions | X1, X6 | Passages are redacted, folded to one line and read by the shield; one that gives orders is dropped before the model sees it; the gate checks the draft against the passages | SR-S4, SR-M11 | T239 | SEC-PIPE-02 |
| TM-33 | Bulk reading of the main brain through answers | X8 | `brain.read` permission (default on for `user`), a per-answer evidence budget (`LARIS_SERVER__PIPELINE_MAX_EVIDENCE_CHARS`), per-key quota; no route returns a note or lists the vault | SR-S5, SR-K2 | T240 | SEC-PIPE-03 |
| TM-35 | Forged loop counters steer the decider | X4 | Counters in `laris.turn` are inputs, clamped to the server's hard caps (`LARIS_SERVER__DECIDER_MAX_STEPS`, `_MAX_SECONDS`, `_MAX_ADVISOR_ASKS`); they never skip a stage or widen the legal set; `run_tool`, `acquire` and `verify` are not decided here; the decision network cannot be enabled by a setting | SR-K5, SR-S4 | T241 | SEC-PIPE-05 |
| TM-34 | Unbounded buffering or retries exhaust memory or the model | X4 | `max_draft_chars` (an error, never a truncation), `max_attempts` of the harness policy, the model concurrency limit, the stage timeout | SR-S4, SR-S6 | T239 | SEC-PIPE-04 |

## 5. Coverage rules and current state

- Every row has one control entry, an owning task and one test id; test ids are unique.
- A test id is reserved by this document and created by its owning task. T154 fails if a listed id has no test.
- A feature that adds an asset, attacker or trust boundary changes this document in the same task.
- Present state (T154, 2026-11-19): `cargo xtask security` runs every test id through `tests/security/suite.json`
  (exact test names per id; a renamed or missing test fails the run) and writes `reports/security/report.json`. Of the
  30 ids, 27 pass, `SEC-SUP-01` passes as **partial** (`cargo deny`, the guard and the scan run; release signing waits
  for T159) and none is deferred any more (`SEC-BRAIN-01` since T240, `SEC-DATA-03` since 2026-11-20, which runs the T168 dataset tests).
  Since T243 the compose stack runs the pipeline (ADR-025 D56): the controls of 4.6 are active in the default
  deployment, and `docker/smoke_test.sh` checks the Prefilter, a grounded answer, the free path and the abstention
  through Caddy. Two limits stay: the gate and decider thresholds are untuned starting values, and the main brain
  lives in the server's state volume, so its backup is the volume (not `docker/backup.sh`, which dumps PostgreSQL).
  A deferral to a task that is already done fails the suite. The PostgreSQL tests (`SEC-KEY-01`
  to `SEC-KEY-04`, `SEC-QUOTA-01`, part of `SEC-KEY-02` and `SEC-HTTP-02`) need `LARIS_TEST_PG_DSN`; without it they
  are reported `not_run` and the suite fails, unless `--without-postgres` is given. `SEC-DEP-01` and `SEC-NET-01` are
  checked statically in CI (`crates/laris-server/tests/deployment.rs`); `docker/verify-images.sh` and
  `docker/smoke_test.sh` check the built images and are run by the owner. `SEC-SBX-01` covers the system the suite
  ran on (Linux); the macOS and Windows backends have their own test targets.

## 6. Residual risks (accepted, not mitigated)

- A local administrator, or the user running the client with their own privileges, can read their own data.
- A model can be wrong inside evidence that is real; the gate proves a span exists, not that the claim is true.
- Denial of service by the holder of a valid admin key is an operator problem.
- The leak guard bounds verbatim leakage only; paraphrase of policy to a determined key holder is not prevented.
