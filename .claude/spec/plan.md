# LARIS — Plan: Obsidian brain and scholarly harness

Version 0.1.0 · 2026-11-11 · Implements [spec.md](spec.md); task detail in [task.md](task.md).

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
