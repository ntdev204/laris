# LARIS — Tasks 2: System, server and client (Rust)

Version 2.0.0-draft · 2026-11-13 · Implements [plan/2-system.md](../plan/2-system.md) for [spec.md](../spec.md).

Status values and rules as in [task/1-model.md](1-model.md). Run `python scripts/validate_spec.py` (from T121:
`cargo xtask spec`) after each task.

## Phase 26 — Rust foundations

### T119 — Owner approval of toolchain, crates and tools
- Requirements: SR-G2
- Depends: T92
- Deliverables:
  - Approved list recorded here and in ADR-021: stable Rust in `rust-toolchain.toml`; candidate crates tokio, axum,
    tower-http, rustls, reqwest (rustls), serde, serde_json, schemars, sqlx (PostgreSQL), rusqlite (bundled), ratatui,
    crossterm, clap, tracing, thiserror, sha2, hmac, uuid, time, regex, globset, ignore, similar, pulldown-cmark, syntect,
    a YAML parser, a PDF text extractor, landlock, seccompiler, windows-sys; `cargo-deny`; a release signing tool; a
    cross-compilation tool; `uv` kept for the Python environment
- Validation:
  - Each item approved, replaced or refused by the owner in writing
- Status: done
- Note: Closed 2026-11-13: the owner approved the whole candidate list above without changes ("Duyệt toàn bộ danh
  sách"). Approved as listed: stable Rust pinned in `rust-toolchain.toml`; every crate named in the deliverables (exact
  versions are pinned and vendored in T121, and `cargo deny` allows only this list); `cargo-deny`; a release signing
  tool and a cross-compilation tool (the concrete tool is named in ADR-021, T120); `uv` for the Python environment.
  Not approved here: any crate or tool not named above. Nothing was installed by this task; `cargo` is not yet present
  on the machine, so the toolchain installation belongs to T121.

### T120 — ADR-021 (Rust generation) and AGENTS.md
- Requirements: SR-G1, SR-G4
- Depends: T119
- Deliverables:
  - `docs/adr/ADR-021-rust-generation.md` with D27-D43, each `proposed` decision confirmed or changed; confirmation of D28
    against the ladder wording of 2026-11-13
  - `AGENTS.md`: ledger paths (`spec.md`, `plan/`, `task/`), `cargo xtask spec`, branches from `laris-v2`, removal of
    generation-1 commands that no longer exist
- Validation:
  - Owner approves the ADR and the `AGENTS.md` change
- Status: done
- Note: Closed 2026-11-13: the owner approved ("Đồng ý") D28 and D35-D42 as proposed and the `AGENTS.md` change; the
  release tools (`cross` for static Linux, native runners elsewhere, `minisign`) were chosen under the owner's
  delegation. `docs/adr/ADR-021-rust-generation.md` is ACCEPTED and indexed; spec D28 and D35-D42 are marked
  confirmed. `AGENTS.md` carries the ledger paths, `cargo xtask spec` (from T121), branches from `laris-v2` and the
  merge authorisation, and no longer lists the `laris harness` commands. Merged into `laris-v2`.

### T121 — Cargo workspace, xtask and CI
- Requirements: SR-G2, SR-G3
- Depends: T120
- Deliverables:
  - Root workspace, empty crates of spec 5.1, `xtask spec` (port of `validate_spec.py`), `deny.toml`, vendoring,
    `THIRD_PARTY.md` skeleton; CI with fmt, clippy, test, deny, spec, model-block checks (T94) and the no-training guard
- Validation:
  - CI green; a seeded unapproved crate and a seeded training call fail; offline build from the vendor folder
- Status: pending

### T122 — Threat model of generation 2
- Requirements: SR-G5
- Depends: T120
- Deliverables:
  - `docs/architecture/THREAT_MODEL.md` (spec section 9) with controls and test ids
- Validation:
  - Every threat maps to a control and a test id
- Status: pending

## Phase 27 — Protocol and shared libraries

### T123 — laris-protocol: P1 and P2
- Requirements: SR-P1, SR-P2
- Depends: T121
- Deliverables:
  - Types for every P1 route and SSE event (with `LarisMeta` evidence list) and P2 chat, embeddings and tool routes;
    version header; JSON Schema export; fixtures recorded from generation 1 and the Python model service
- Validation:
  - Round-trip and schema tests on all fixtures; deterministic export
