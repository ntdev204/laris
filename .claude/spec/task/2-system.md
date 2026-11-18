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
- Status: done
- Note: Closed 2026-11-13. Toolchain installed with the owner's permission: rustup, Rust 1.100.0 pinned in
  `rust-toolchain.toml`, `cargo-deny` 0.20.2. Root workspace with the 14 empty crates of spec 5.1 and `xtask`;
  `cargo xtask spec` is a port of `validate_spec.py` (same result on the real ledger: 81 tasks, 9 done, now 10 with
  this one); `cargo xtask guard` is the no-training guard over `crates/`, `xtask/` and `.github/`; `deny.toml` allows
  only the T119 crates plus the workspace and the transitive crates of `regex`; vendoring in `vendor/` with source
  replacement in `.cargo/config.toml` (offline); `THIRD_PARTY.md` skeleton; `.github/workflows/ci.yml` (rust and
  model-block jobs). Verified locally: fmt, clippy `-D warnings`, test (7 xtask tests), `cargo deny check`, offline
  frozen build; a seeded `itoa` dependency failed `cargo deny` and a seeded `run_training` call failed the guard
  (also with the authorization variable set, exit 2). NOT verified here: the workflow itself has not run on GitHub
  (push stays with the owner), and the model-block job (`verify_model_block.py` with the `model` extra) was not run
  locally. "CI green" therefore remains to be confirmed on the first push. Foundation model unchanged: NOT QUALIFIED.


### T122 — Threat model of generation 2
- Requirements: SR-G5
- Depends: T120
- Deliverables:
  - `docs/architecture/THREAT_MODEL.md` (spec section 9) with controls and test ids
- Validation:
  - Every threat maps to a control and a test id
- Status: done
- Note: Closed 2026-11-18. `docs/architecture/THREAT_MODEL.md` (DRAFT 0.1.0) lists 9 assets, 8 attackers, the trust
  boundaries and 30 threats (TM-01 to TM-30); each row has a control, requirement, owning task and a unique test id
  `SEC-<area>-<nn>`. Checked by script: every requirement and task id cited exists, ids and test ids are unique.
  `validate_docs.py` and `cargo xtask spec` pass. The controls and tests are PLANNED: the owning tasks (T127-T149,
  T153, T159, T164, T168) create them and T154 collects them; only `SEC-SUP-01` is partly exercised today (`cargo deny`
  and the guard, T121). Residual risks are listed in the document. No code changed; model unchanged, NOT QUALIFIED.

## Phase 27 — Protocol and shared libraries

### T123 — laris-protocol: P1 and P2
- Requirements: SR-P1, SR-P2
- Depends: T121
- Deliverables:
  - Types for every P1 route and SSE event (with `LarisMeta` evidence list) and P2 chat, embeddings and tool routes;
    version header; JSON Schema export; fixtures recorded from generation 1 and the Python model service
- Validation:
  - Round-trip and schema tests on all fixtures; deterministic export
- Status: done
- Note: Closed 2026-11-18. `laris-protocol` has the P1 types (chat request with the `laris` block, SSE chunk with the
  brain evidence list `LarisMeta` and usage, embed, models, workflows, help, account, admin usage and reasoning, error
  bodies), the P2 types (chat completion and chunk with `reasoning_content`, embeddings), the SSE decoder and encoder
  (`error` event then `[DONE]`), the `X-Laris-Protocol` check with the generation-1 message, and the JSON Schema export
  (`cargo xtask schema [--check]`; committed in `crates/laris-protocol/schema/`). Names: the request block is
  `LarisRequest` and the response evidence block is `LarisMeta` (generation 1 used `LarisMeta` for the request).
  Fixtures: 16 P1 and 16 P2 files recorded by `scripts/record_protocol_fixtures.py` from the real generation-1 server
  (branch `laris-v1`, scripted model; includes the brain evidence list, a tool call, reasoning chunks, an error before and
  after the stream started, 400/401/426); `tests/fixtures/authored/` holds hand-written ones (admin routes, metered
  account, the `/tools/{name}` route, an SSE stream with a comment line and unknown fields) and says so. The tool route
  is new in generation 2: its request and response shapes are this task's design, with no generation-1 recording.
  Verified: round trip (no loss, stable) and schema validation (own small validator in the tests, since no validator
  crate is approved) on every fixture; the decoder gives the same events however the bytes are cut; seeded faults fail
  both the type and the schema; export deterministic and equal to the committed file; `cargo fmt --check`, `clippy -D
  warnings`, `cargo test`, `cargo deny check`, `xtask guard` and `xtask spec` pass. Crates added within the T119 list:
  serde, serde_json, schemars and their transitive crates (vendored; `deny.toml` and `THIRD_PARTY.md` updated). The P2
  fixtures are from the Python service code with a scripted model, not from a trained model; the model is NOT QUALIFIED.

### T124 — Core event protocol
- Requirements: SR-P3
- Depends: T123
- Deliverables:
  - Commands and events, JSON-lines encoding, version in `ready`; the eleven Ink scenarios translated
