# LARIS — Plan: Obsidian brain, scholarly harness and the second programme

Version 0.2.0 · 2026-11-12 (second programme in section 8) · Implements [spec.md](spec.md); task detail in [task.md](task.md).

## 1. Order of work

The owner's order: finish the system harness, then return to the core model. Phases run in order; a
phase starts when the exit criteria of the previous one hold. Inside a phase, tasks run in dependency
order (task.md). Each task ends with: code and tests, documentation, `ruff`, `mypy`, `validate_docs`,
`validate_spec`, `make test-no-training` and the relevant unit suites passing, then a pull request.

Nothing in this plan trains, fits or optimises a model. Push, merge, tag and release need the owner's
explicit authorisation each time.

## 2. Phases

### Phase 0 — Foundations and decisions
Goal: adopt this ledger, fix the format rules and the threat model before code.
Tasks: T01, T02, T03, T04, T40, T41, T47
Exit criteria:
- `scripts/validate_spec.py` runs in CI and `make check-no-training`.
- `docs/specifications/OBSIDIAN_VAULT_FORMAT.md` and the golden fixture vault exist and cite the official rules.
- Threat model lists every threat with a control and a planned test.
- ADR records the Obsidian-compatible brain decision (D1 to D9 confirmed or changed by the owner).
- ADR-015 fixes the local data plane (user disk = database, user machine = sandbox) and the server authenticates keys.
- ADR-016 keeps the system policy on the server; the client is thin (npm package, global and project `.laris/`).

### Phase 1 — Vault core library
Goal: a dependency-free library that reads, indexes, writes and checks Obsidian-format vaults.
Tasks: T05, T06, T07, T08, T09, T10
Exit criteria:
- Parser, index, safe writer, schema registry, graph analytics and lint pass the fixture suite.
- Index is deterministic and incremental; cache is disposable.
- No import of Obsidian or network access in the package.

### Phase 2 — Project vault lifecycle
Goal: every user's project gets and keeps an Obsidian structure as they work.
Tasks: T11, T12, T13, T14, T15, T16, T17
Exit criteria:
- First work in a project creates the vault; later work adds linked notes; user edits survive.
- Memory is unified in the vault; old memory migrates losslessly.
- CLI, chat and web expose the vault; the guide documents it.

### Phase 3 — System brain
Goal: a protected, curated brain that only brain tools can reach.
Tasks: T18, T19, T20, T21, T22, T23
Exit criteria:
- File tools cannot reach the brain; integrity lock covers it; runtime never writes to it.
- Brain content v1 exists for all six directions with playbooks.
- Extraction suite shows no verbatim brain leakage above the limit.

### Phase 4 — Brain-assisted reasoning
Goal: the whole system reasons with the brain.
Tasks: T24, T25, T26
Exit criteria:
- Graph-aware retrieval is implemented and measured against BM25 on the fixture.
- Research turns consult the brain, record a trace and cite sources.
- Consult step is configurable and audited.

### Phase 5 — Scholarly analytics
Goal: the six application directions run on the harness.
Tasks: T27, T28, T29, T30, T31, T32
Exit criteria:
- Literature mining, citation analysis, knowledge graph, research QA, scientific RAG and extraction each have tools, a workflow, vault notes and measured fixtures.
- Exports validate; every statistic names its scope.

### Phase 6 — Hardening and release
Goal: security, evaluation, performance and documentation closed; release 1.4.0.
Tasks: T33, T34, T35, T36, T37
Exit criteria:
- Security and evaluation suites in CI; benchmarks recorded; budgets fixed.
- Guide, architecture documents and runbook updated; release done under the git flow.

### Phase 7 — Return to the core model (owner gate)
Goal: define the model boundary and wait for the owner's decision.
Tasks: T38, T39
Exit criteria:
- Boundary contract and resumption criteria documented.
- Owner decision recorded. Until then no model work starts.

## 3. Critical path

T01 → T02 → T05 → T06 → T07 → T11 → T12 → T13 → T18 → T19 → T24 → T25 → T31 → T34 → T37.
T03 and T04 run beside T02. T08, T09 and T10 follow T06. Phase 5 analytics (T27 to T30, T32) can run in
parallel once Phase 2 has produced Source and Concept notes.

## 4. Risks and responses