- Status: pending

### T124 — Core event protocol
- Requirements: SR-P3
- Depends: T123
- Deliverables:
  - Commands and events, JSON-lines encoding, version in `ready`; the eleven Ink scenarios translated
- Validation:
  - Round-trip per message; translated scenarios validate
- Status: pending

### T125 — laris-config and catalogue
- Requirements: SR-L1
- Depends: T121
- Deliverables:
  - Settings precedence, JSON Schema validation, EN and VI catalogue
- Validation:
  - Precedence and path-error tests; scan for hardcoded endpoints and secrets
- Status: pending

### T126 — laris-vault: parser and index
- Requirements: SR-L2
- Depends: T121
- Deliverables:
  - Parser for every link form, properties, tags, headings, blocks; backlinks, orphans; incremental deterministic index
- Validation:
  - Golden fixture equals the generation-1 index; rerun byte-identical
- Status: pending

### T127 — laris-vault: writer, schema and lint
- Requirements: SR-L2
- Depends: T126
- Deliverables:
  - Atomic writer with managed blocks; schema registry; filename rules; hub-tree lint
- Validation:
  - User edits survive 100 rewrites; crash mid-write keeps the old file; lint fails on seeded faults
- Status: pending

## Phase 28 — System: loop

### T128 — laris-model-client
- Requirements: SR-H12
- Depends: T123, T125
- Deliverables:
  - P1 client: SSE, version check, key, pinning, timeouts, bounded retries, interrupt
- Validation:
  - Fixture tests; version and pin mismatch; interrupted stream
- Status: pending

### T129 — laris-store: client SQLite
- Requirements: SR-H9
- Depends: T125
- Deliverables:
  - Per-project, per-key database; migrations continuing generation 1; tables for sessions, events, passages, embeddings,
    learning examples, vault index cache
- Validation:
  - A generation-1 database migrates without loss; two writers lose nothing
- Status: pending

### T130 — Event log and replay
- Requirements: SR-H2
- Depends: T124, T129
- Deliverables:
  - Event types, append-only store, replay with a scripted model, resume
- Validation:
  - Byte-identical replay; resume after a killed process
- Status: pending

### T131 — Core loop and decider seam
- Requirements: SR-H1, SR-H14
- Depends: T128, T130
- Deliverables:
  - State machine (plan, tools, reflection, completion check, budgets, interrupt); `Decider` trait with the
    generation-1 policy as its only implementation
- Validation:
  - Translated Agentic scenarios pass with a scripted model; no model call outside a decided action
- Status: pending

## Phase 29 — System: harness

### T132 — Tool registry and coding tools
- Requirements: SR-H4
- Depends: T131
- Deliverables:
  - Local and remote tool registry; `Read`, `Write`, `Edit`, `Glob`, `Grep`, `Bash`, `save_memory`, skills; structured
    errors; limits; untrusted marking; checkpoints and rewind
- Validation:
  - Tests per tool; `Edit` uniqueness; rewind; local and remote tools identical to the loop
- Status: pending

### T133 — Permissions, hooks and folder trust
- Requirements: SR-H5
- Depends: T132
- Deliverables:
  - Modes, rules, saved approvals, hooks with JSON stdin and timeouts, folder trust
- Validation:
  - Mode and precedence tests; denied path never written; hook cases; planted project settings ignored
- Status: pending

### T134 — Sandbox measurement: cut the codex sandbox
- Requirements: SR-H6
- Depends: T121
- Deliverables:
  - Report: codex crates per platform after replacing `codex-protocol` types, line counts, Windows first;
    `THIRD_PARTY.md` entries (origin `aa5f492`, licence, files to modify)
- Validation:
  - Owner reviews and approves the cut
- Status: pending

### T135 — Sandbox integration and Python environment
- Requirements: SR-H6
- Depends: T133, T134
- Deliverables:
  - `laris-sandbox` for Linux, macOS, Windows; automatic `~/.laris/.venv` with `uv`
- Validation:
  - Per platform: writes outside allowed roots fail; build on first use, repair, single build under two sessions
- Status: pending

### T136 — Redaction and injection defence
- Requirements: SR-H10
- Depends: T132
- Deliverables:
  - Redaction before P1; untrusted data handling; policy refusal of injected command requests
- Validation:
  - Security tests: secrets in output, injected document, hostile hook output