- Validation:
  - Round-trip per message; translated scenarios validate
- Status: done
- Note: Closed 2026-11-18. `laris-protocol` has `events` (14 events and 8 commands of the E1 set as tagged enums,
  unknown fields refused, version in `ready`, `check_ready` with the generation-1 message, `ends_command`, an
  in-process `channel()`), `jsonl` (one object per line, `LineBuffer` that gives the same lines however bytes are cut,
  unknown type is an error) and `scenario` (typed scenario with id pairing checks, and a replay through the JSON-lines
  encoding). The schema export gained group `core` (`Event`, `Command`; committed file regenerated). Tests
  (`tests/core.rs`): round trip and schema validation of every message in `tests/fixtures/core/*.jsonl` (authored, one
  per type plus minimal forms) and of every message in the eleven scenarios of `tests/golden/ink_scenarios/`;
  seeded faults fail both type and schema; the `mismatch` scenario is detected. Worked on v2 only; generation 1 was
  not read for this task beyond the E1 field list already known. The test validator learned `minimum`.
  `cargo fmt --check`, `clippy -D warnings`, `cargo test`, `cargo deny check`, `xtask guard` pass. No new crates.

### T125 — laris-config and catalogue
- Requirements: SR-L1
- Depends: T121
- Deliverables:
  - Settings precedence, JSON Schema validation, EN and VI catalogue
- Validation:
  - Precedence and path-error tests; scan for hardcoded endpoints and secrets
- Status: done
- Note: Closed 2026-11-18. `laris-config` has `settings` (the generation-1 settings document as typed Rust, camelCase,
  unknown keys refused; one source of the JSON Schema, committed in `crates/laris-config/schema/settings.schema.json`,
  checked by `cargo xtask schema --check`), `validate` (own JSON Schema validator, since no validator crate is
  approved; errors name the JSON path, e.g. `hooks.PreToolUse[0].hooks[0].timeout`), `layers` (precedence `LARIS_*`
  environment over settings file over packaged defaults over defaults; env names `LARIS_<SECTION>__<KEY>` matched to
  keys ignoring case and underscores; values read as the type of their setting; an error in the merged value names the
  variable that set it), `packaged` (build-time defaults file beside the binary or named by `LARIS_PACKAGED_DEFAULTS`,
  or compiled in from `LARIS_BUILD_DEFAULTS`; only a well-formed address, fingerprint kept apart), `files` (strict read,
  generation-1 flat files converted in memory without the API key, literal secrets refused, atomic validated write,
  dotted-path get/set) and `catalogue` (English and Vietnamese JSON, `group.name` keys, `{placeholder}` templates,
  fallback to English; tests require the same keys and placeholders in both and a message for every error kind).
  `cargo xtask scan` (new; in CI) finds hardcoded endpoints and secrets in `crates/*/src`, `crates/*/catalogue` and
  `xtask/src`; seeded faults are tested. A test compares the schema with generation 1's `settings.schema.json`: every
  generation-1 setting keeps type, default and limits; the only addition is `ui.language` (`en` or `vi`, default `en`).
  Owner decisions of 2026-11-18, all confirmed: the default language is English everywhere and Vietnamese appears only
  when the user sets `ui.language` to `vi`; the catalogue starts with the config messages only, later tasks add keys in
  both languages (parity is tested); the YAML policy file `.laris/prompts/strings.yaml` is untouched and not read (no
  YAML crate approved). The library reads neither the environment nor the home
  directory; callers pass them. `cargo fmt --check`, `clippy -D warnings`, `cargo test`, `cargo deny check`,
  `xtask guard`, `xtask scan` and `xtask spec` pass. No new crates.

### T126 — laris-vault: parser and index
- Requirements: SR-L2
- Depends: T121
- Deliverables:
  - Parser for every link form, properties, tags, headings, blocks; backlinks, orphans; incremental deterministic index
- Validation:
  - Golden fixture equals the generation-1 index; rerun byte-identical