| Risk | Response |
|---|---|
| Reimplementing Obsidian rules incorrectly | Fixture vault from the official rules (T02); unknown behaviours verified or avoided; round-trip tests |
| User edits lost or corrupted | Managed blocks, hash conflict detection, backups before rewrite, property tests (T07, T16) |
| Brain leaks through answers | Shingle detection of brain text, excerpt budgets, extraction suite (T20, T33) |
| Poisoned notes steer the model | Notes from documents are untrusted; injection scan on write and read; proposals inbox (T07, T23) |
| Index too slow or too large | Incremental cache, budgets and benchmarks (T06, T35) |
| Scope growth | Each direction ships as tool + workflow + notes + fixtures only; no new model work |
| New dependency pressure | Standard library and existing packages only; owner approval recorded in the task otherwise |
| Local files readable by the local user | Documented as out of scope; optional encryption deferred (D3) |

## 5. Verification policy

- Unit tests per task; fixtures under `tests/fixtures/`; experiments stay outside the automated suite.
- Model-free evaluation reports go to `reports/`, never into specifications.
- CI runs lint, types, docs, ledger validation and tests on Python 3.10 to 3.12.
- A task is `done` only when every deliverable and validation item in its record is met and the
  completion note is written.

## 6. Reporting to the owner

At each phase exit: what was built, what was measured, open decisions, and the next phase. Items that
need the owner: D1 to D9 confirmation (T04), new dependencies, push, merge and release, and the model
gate (T39).

### Phase 8 — Layers and Agentic
Goal: fix the layer vocabulary and make the system Agentic (ADR-017).
Tasks: T42, T43, T44, T45, T46
Exit criteria:
- The layer contract test passes and the scripted Agentic scenario suite passes within all limits.

## 7. Closing status (2026-11-11)

Phases 0 to 6 and Phase 8 are complete: 45 of 47 tasks are `done` (task.md has the completion note and the
measured figures of each). Two tasks wait for the owner and are not engineering work: T38 (the boundary
contract and tests are written; the owner reviews the resumption criteria) and T39 (the decision to resume
the core model, which stays paused). The client wheel is built after this closing, then the release under
the git flow (see docs/development/OWNER_RUNBOOK.md).

## 8. Second programme: three blocks, two databases, Docker, terminal client (2026-11-12)

Owner instruction: restructure the code and the operating flow (spec sections 1, 4b and 5b). Target:

```text
Client (laris, npm)  --P1 HTTPS/SSE-->  Caddy --> Server API (FastAPI) --P2 internal--> Model service (FastAPI, GPU)
 SQLite per space                                  PostgreSQL                             weights mounted read-only
```

Flow of one chat turn after the restructuring: the client composes the user's layers and sends P1 through
Caddy; the API takes the real address from a trusted proxy, authenticates, validates the body and reserves
quota; the gateway composes the prompt and consults the brain (lock on the brain budget only) and calls the
model over P2 with bounded concurrency; the model's GPU queue loads the needed model and streams back; the
gateway guards the text, diverts reasoning and streams SSE (an `error` event on failure mid-stream), then
settles quota and stores the trace in `finally`; the client runs tools locally and sends the next request;
dense search embeds through `POST /v1/laris/embed` and caches vectors in SQLite.

Rules for every task of this programme: one `feature/<id>-<name>` branch from `develop` per task; no
behaviour change in Phase 10; `ruff`, `mypy`, `validate_docs`, `validate_spec` and
`make check-no-training` pass; nothing trains or fits a model; PostgreSQL tests run when
`LARIS_TEST_PG_DSN` is set; the unrelated local change to `data/acquisition_manifest.json` is preserved.
Release 2.0.0 (protocol and server storage change) needs the owner's authorisation.

### Phase 9 — Decisions of the second programme
Goal: record the decisions and dependency approvals before code.
Tasks: T48
Exit criteria:
- [x] ADR-019 accepted; ADR-015, ADR-016 and ADR-018 amended; D10 to D23 recorded (T48, 2026-11-12).
- [x] Approved dependencies listed in `pyproject.toml` extras `server` and `model`; `ink` 8.0.0, `react` 19.3.1 and `uv` 0.13.1 pinned in ADR-019; `prompt_toolkit` and `rich` recorded as dropped.

### Phase 10 — Three blocks
Goal: move the code into `src/laris/{protocol,shared,client,server,model,research}` without changing behaviour.
Tasks: T49, T50, T51, T52
Progress: [x] T49, [x] T50, [x] T51, [x] T52 (2026-11-12). Phase complete except the npm smoke test in CI.
Exit criteria:
- No import cycle between blocks; the block-boundary test passes.
- Three entry points (`laris`, `laris-server`, `laris-model`); the client wheel is built from its blocks only.
- The no-training suite passes with the same results as before the move.

### Phase 11 — Model service
Goal: a separate inference process that alone loads weights and manages VRAM.
Tasks: T53, T54, T55
Progress: [x] T53, [x] T54, [x] T55 (2026-11-12). Phase complete.
Exit criteria:
- `laris-model serve` speaks P2; the boundary tests pass over HTTP; the GPU queue respects the VRAM budget.
- The server reaches the model only through P2.