- Status: pending

### T137 — Evidence gate
- Requirements: SR-H7
- Depends: T131
- Deliverables:
  - Citation parser and checker for workspace evidence and `LarisMeta` brain evidence; absence-of-evidence rule;
    unsupported-statement marking
- Validation:
  - Fabricated citation, missing span and unsupported claim caught; valid answers unchanged
- Status: pending

### T138 — Learning data from the event log
- Requirements: SR-H11
- Depends: T130
- Deliverables:
  - Example derivation; `laris learn export` JSONL
- Validation:
  - Export matches the fixture; no collected data in P1 requests or the repository
- Status: pending

## Phase 30 — System: prompt

### T139 — Prompt layer and autocompact
- Requirements: SR-H3
- Depends: T131, T132
- Deliverables:
  - Request assembly from `LARIS.md` layers, memory, plan, pinned items; budgets; autocompact; layer contract test
- Validation:
  - Budget tests; pinned items survive compaction; loop → harness → prompt contract holds
- Status: pending

### T140 — Model-free evaluation runner
- Requirements: SR-H15
- Depends: T135, T136, T137, T138, T139
- Deliverables:
  - One command replaying golden and Agentic scenarios, evidence checks, leak and injection tests and vault round trips;
    report outside the specifications
- Validation:
  - Reproducible run; seeded regression fails
- Status: pending

## Phase 31 — Server: LLM

### T141 — laris-server: hardened API
- Requirements: SR-S1
- Depends: T123, T125
- Deliverables:
  - axum app, configuration, health, body validation, trusted proxies, content-free logs, mid-stream error events
- Validation:
  - Tests for 400, 411, 413, mid-stream error, slow client, proxy rules
- Status: pending

### T142 — PostgreSQL storage
- Requirements: SR-S3
- Depends: T141
- Deliverables:
  - Migrations continuing generation 1, pool, partitions, retention, daily summary
- Validation:
  - Tests under `LARIS_TEST_PG_DSN`; generation-1 dump migrates without loss
- Status: pending

### T143 — Keys, roles, quotas, admin
- Requirements: SR-S2
- Depends: T142
- Deliverables:
  - Digest-only keys, roles, quota reservation and settlement, expiry, revocation, admin and account routes
- Validation:
  - 401, 403, 429; parallel quota test; no key printed
- Status: pending

### T144 — Model proxy and the LLM rung
- Requirements: SR-S6, SR-M1, SR-S9
- Depends: T143
- Deliverables:
  - P2 client with bounded concurrency and stream passthrough; `/chat` and `/embed` end to end; LLM-rung scenario
- Validation:
  - Contract tests against the Python model service (placeholder); first-chunk latency measured; scenario passes
- Status: pending

## Phase 32 — Server: RAG

### T145 — laris-retrieval
- Requirements: SR-L3
- Depends: T126
- Deliverables:
  - BM25, graph expansion, fusion, span provenance, dense channel interface (not qualified); benchmark report
- Validation:
  - Rankings equal generation 1 on the fixture; metrics computed; P95 measured
- Status: pending

### T146 — Policy gateway, integrity lock, leak guard
- Requirements: SR-S4
- Depends: T144
- Deliverables:
  - Composition from `.laris/`, integrity lock compatible with `integrity.lock`, leak guard, private reasoning,
    `/workflows` and `/help`
- Validation:
  - Confidentiality suite; changed policy stops the server; no reasoning in chat bodies
- Status: pending

### T147 — System brain service
- Requirements: SR-S5
- Depends: T127, T145, T146
- Deliverables:
  - Progressive-disclosure operations over `.laris/brain/`, budgets, brain brief, evidence list in `LarisMeta`, brain tools
- Validation:
  - Each direction reaches its playbook within `brain.max_depth`; no write path
- Status: pending

### T148 — Ingestion, project vault and the RAG rung
- Requirements: SR-H8, SR-H13, SR-S9
- Depends: T127, T132, T137, T145, T147
- Deliverables:
  - Ingestion (text, Markdown, PDF text layer), Source notes, vault lifecycle, memory, proposals inbox; RAG-rung scenario
    through server and system with the evidence gate
- Validation:
  - Generation-1 vault adopted unchanged; passages equal generation 1; scenario passes
- Status: pending

## Phase 33 — Server: Agent