- Status: done
- Note: Closed 2026-11-18. `laris-vault` has `yaml` (own reader for the properties subset, since no YAML crate is
  approved: block and flow collections, quoted and plain scalars over several lines, `|` and `>` blocks, comments,
  YAML 1.1 scalar resolution as PyYAML does it, tabs refused as PyYAML does; tags, explicit keys and an explicit
  block-indent digit are errors; `.inf`, `.nan` and integers beyond 64 bits stay text), `note` (`parse_note`: every
  link form, property links, tags, headings, block ids, SHA-256, the five fixed error texts, JSON form with
  `__date__`/`__datetime__`) and `index` (`VaultIndex::build` over a folder with the same ignored folders, symlink
  rule and lossy UTF-8 with universal newlines as generation 1; shortest-path resolution, ambiguity and unresolved
  lists, backlinks, orphans; reuse of unchanged notes by size and mtime from a previous index or the `dumps` cache;
  `export_string` is deterministic, sorted, byte-stable). Golden files in `tests/golden/vault/`: `fixture/` is the
  generation-1 fixture plus 16 authored notes and two in ignored folders (property zoo, bad YAML, anchors, depth, CRLF, Unicode names, hidden and
  ignored folders, every link and tag form); `index.json` and `yaml_cases.json` are written by `generate.py` from the
  generation-1 code, and the Rust output equals `index.json` byte for byte. Checked beyond the committed tests (not
  committed): identical to generation 1 on `.laris/brain` (65 notes), `docs` (33), `.claude/spec` and the retrieval
  fixture; 18 000 random YAML documents and 120 random vaults gave no difference. Known differences from generation 1:
  keys that Python treats as equal (`yes` and `true`, `1` and `true`) stay two keys; a whitespace-only line holding a
  tab is accepted; the format spec lists four ignored folders, the code (and so this crate) ignores six (`.laris`,
  `_templates` too) - spec text left for the owner. New crates: `sha2` with its nine transitive crates, vendored and
  added to `deny.toml` (approved in T119); `regex`, `serde_json` already present. `cargo fmt --check`,
  `clippy -D warnings`, `cargo test`, `cargo deny check`, `xtask guard`, `xtask scan`, `xtask schema --check` and
  `xtask spec` pass.

### T127 — laris-vault: writer, schema and lint
- Requirements: SR-L2
- Depends: T126
- Deliverables:
  - Atomic writer with managed blocks; schema registry; filename rules; hub-tree lint
- Validation:
  - User edits survive 100 rewrites; crash mid-write keeps the old file; lint fails on seeded faults