### Phase 12 — Server API
Goal: replace `http.server` with FastAPI and close the reliability and safety findings.
Tasks: T56, T57, T58, T59
Progress: [x] T56, [x] T57, [x] T58, [x] T59 (2026-11-12). Phase complete.
Exit criteria:
- Body validation, SSE error events, bounded model concurrency and the narrowed brain lock are tested.
- Address rules hold behind a trusted proxy; `/v1/laris/embed` serves the client; the default key is never printed.

### Phase 13 — Server storage on PostgreSQL
Goal: keys, usage and traces in PostgreSQL with atomic quota and running retention.
Tasks: T60, T61, T62, T63
Progress: [x] T60, [x] T61, [x] T62, [x] T63 (2026-11-12). Phase complete.
Exit criteria:
- Migrations apply on an empty database; the concurrency test never passes a limit.
- Partitions and background retention work; the SQLite import is lossless on a fixture.

### Phase 14 — Client storage on SQLite
Goal: the user's data in one SQLite file per private space, vault notes unchanged.
Tasks: T64, T65, T66
Progress: [x] T64, [x] T65, [x] T66 (2026-11-12). Phase complete.
Exit criteria:
- Automatic, idempotent migration with backups; BM25 rankings identical; no lost update under two writers.

### Phase 15 — Deployment with Docker
Goal: the whole server side runs with `docker compose` on one machine.
Tasks: T67, T68, T69
Progress: [x] T67, [x] T68 (2026-11-12). Remaining: T69.
Exit criteria:
- Images build; only Caddy publishes ports; policy and weights are read-only mounts; secrets are Docker secrets.
- The end-to-end smoke test passes (or its commands are prepared for the owner when no Docker or GPU is available).

### Phase 16 — Terminal client like Claude Code
Goal: `laris` offers the interface and flow of Claude Code: one engine, the Ink + React front end,
a dependency-free plain mode, global settings and an automatic sandbox.
Tasks: T70, T71, T72, T73, T74, T75, T76, T77, T78, T79, T80, T81, T82
Exit criteria:
- E1 contract tests pass; the Ink front end passes the scenario set; plain mode and headless `stream-json` (equal to E1) pass where they apply.
- Global home with Claude-Code-style settings, login without flags, sandbox built and repaired without user action.
- Permission modes and rules, coding tools, input forms, hooks, status line and interrupt pass the client
  acceptance suite.

### Phase 17 — Hardening and release 2.0.0
Goal: security, documentation and the release of the restructured system.
Tasks: T83, T84, T85
Exit criteria:
- Security tests for the new surfaces pass; architecture documents and the guide describe the new flow.
- Release 2.0.0 under the git flow, only with the owner's authorisation.

### Critical path of the second programme

T48 → T49 → T50 → T51 → T52 → T53 → T54 → T55 → T56 → T57 → T68 → T69 → T83 → T84 → T85.
Phase 13 (T60 to T63) and Phase 14 (T64 to T66) can start after T52; Phase 16 starts after T52 and T48
(pinned front-end dependencies): T70 (engine) first, then T71 to T79 on the engine, then plain mode T80, the Ink front end
T81 and the acceptance suite T82; T79 needs T56.

### Risks of the second programme

| Risk | Response |
|---|---|
| The package move breaks imports or behaviour | Scripted import rewrite, no behaviour change in Phase 10, full no-training suite before and after |
| Mixed versions of client and server | `X-Laris-Protocol` header and a clear refusal; npm client and server released together as 2.0.0 |
| Data loss when migrating storage | Idempotent migrations, backups of the originals, lossless import test, `pg_dump` backups |
| Quota overshoot under load | Atomic reservation and settlement; concurrency test |
| One GPU shared by chat and embeddings | Model block queue with VRAM budget; bounded concurrency from the API |
| Shell tools and hooks run harmful commands | Permission modes and rules, folder trust, confinement, timeouts, security tests (SR-C5) |
| Address rules broken behind the proxy | Trusted-proxy list; tests with trusted and untrusted proxies |
| Logic leaks into the Ink front end | All logic in the engine; the front end speaks only E1; the same scenarios run through Ink, plain mode and headless (T82) |
| Sandbox cannot be built (offline, no Python) | System Python fallback, clear message, the program keeps working; download source is configuration |
| Agent installs break the program | The program is a sealed binary from npm (D19); the agent works only in the sandbox, which is repaired automatically (D23) |
| A cloned repository reconfigures the client | Project `./.laris/` carries no configuration (D20); hooks only from the global settings; folder trust |