### T149 — Scientific tools as remote tools
- Requirements: SR-M2, SR-S6
- Depends: T144
- Deliverables:
  - Inventory of generation-1 call sites; tool routes in the Python model service; server `/tools/{name}`; schemas
- Validation:
  - Fixture tests reproduce generation-1 extraction results through the server
- Status: pending

### T150 — Traces and audit
- Requirements: SR-S7
- Depends: T142
- Deliverables:
  - Content-free trace per request; operator query; retention
- Validation:
  - Trace on success, error, disconnect; no message text in rows
- Status: pending

### T151 — The Agent rung
- Requirements: SR-S9, SR-H4
- Depends: T133, T148, T149, T150
- Deliverables:
  - Agent-rung scenarios mixing local tools (files, shell in sandbox) and remote tools (brain, scientific) end to end
- Validation:
  - Scenarios pass; traces show tool names only
- Status: pending

## Phase 34 — Server: Agentic

### T152 — The Agentic rung
- Requirements: SR-S9, SR-H15
- Depends: T140, T151
- Deliverables:
  - Agentic suite through the stack: visible plan, resumable progress, bounded replanning, completion check, memory in
    the vault, bounded autonomy; report naming the backend
- Validation:
  - Suite passes; the report states that mechanics, not model capability, were shown
- Status: pending

### T153 — Docker deployment
- Requirements: SR-S8
- Depends: T147, T150
- Deliverables:
  - Static non-root API image, model image, Caddyfile, `compose.yaml`, secrets, backup script, runbook
- Validation:
  - `docker compose config`; smoke test; no policy or weights in images; trial-server volumes (`caddy_data`, PostgreSQL)
    survive the upgrade (owner runs it)
- Status: pending

### T154 — Security suite and performance budgets
- Requirements: SR-G5, SR-H15
- Depends: T122, T152, T153
- Deliverables:
  - Security suite for every threat row in CI; budgets fixed from measurements
- Validation:
  - Suite and budgets pass
- Status: pending

## Phase 35 — Client (after the model is finished)

### T155 — Global home, settings and login
- Requirements: SR-C3, SR-C4
- Depends: T118, T128, T129
- Deliverables:
  - `~/.laris` layout, settings schema, project-folder rules, packaged default server, login inside the interface
- Validation:
  - Fresh home; generation-1 home unchanged; wrong key shows the form again; overrides work
- Status: pending

### T156 — Headless mode
- Requirements: SR-C5
- Depends: T155
- Deliverables:
  - `laris -p` with stdin, output formats, resume, continue, flags, exit codes
- Validation:
  - Tests with a scripted model per format and exit code
- Status: pending

### T157 — Terminal interface on a recorded core
- Requirements: SR-C1
- Depends: T124, T155
- Deliverables:
  - Banner, input box, streaming Markdown, status line, footer, driven by a recorded core
- Validation:
  - Render tests at 60 and 100 columns; chat and interrupt scenarios pass
- Status: pending

### T158 — Interface on the real core and commands
- Requirements: SR-C1, SR-C2
- Depends: T152, T157
- Deliverables:
  - Tool and diff blocks, approvals, login form, queued input, history search; slash and custom commands, `@path`,
    `!command`, `# note`; guide entries
- Validation:
  - All translated golden scenarios pass; owner screenshot review on Linux and Windows
- Status: pending

### T159 — Distribution
- Requirements: SR-C6
- Depends: T156
- Deliverables:
  - Release builds per platform, `install.sh`, `install.ps1`, checksums and signatures, npm wrapper, size report
- Validation:
  - One-command install on a clean machine per platform; tampered binary refused
- Status: pending

## Phase 36 — Parity and release 3.0.0

### T160 — Parity with generation 1
- Requirements: SR-H15, SR-G4
- Depends: T154, T158, T159
- Deliverables:
  - Parity checklist (behaviours, commands, data) against `laris-v1`; generation-1 home, project databases, vaults and
    server database tested unchanged
- Validation:
  - Checklist complete; no open regression
- Status: pending

### T161 — Documentation and release 3.0.0
- Requirements: SR-G4
- Depends: T160
- Deliverables:
  - Guide, architecture documents, runbook, changelog; PR `laris-v2` into `main`; tag and release with authorisation
- Validation:
  - Release checklist recorded; `laris-v1` untouched
- Status: pending