- Status: done
- Note: Closed 2026-11-18. `laris-vault` gains `emit` (properties written as YAML in PyYAML's style: plain text stays
  plain, text that would read back as another type, or holds indicators, edge spaces, tabs or line breaks, is quoted;
  flat shape only), `writer` (`safe_title`, `resolve_inside` against `..`, absolute paths and symlink escapes,
  `atomic_write` = temporary file in the same folder, flush, rename, directory flush, with stage hooks for tests and
  `sweep_stale_temp` for the file a killed write leaves; managed blocks `upsert_block` with SHA-256 prefix, conflict
  detection, `conflicts` and `accept_edits`; `VaultWriter` with size limit, injection scan, redactor, backups under
  `.laris/backups`, per-minute rate limit on an injectable clock; a refused call consumes no quota and writes
  nothing), `schema` (registry read from `.laris/vault/schema.yaml` or the built-in copy; a test keeps them equal) and
  `lint` (`lint_format`, `lint_hierarchy` with `HierarchyRules`, `lint_content`; same problems in the same order as
  generation 1). Limits are arguments; nothing is hardcoded. Golden: `tests/golden/vault/writer_lint.json` and
  `brain/` (a ten-note hub tree with seeded faults) are written by `generate.py` from the generation-1 code, and the
  Rust output equals them: 14 rendered property sets, block upserts, titles, format, schema, content and hierarchy
  lint. Validation tests: user edits (appended, prepended, changed) survive 100 rewrites with order kept and 100
  backups; an edit inside a block is a conflict that leaves the whole note untouched; a failed replacement at each
  stage and a real killed process (child aborted after the temporary file is written, and after it is flushed) both
  keep the old file byte for byte; lint reports every one of ten seeded faults plus three two-note faults. Checked
  beyond the committed tests (not committed): 39 806 random property sets: 35 749 equal to PyYAML text for text, and
  the other 4 057 all hold U+0085, U+2028, U+2029 or U+00A0, the cases listed below. Known differences from generation 1: a block name must match `[\w.-]+`, a
  block text may not hold a LARIS marker and a property set may not be nested or repeat a name (all refusals, where
  generation 1 wrote a note it could not update again); a stored hash of 8 to 63 digits is taken as a prefix (the
  format spec) where generation 1 reported a conflict; text with U+0085, U+2028 or U+2029, or Unicode white space at an
  edge, is quoted differently (PyYAML's own output reads back wrong there); long text is not folded at column 1000;
  files that are not UTF-8 are refused, not rewritten. The brain limits of `lint_hierarchy` come from the caller; the
  settings schema has none yet (T145). No new crates. `cargo fmt --check`, `clippy -D warnings`, `cargo test`,
  `cargo deny check`, `xtask guard`, `xtask scan`, `xtask schema --check` and `xtask spec` pass.

## Phase 28 — System: loop

### T128 — laris-model-client
- Requirements: SR-H12
- Depends: T123, T125
- Deliverables:
  - P1 client: SSE, version check, key, pinning, timeouts, bounded retries, interrupt
- Validation:
  - Fixture tests; version and pin mismatch; interrupted stream
- Status: done
- Note: Closed 2026-11-18. `laris-model-client` holds the P1 client: `ModelClient<T: Transport>` (`chat`, `get_json`,
  `post_json`), `ChatStream` (pull-based: bytes are read only when `next` asks, so a slow consumer slows the server; an
  event or body above `max_body_bytes` is cut off), `Interrupt` (one handle ends a connect, a backoff wait or a stream at
  once; `biased` selects so an interrupt already set wins over ready data), `ApiKey` (bearer token, `Debug` prints
  `ApiKey(***)`, `LARIS_API_KEY`), `Pin` and `Trust`, and `ReqwestTransport` (reqwest 0.12.28 on rustls 0.23.46 with
  the ring provider; redirects are never followed, so the key cannot leave the configured server). Behaviour: every
  request carries `X-Laris-Protocol: 1`; a 426 or an answer with another version is a `Version` error; 401 and 403 are
  `Unauthorized`; 429, 502, 503, 504, a connection failure and a missing answer within `request_timeout` are retried up
  to `max_retries` with doubling backoff capped at `backoff_max` (a `Retry-After` is honoured up to the cap) and only
  before the stream has started; silence for `idle_timeout` inside a body, a body that ends before `[DONE]` and a
  malformed event are errors after which the stream is finished and nothing is resent; an error event then `[DONE]` is
  delivered as events. Pin: `server.caFingerprint` is the SHA-256 of the private authority certificate; the caller
  supplies that certificate (DER), `Trust::pinned` refuses it with `PinMismatch` unless its fingerprint equals the pin,
  and the connection then trusts that authority and nothing else (no system store). Without a pin the system store is
  used. Tests (35): 26 on a scripted transport over the generation-1 P1 fixtures of `laris-protocol` (all seven chat
  streams equal the reference decode at chunk sizes 1, 7, 64 and whole; midstream error; request headers and forced
  `stream: true`; 426, header mismatch, 401, 400 not retried; retry timing under paused time, bound, cap and
  `Retry-After`; answer timeout; idle timeout; truncation; interrupt while waiting, while connecting, while backing off,
  before any request and with events already queued; backpressure by counting pulled chunks; size limit; JSON routes
  decode their fixtures), 5 on pinning including a real TLS handshake against a local rustls server (pinned authority
  accepted; another authority and the system store refused with a certificate error and no request reaching the server),
  and 4 over a plain socket through `ReqwestTransport` (chunked SSE cut mid-event, headers and body on the wire, 426,
  redirect refused, connection refused). Test certificates and the key of the local test server are in
  `crates/laris-model-client/tests/fixtures/tls/` (made with openssl, protect nothing). Dependencies, with the owner's
  approval of the HTTP stack (2026-11-18: vendor reqwest, tokio and rustls): `reqwest` (features `rustls-tls-native-roots`,
  `stream`, `json`), `rustls` (ring, std, tls12), `tokio`, `serde`, `serde_json`, `sha2`, `thiserror`, `laris-protocol`;
  `cargo vendor` added 138 crates (the transitive trees of reqwest, tokio and rustls, wasm and Windows targets
  included, since `cargo deny` checks every target) and `deny.toml` lists each of them; `cpufeatures` 0.3.1 sits beside
  the old 0.2.17. Decisions taken on the open points (owner delegated them, 2026-11-18): the vendor size (about 190 MB, 138
  crates) is accepted as the cost of the approved HTTP stack; `deny.toml` allows the licences ISC and BSD-3-Clause, which
  come with ring, rustls-webpki, untrusted and subtle and cannot be avoided with rustls (comment in the file); the client
  is wired to the settings: `server` gains `caCertificateFile` (PEM or DER, empty for none), `idleTimeoutSeconds` (60),
  `maxRetries` (3), `retryBackoffSeconds` (1), `retryBackoffMaxSeconds` (30) and `maxResponseBytes` (16 MiB), next to
  `timeoutSeconds` (the wait for answer headers), with the schema regenerated and the T125 added-settings test updated;
  `ClientConfig::from_server` and `Trust::from_server` build the client from the block (a pin without a certificate file,
  an unreadable or non-matching file, a non-finite number and a first wait above the longest wait are configuration
  errors; 8 tests in `tests/settings.rs`, PEM and DER both load). The API key still comes from the credentials file or
  `LARIS_API_KEY`, never from the settings. Not covered: a
  test of a pinned server whose certificate chain is presented without the authority (the pin names the authority, which
  the caller supplies). `cargo fmt --check`, `clippy -D warnings`, `cargo test`, `cargo deny check`, `xtask guard`,
  `xtask scan`, `xtask schema --check` and `xtask spec` pass.

### T129 — laris-store: client SQLite
- Requirements: SR-H9
- Depends: T125
- Deliverables:
  - Per-project, per-key database; migrations continuing generation 1; tables for sessions, events, passages, embeddings,
    learning examples, vault index cache
- Validation:
  - A generation-1 database migrates without loss; two writers lose nothing
- Status: done
- Note: Closed 2026-11-18. `laris-store` holds `Store` (one SQLite file; `open`, `open_space`, `connect`, `transaction`,
  `version`, `migrate`, `get_meta`/`set_meta`, `create_session`, `append_event`, `events`), `slug_of`, `fingerprint_of`
  and `space_path` (`<home>/projects/<slug>/<key-fp>.sqlite`, the generation-1 layout and the same slug: folder name
  plus the first 8 hex digits of the SHA-256 of the resolved path, checked against the generation-1 function). WAL,
  `synchronous=NORMAL`, a busy timeout (default 5000 ms), one short-lived connection per operation, every write in
  `BEGIN IMMEDIATE`. Migrations 1 and 2 are the generation-1 ones verbatim (`chunks` = passages with spans,
  `embeddings`, `conversations`, `learning` with its unique index, `vault_index`, `meta`, `schema_version`), so a
  generation-1 file already records them and only 3 runs; migration 3 adds `sessions` and `events` (primary key
  `(session_id, seq)`, `WITHOUT ROWID`, triggers that abort UPDATE and DELETE: append-only). A file whose
  `schema_version` is newer than the build is refused (`TooNew`). `append_event` reads the next position and writes in one
  immediate transaction, so positions are gapless and distinct across writers; the payload is stored as the caller's
  string, byte for byte (T130 serialises). Tests (7): a real generation-1 database made by the generation-1 `Store`
  (fixture `tests/fixtures/generation1.sqlite`, rows in every table, a float32 vector, Vietnamese text) migrates with
  every row and value intact, the unique index still bites, a second open applies nothing; empty file gets all
  migrations and a newer one is refused; two `Store` values on one file written from two threads (150 events and 150
  learning rows each) lose nothing, with gapless sequence and each writer's order kept; events cannot be updated or
  deleted, an unknown session is refused, creating a session twice changes nothing; a failed transaction leaves nothing;
  paths and slugs. Dependencies (owner approved `rusqlite` in T119): `rusqlite` 0.41.1 with `bundled` (SQLite 3.54.1),
  `sha2`, `thiserror`; `cargo vendor` added 11 crates (`libsqlite3-sys`, `hashlink`, `hashbrown`, `foldhash`,
  `fallible-iterator`, `fallible-streaming-iterator`, `pkg-config`, `vcpkg`, `rsqlite-vfs`, `sqlite-wasm-rs`), listed in
  `deny.toml`. rusqlite 0.37 was tried first and dropped: `cargo deny` reports RUSTSEC-2026-0459 for the SQLite it
  bundles (before 3.54.0), fixed in 0.41. `deny.toml` also allows the licence Zlib, which comes with `foldhash`
  (owner to confirm). Not covered: opening a generation-1 file while a generation-1 process writes it (same SQLite
  locking, not exercised); passages, embeddings, learning and vault-cache access have no typed API yet (the tables exist;
  T131-T138 and T126 callers add what they need). `cargo fmt --check`, `clippy -D warnings`, `cargo test`,
  `cargo deny check`, `xtask guard`, `xtask scan`, `xtask schema --check` and `xtask spec` pass.

### T130 — Event log and replay
- Requirements: SR-H2
- Depends: T124, T129
- Deliverables:
  - Event types, append-only store, replay with a scripted model, resume
- Validation:
  - Byte-identical replay; resume after a killed process
- Status: done
- Note: Closed 2026-11-18. `laris-core` holds the event log. `Record` (stored as one JSON object, kind column
  `command`, `model_answer`, `tool_outcome`, `event`): three inputs (an interface `Command`; a `ModelAnswer` bound to the
  SHA-256 of the conversation it answered; a `ToolOutcome`, never re-run on replay) and one output (`Emitted` core
  `Event`). `Session::apply` is the pure fold of inputs into state (conversation, `Pending` = idle / model / open tool
  ids, turns, closed) and returns the events; an input that does not fit is refused and the state stays as it was. T130
  covers user message (busy while a turn runs), interrupt, shutdown, model answer (text, tool calls, `done`) and tool
  outcome; plan, tools, reflection, budgets and the decider are T131. `Recorder::open` creates or resumes a session by
  folding its log, and first writes the outputs lost between the last input and a kill; `record` appends the input,
  then its outputs. `replay(events, Some(&mut ScriptedModel))` folds again, asks the scripted model for every recorded
  answer (it refuses a different conversation, an exhausted script or a different answer) and compares each recorded
  output with the regenerated one byte for byte. `Model` is the trait the loop will use; the P1 client is not wired to
  it yet (T131). Tests (6): byte-identical replay of three tool turns with non-ASCII text, twice; divergence refused
  (changed conversation, tampered output at its position, different or exhausted script); refused inputs leave no
  trace, `busy`, interrupt; a log cut between an input and its outputs is repaired and then equals the clean log byte for
  byte; three rounds of a child process driving the session and killed with SIGKILL after 40 steps, each followed by
  gapless-log, replay and resume checks, the child continuing from the resumed state. Not covered: a kill is not
  steered into the gap between an input and its outputs (the deterministic cut test covers that case); no log
  compaction or retention; `Emitted` records are stored with the input, so a log is about twice the inputs. Dependencies:
  none new (`serde`, `serde_json`, `sha2`, `thiserror` and the two path crates). `cargo fmt --check`,
  `clippy -D warnings`, `cargo test`, `cargo deny check`, `xtask guard`, `xtask scan`, `xtask schema --check` pass.

### T131 — Core loop and decider seam
- Requirements: SR-H1, SR-H14
- Depends: T128, T130
- Deliverables:
  - State machine (plan, tools, reflection, completion check, budgets, interrupt); `Decider` trait with the
    generation-1 policy as its only implementation
- Validation:
  - Translated Agentic scenarios pass with a scripted model; no model call outside a decided action
- Status: done
- Note: Closed 2026-11-18. `laris-core` holds the loop. The decider chooses each step from the closed `Action` set
  (`ask_model`, `run_tool`, `reject_tool`, `set_plan`, `auto_plan`, `reflect`, `retry`, `finish`, `stop`); the step is
  written to the log as a new input record `decision` before it is applied, and it carries everything the decider
  looked at (clock, limits, gate, rendered messages), so replay needs no decider. The fold (`Session::apply`) refuses a
  model answer that no `ask_model` cleared and a tool outcome that no `run_tool` cleared: that is the "no model call
  outside a decided action" rule, enforced in the state and not only in the driver. `Driver` runs decider, model
  (`Model`, now taking a `ModelRequest` with the conversation, a per-call plan note and the offered tools) and
  `ToolRunner` (T132 supplies the registry); events are emitted when a call is decided (`tool_call`) and answered
  (`tool_result`), as in generation 1. `FollowModel` is the generation-1 policy and the only `Decider`: step and time
  budgets, a plan the model keeps through `update_plan` (strict parse, typed `invalid_plan`) or the loop records itself
  when a long request acts without one, per-step call cap, workflow tool set, `ToolGate` (T133 supplies approvals),
  repeat detection (`cyclic`), progress check after each step (typed error or empty answer: bounded replan, a
  permanent error such as `no_documents` said once and spending no replan, "stop retrying" said once), completion
  check (open steps send the model back `completionRetries` times, then the answer carries "Not complete: ..." and
  the goal event says open), interrupt (every open call is answered `interrupted`, so the conversation stays valid)
  and resume (a call cleared to run whose outcome was lost in a kill is answered `interrupted`, never run again).
  Settings `agent.*` (maxSteps <= 10, timeBudgetSeconds, maxToolCallsPerStep, plan.*, reflect.*) are new in
  `laris-config` with the schema regenerated; the messages are catalogue keys `plan.*`, `reflect.*`, `loop.*` in
  English and Vietnamese. T130 tests were updated for the decision records (a turn is now 14 records). Tests: 20 in
  `tests/agentic.rs` (the generation-1 scenarios 1-4, 6 and 2b translated: plan before the first call and tracked, auto
  plan, short question, planning off, replan that succeeds, bounded replanning, goal held open, unfinished goal
  reported, plan resumed across a reopened log without repeating a step, approval, step ceiling, bad plan, empty
  corpus; plus call cap, tool set, cyclic, time budget, reflection off, interrupt, a scripted decider, undecided answer
  and outcome refused, killed call); each scenario log is replayed byte for byte from the log alone. Not covered:
  scenario 5 (the finished goal and plan written to the vault) belongs to the vault and learning tasks, not the loop;
  answer verification (citations, `verify`) is T136; the `usage` and `compact` events and context compaction are not
  emitted yet and there is no token budget (SR-H1 names one; it needs the usage of the answers and the context estimate); the model trait is `Model`, not `ModelClient` as SR-H1 words it; the P1 `ModelClient` (async) is not wired to the synchronous `Model` trait, so nothing drives a real
  server yet; a `ModelError` is not told apart as auth or quota (one `provider_error` stop); time is measured per
  process, so a resumed turn restarts its clock. `cargo fmt --check`, `clippy -D warnings`, `cargo test`,
  `cargo deny check`, `xtask guard`, `xtask scan`, `xtask schema --check` and `xtask spec` pass. No new dependency
  (`laris-config` is a workspace crate).

## Phase 29 — System: harness

### T132 — Tool registry and coding tools
- Requirements: SR-H4
- Depends: T131
- Deliverables:
  - Local and remote tool registry; `Read`, `Write`, `Edit`, `Glob`, `Grep`, `Bash`, `save_memory`, skills; structured
    errors; limits; untrusted marking; checkpoints and rewind
- Validation:
  - Tests per tool; `Edit` uniqueness; rewind; local and remote tools identical to the loop
- Status: done
- Note: Closed 2026-11-18. `laris-tools` holds one `Registry` (the `ToolRunner` of T131) with the eight local tools
  `Read`, `Write`, `Edit`, `Glob`, `Grep`, `Bash`, `save_memory`, `use_skill` and any number of `RemoteTools` sources
  (the trait T149 implements over `POST /v1/laris/tools/{name}`). Every call is checked against the tool's schema
  (`invalid_arguments`) and every result, local or remote, is finished in one place: a failure becomes the typed error
  `{"error": {"code", "message"}}`, a result over `tools.resultMaxChars` becomes `{"truncated", "chars", "preview"}`,
  and `Read`, `Grep`, `Bash` and every remote tool mark their output `"untrusted": true` (a remote error too, an error
  of ours not). A remote tool is taken to change state, so the permission rules (T133) ask about it. Names cannot be
  registered twice, so a remote tool cannot shadow a local one. `Scope` resolves a path before judging it (`..`,
  symbolic links, dangling links), keeps tools inside the project folder and `permissions.additionalDirectories`,
  refuses secrets by file name (`tools.deniedFiles`) and never writes `.git` or `.laris`. `Write`, `Edit` and
  `save_memory` save the old content to `Checkpoints` first (JSON-lines index and blobs, capped by
  `tools.checkpointKeep`, a failed change discards its checkpoint); `Registry::rewind` restores newest first and skips a
  path a tool could not write now. Files are replaced by temporary file and rename, keeping the mode. `Bash` runs
  `bash -c` in its own process group with a clean environment (`PATH`, `HOME`, `env`; everything only when
  `sandbox.inheritEnv`), standard error merged, a time limit that kills the group, and a capped output read on another
  thread. `use_skill` reads `<folder>/<name>/SKILL.md` from the folders the caller passes. New settings group `tools.*`
  in `laris-config` (13 keys, schema regenerated): the generation-1 `agent.coding` limits plus `resultMaxChars`,
  `skillMaxChars`, `deniedFiles`. Tests (34): per tool (ranges, caps, refusals, secrets, links out of the project,
  atomic write and mode, `Edit` uniqueness and `replace_all`, glob and grep patterns and cut-offs, `Bash` exit code,
  merged output, kill of a child at the time limit, noisy output, environment, memory and skill cases), rewind (order,
  created files removed, cap, a planted index pointing at `.git/config` skipped), argument checks, marking, limits,
  remote tools, and the contract test: a scripted turn calls a local and a remote tool through `Driver`, both answer
  with the same typed shapes, and the log replays byte for byte. Not covered: permissions, modes, hooks and folder trust
  (T133); the OS sandbox and the `uv` Python environment for `Bash` (T135, so `Bash` is not confined here and install
  commands are not refused); redaction is a `Redactor` hook that does nothing until T136; the diff preview for
  approvals (T133); no generic per-tool timeout (`Bash` has its own, the remote client of T149 will have one);
  `Grep` uses the `regex` crate, so look-around and back-references of the generation-1 `re` are not supported; `~` in
  a tool path is not expanded (it is for `additionalDirectories`); skill front matter is parsed as `key: value` lines
  (folded blocks allowed), not full YAML, and `save_skill`, ingestion and vault tools are not here (T127 and the
  learning tasks); `save_memory` writes a plain file, not a vault note; `/rewind` as a command is the client's (T158);
  Linux only was run: the Windows and macOS branches of `Bash` (`taskkill`) are not compiled or tested. No new
  dependency (`regex` was approved; `laris-core`, `laris-config` and `laris-protocol` are workspace crates). `cargo fmt
  --check`, `clippy -D warnings`, `cargo test`, `cargo deny check`, `xtask guard`, `xtask scan`, `xtask schema --check`
  and `xtask spec` pass.

### T133 — Permissions, hooks and folder trust
- Requirements: SR-H5
- Depends: T132
- Deliverables:
  - Modes, rules, saved approvals, hooks with JSON stdin and timeouts, folder trust
- Validation:
  - Mode and precedence tests; denied path never written; hook cases; planted project settings ignored
- Status: done
- Note: Closed 2026-11-18. `laris-policy` holds four parts. `Engine` decides one call, first match wins: a `deny`
  rule refuses; `plan` mode refuses a call that changes state (no rule makes a plan writable); an `ask` rule asks, even
  in `bypass`; an `allow` rule allows; then the mode (`bypass` allows, `acceptEdits` allows `Write` and `Edit`,
  `default` asks for a call that changes state, a read is allowed). Rules are `Tool` or `Tool(pattern)`, tool names
  compared without case, from the settings (`permissions.*`), the folder's saved answers and the session's; a path
  pattern is matched against the resolved path (`..`, symbolic links and absolute spellings do not dodge it), a command
  pattern is not let through by chaining (`allow` must fit every command of a line and refuses substitutions and
  redirections unless the rule spells the whole line out; `deny` and `ask` fit when any command does). `bypass` exists
  only when the installation's policy passes `allow_bypass`; a setting alone is ignored. "Always" answers are kept for
  the session, the folder (`<home>/projects/<slug>/state.json`, mode 0600, damaged file read as empty) or everywhere
  (`permissions.allow` of the settings file, other keys kept). `PolicyGate` is the loop's `ToolGate`: engine, then the
  `PreToolUse` hooks (a hook can block, never grant), then the `Approver` (the front end; `NoApprover` refuses); the
  refusals are the typed errors `permission_denied`, `hook_blocked`, `approval_denied`; a tool the gate does not know is
  taken to change state, so remote tools are asked about; an approval carries the rule an "always" answer would save
  and a diff preview (own line diff, no new crate). `HookRunner` runs `SessionStart`, `UserPromptSubmit`, `PreToolUse`,
  `PostToolUse`, `Stop` from the user's settings only: `bash -c` in the project folder, clean environment plus
  `settings.env` and `LARIS_HOOK_EVENT`, `LARIS_PROJECT_DIR`, `LARIS_SESSION_ID`, JSON on standard input (a hook that
  never reads it does not stall), exit 2 or `{"decision": "block"}` blocks, any other failure, a timeout (the process
  group is killed) or non-JSON output warns and carries on, output cut at 64,000 characters and stripped of control
  characters. `HookedRunner` wraps a `ToolRunner` and puts what a `PostToolUse` hook adds under `hook_context` with the
  result marked untrusted. Folder trust: `ProjectState` (in the home, not the project) and `skill_dirs` and
  `command_dirs`, which add the project's `.laris/skills` and `.laris/commands` only for a trusted folder. A project
  folder has no settings layer, so planted `.laris/`, `.claude/`, `settings.json` and `configs/default.yaml` files
  change nothing. `laris-tools` gained `Scope::locate`, `Scope::relative_to_root` and the exports `shell` and
  `kill_tree` (no behaviour change). Tests (59): rules 6 (syntax, matching table, resolved paths with a symbolic
  link, chained allow and deny); modes 15 (each mode, precedence, deny against every mode and against saved allows,
  bypass bounds, settings changes, cycling, answers kept three ways, bad rule); gate 14 (a denied path never written
  under five spellings and a link, deny beats a yes and is not asked, diff and approval, previews, always, plan mode,
  unknown and remote tools, hook blocks, hook cannot grant, a denied call runs no hook, post hook context, a loop turn
  refused through the gate whose log replays byte for byte); hooks 17 (allow with context and JSON input, exit 2,
  JSON block, matcher and first block, timeout, malformed and failing output, notices, non-UTF-8, flood, ignored
  input, lingering child, control characters, environment); trust 7 (planted settings, hooks and rules ignored,
  untrusted folder without project skills, trust per folder, trust grants no permission). These are the tests for
  SEC-PERM-01 to SEC-PERM-03 of the threat model; T154 collects them. Not covered: the refusal of installs outside the
  sandbox (v1 built-in rule) belongs to T135, which has the sandbox; redaction and the injection defence are T136;
  `allow_bypass` is a constructor argument, no setting or policy file supplies it yet (the client task T155 does);
  nothing wires the gate, the hook events other than `PreToolUse` and `PostToolUse`, or the approver into a running
  session yet (the client tasks); the hook tests are Unix only (Windows `bash` is not run);
  quoted words in a command are split on white space when suggesting a rule; rules over remote tool arguments match
  the first text argument only. `cargo fmt --check`, `clippy -D warnings`, `cargo test`, `cargo deny check`,
  `xtask guard`, `xtask scan`, `xtask schema --check` and `xtask spec` pass. No new dependency (`regex` was approved;
  the others are workspace crates).

### T134 — Sandbox measurement: cut the codex sandbox
- Requirements: SR-H6
- Depends: T121
- Deliverables:
  - Report: codex crates per platform after replacing `codex-protocol` types, line counts, Windows first;
    `THIRD_PARTY.md` entries (origin `aa5f492`, licence, files to modify)
- Validation:
  - Owner reviews and approves the cut
- Status: done
- Note: Measured 2026-11-18 against codex `aa5f492031f7edb75a40973d19eda8efb9512c61`; report
  `docs/architecture/SANDBOX_MEASUREMENT.md` (DRAFT 0.1.0), origin and planned files in `THIRD_PARTY.md`. Uncut closure
  is about 135-140k code lines (28-30 crates); confinement crates are 36.7k, of which Windows is 25.2k. Proposed cut:
  replace `codex-protocol` by an own policy type, drop network-proxy, otel, mxc and pty crates; about 4-5k lines Linux,
  3k macOS, 9-10k Windows with the restricted-token backend (option A, recommended), about 30k in total with the
  elevated Windows backend (B). Finding: the restricted-token path cannot do read-only restriction. NOT verified:
  nothing compiled; macOS and Windows read from source only (Linux machine); estimates are +/-25%. Owner decision 2026-11-18: approved
  all four points (own policy type replacing `codex-protocol`; Windows option A, restricted token only; common drops incl.
  no managed proxy, no `mxc-sandbox`, no bundled `bwrap`; new crates `rustix`, `dunce`, `which`, `indexmap`; `rand` and
  `tempfile` stay unapproved: not needed under option A). `deny.toml` gains them when T135 vendors them.
  Taken out of plan order at the owner's request (T129 done since; T130-T133 still pending; T134 depends only on T121).

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
