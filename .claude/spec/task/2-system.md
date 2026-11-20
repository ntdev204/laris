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
    (Linux and the Python environment here; the macOS and Windows runs are T214)
- Status: done
- Note: Closed 2026-11-18 on `feature/T135-sandbox` with the owner's agreement (the owner has no Windows or macOS
  machine) **for Linux and the Python environment only**: the macOS and Windows backends are written but were never run,
  and their per-platform validation, the part of SR-H6 still open, moved to T214. Do not read this as three-platform
  sandboxing proven. `laris-sandbox`: own `Policy`
  (readable roots or whole disk, writable roots, hidden paths, protected names `.git` and `.laris`, network on/off;
  replaces `codex-protocol`, T134 decision 1). Linux: `bwrap_args` builds the mounts in covering order (read-only
  base, writable roots, protected names read-only, hidden paths last; `--unshare-user/pid/ipc/uts/net`,
  `--die-with-parent`, `--new-session`); the `laris-sandbox-helper` binary runs inside and applies `no_new_privs`
  (`rustix`, no `unsafe`) and a seccomp filter (ptrace, process_vm, bpf, io_uring, keyctl, perf, userfaultfd, kexec
  refused; every non-local socket family refused when the network is off) and then `exec`s the command. Without a
  usable `bwrap` the same helper applies a Landlock ruleset (read everywhere, write only the roots and `/dev`): weaker,
  and `Sandbox::limits()` says so (protected names are writable, no private process namespace, no read hiding; a policy
  that hides paths is refused there). Fail closed: no helper or no backend means the command does not run
  (`Unavailable`, and `Bash` reports `sandbox_unavailable`); on Windows `Sandbox::detect` always refuses. macOS: the
  Seatbelt base and network profiles are forked from codex (header and origin kept) and wrapped by an own generator
  (writable roots minus protected names, hidden paths, network); `sandbox-exec` is taken from `/usr/bin` only; **never
  run on macOS**. Python: `pyenv::ensure(home, settings)` builds `<home>/.venv` with `uv venv` and `uv pip install`
  (`sandbox.python`, `.packages`, `.indexUrl`, `.pythonSource`), under an exclusive lock on `<home>/.venv.lock`, a
  marker holding the settings fingerprint written last; a missing interpreter, a missing marker or changed settings
  rebuild it; a failed build removes the folder. `uv` is `LARIS_UV` or `PATH`; `LARIS_SANDBOX_HELPER` names the helper,
  else it is looked up beside the running program and in the folders above it. `laris-tools`: `Context::with_sandbox`
  and `with_python_env`; `Bash` runs through the sandbox, puts the environment's `bin` first on `PATH` and sets
  `VIRTUAL_ENV`; without a sandbox a package install (`pip`, `uv pip`/`add`/`sync`, `python -m pip`, `conda`, `apt`,
  `brew`, `npm`/`pnpm`/`yarn install`) is refused as `install_outside_sandbox` (the generation-1 rule T133 left here;
  it matches by words, so a command that merely contains `pip install` is refused too). Tests: 10 unit, 10 Linux
  (write outside roots fails and inside works on both Linux backends, link out of the root, read-only policy, network
  cut with local sockets kept and the network allowed again, ptrace, protected names and hidden paths and restricted
  read under bubblewrap, fallback limits, missing helper, exit code), 6 Python (first build, reuse, repair of a broken
  interpreter and of a missing marker, rebuild on changed settings, two concurrent sessions build once, a failed build
  leaves nothing, the environment is read-only to a command), 5 `Bash` (sandboxed write, the time limit kills the group
  inside bubblewrap, `PATH`, install rule, a sandbox that cannot start). New vendored crates: `landlock`, `seccompiler`,
  `rustix` (approved in T119 / T134) and their transitive `enumflags2`, `enumflags2_derive`, `linux-raw-sys`, plus a
  second `syn` 2.0.119 beside `syn` 3 for `enumflags2_derive` (`multiple-versions` warns). Windows (added 2026-11-18, option A): `Backend::RestrictedToken`; the helper makes a `WRITE_RESTRICTED` copy of its token
  (restricting SIDs: a per-user capability SID derived from the user SID, the logon SID, Everyone), grants the capability SID
  write on the writable roots and denies it write on existing `.git`/`.laris`, sets the token's default DACL, starts the
  command suspended inside a kill-on-close job object and returns its exit code. About 330 own lines in `windows.rs`
  (nothing copied from codex's 25k) plus `winargs.rs` (helper arguments, MSVC command-line quoting, capability SID: text,
  unit-tested on Linux). Policies it cannot enforce are refused (hidden or limited reads, network off: the policy must allow
  the network on Windows). `laris-sandbox` now sets its own lints (`unsafe_code = deny`, not the workspace `forbid`) and only
  `windows.rs` allows `unsafe`: confirmed by the owner 2026-11-18. `windows-sys` 0.61 features added to the crate only. Verified: `cargo
  check` and `clippy -D warnings --all-targets` for `x86_64-pc-windows-msvc` (target added with `rustup target add`), 4
  Linux unit tests for the text parts and the command shape. **Not verified: it has never run on Windows**; `tests/windows.rs`
  (write inside/outside, `.git` read-only, exit code, refusals) is written for the owner to run there (`cargo test -p
  laris-sandbox --test windows`). Known limits: no read hiding, no network block, Everyone-writable folders stay writable,
  the capability ACE stays on the roots, no private desktop, no ConPTY, `Bash` still assumes a Unix `sh` and a process group
  (the Windows shell and time-limit kill are not wired). SR-H6 "per platform" stays unmet until the Windows tests pass on
  Windows. macOS untested; the bubblewrap tests need
  unprivileged user namespaces (they run here, they fall back to Landlock only where `bwrap` is unusable); protected
  names that do not exist yet can be created by a sandboxed command (only existing ones are mounted read-only);
  nothing wires the sandbox into a running session (the client tasks); `rand` and `tempfile` stayed unapproved and
  unused. `cargo fmt --check`, `clippy -D warnings`, `cargo test`, `cargo deny check`, `xtask guard`, `xtask scan` and
  `xtask schema --check` pass.

### T214 — Run the sandbox on Windows and macOS
- Requirements: SR-H6
- Depends: T135
- Deliverables:
  - `tests/windows.rs` and `tests/macos.rs` run on their platforms (a machine or a CI runner), failures fixed
- Validation:
  - On Windows and macOS: write outside allowed roots fails, inside works, `.git` and `.laris` stay read-only, exit code
    kept, unenforceable policies refused (Windows); then the Python environment tests on both
- Status: done
- Note: Split from T135 on 2026-11-18 (no Windows or macOS machine). Until it is done SR-H6 "per platform" is unmet there
  and the sandbox must be described as proven on Linux only. `cargo test -p laris-sandbox --test windows` and `--test macos`
  are written; Windows needs `bash` (Git for Windows) on `PATH` for `Bash`, and a policy that allows the network
  (`Policy::with_network(true)`), since the backend cannot block it. Also open there: wiring a sandbox policy into a
  running session (client tasks).
- Result: 2026-11-20, closed on the owner's order ("duyệt, commit và merge"). **No run of `cargo test -p laris-sandbox --test windows` or `--test macos`, or of the Python environment tests on those systems, is recorded in this repository**; the agent has only a Linux machine. The task is closed as accepted by the owner, not as measured: until a run on Windows and macOS is recorded, the sandbox must still be described as proven on Linux only, and SR-H6 "per platform" is unmet there in the sense of the original validation.

### T136 — Redaction and injection defence
- Requirements: SR-H10
- Depends: T132
- Deliverables:
  - Redaction before P1; untrusted data handling; policy refusal of injected command requests
- Validation:
  - Security tests: secrets in output, injected document, hostile hook output
- Status: done
- Note: Built in `laris-policy` (no new crate or dependency; `laris-protocol` became a normal dependency of it).
  `Redactor` hides private key blocks (also cut short), AWS, GitHub, GitLab, OpenAI/Anthropic-style, Slack, Google,
  Stripe keys, JWTs, bearer headers, passwords in URLs and `secret = value` assignments (name kept, value masked as
  `[REDACTED]`), plus the exact values of secrets held in the environment (`from_process_env`, names with `KEY`,
  `TOKEN`, `SECRET`, `PASSWORD`, ...; eight characters or more). It is applied where text is kept or leaves: to what
  `Write`, `Edit` and `save_memory` persist (`Redactor::for_tools`), to every tool result before the loop logs it
  (`ShieldedRunner`, so the event log never holds the secret), and to the whole conversation and the note just before
  a request goes to the model service (`RedactingModel`; the loop's own conversation and its digest are unchanged,
  and a message that cannot be redacted is not sent). `Shield` is the injection defence: a result marked
  `untrusted` (local tools, remote tools) is remembered and searched for text that gives orders (ignore earlier
  instructions, new instructions, speaking as the system, role markers, run the following command, hide this from the
  user, reveal secrets, download into a shell; English and Vietnamese); such a result gets an `injection_warning`.
  After that alarm a call is refused as `injected_request`, whatever the rules, mode or saved approvals allow, when
  it repeats a command, address or path from untrusted content that the user did not write (`Shield::user_says`), or
  when a Bash command reaches beyond the project (download piped into a shell, `sudo`, `~/.ssh` and other key
  stores, `.env`, upload to an address, `rm` of `/` or `~`, edits to the sandbox or rules). What the user typed
  authorises; with no alarm the shield does nothing and the permission rules stay in charge. `PolicyGate::with_shield`
  puts it ahead of hooks and questions. Hook output (`HookedRunner::with_shield`) is redacted, watched for orders and
  carries a warning line. Tests (18): redact 9 (shapes, names kept, ordinary text untouched, idempotent, literal and
  environment secrets, JSON, secret in `Read` and `Bash` output and in an error, what `Write` persists, the request
  that leaves); shield 9 (clean session untouched, injected README flagged and its command refused even with
  `Bash(*)` allowed, user's own words authorised, escapes refused after an alarm, no alarm no refusal, secret and
  injection in one file, address argument, hostile remote tool, hostile hook output). These are the tests for
  SEC-INJ-01 to SEC-INJ-03 of the threat model; T154 collects them. Limits: a filter and a text rule, not a proof; a
  secret in a shape nobody listed passes, a hostile document that matches no pattern and whose words the model does
  not repeat is not caught, and the assignment rule also masks harmless values such as `password: required`;
  nothing wires the shield, `RedactingModel` or `user_says` into a running session yet (the client tasks); the
  escape patterns are for Bash and the address rule covers arguments that look like a URL or path. Found, not
  fixed (T133): `tests/hooks.rs` is flaky on the baseline too (one of `control_characters_cannot_reach_the_terminal`,
  `a_json_decision_blocks`, `output_that_is_not_utf8_is_a_warning_not_a_crash` fails in about one run in three with
  `getcwd: cannot access parent directories`). `cargo fmt --check`, `clippy -D warnings`, `cargo test` (except that
  flake), `cargo deny check`, `xtask guard`, `xtask scan` and `xtask schema --check` pass.

### T137 — Evidence gate
- Requirements: SR-H7
- Depends: T131
- Deliverables:
  - Citation parser and checker for workspace evidence and `LarisMeta` brain evidence; absence-of-evidence rule;
    unsupported-statement marking
- Validation:
  - Fabricated citation, missing span and unsupported claim caught; valid answers unchanged
- Status: done
- Note: Built in `laris-evidence` (new dependencies: `laris-protocol`, and `regex` and `serde_json`, already in the
  workspace). `Evidence` holds what the turn received: hits read from retrieval tool results (`absorb_text` for lines
  `[source #rank] title: excerpt`, `absorb_json` for objects with `source`, `rank` and `text`/`excerpt`/`snippet`/
  `content` at any depth) and the brain titles of `LarisMeta` (`set_brain`). `citation::parse` reads `[source #rank]`
  (rule E-2) and `[brain: Title]`, plus the verbatim quote standing right before a citation; code is not read.
  `Gate::check(answer, &evidence)` returns a `Verdict` with findings and the answer marked in place: a citation that
  names no hit or no listed brain note (`fabricated_citation`); a quote of eight characters or more that is not in the
  cited hit after case, whitespace and typography are folded, an ellipsis standing for text left out (`span_missing`);
  a sentence of six words or more that cites nothing and is not marked assumed, speculative, a hypothesis or
  unverified (`unsupported_statement`; only when the turn retrieved evidence or the answer cites, or with
  `Gate::strict`); a conclusion of absence or of a research gap that does not say what was searched (`absence_claim`,
  rule E-5; the same sentence with a scope word is a report of the search and passes). Headings, tables, questions,
  first-person and "here is" sentences and the closing blocks (Assumptions, Uncertainties, Next step, Sources) are
  not statements. An answer without findings is returned byte for byte unchanged. Tests (15): valid answer
  unchanged, valid quote after folding, fabricated citation, missing span, unsupported claim, assumed statements,
  chat left alone, absence rule, brain citations, JSON results, parser, code skipped, abbreviation and citation full
  stops, non-statements, several findings marked in order. Limits: it proves that cited places exist, not that they
  entail the claim (that is the model block's NLI, D41); ranks repeat across searches, so a citation matches any hit
  with that source and rank; "statement" is a sentence of some length, the patterns are English and Vietnamese
  text rules; nothing wires the gate into a session yet (the client tasks); `Config` and `Marks` take their defaults
  until the client reads them from settings. `cargo fmt --check`, `clippy -D warnings`, `cargo test`, `cargo deny
  check`, `xtask guard`, `xtask scan` and `xtask schema --check` pass.

### T138 — Learning data from the event log
- Requirements: SR-H11
- Depends: T130
- Deliverables:
  - Example derivation; `laris learn export` JSONL
- Validation:
  - Export matches the fixture; no collected data in P1 requests or the repository
- Status: done
- Note: Closed 2026-11-18. `laris_policy::learning` (new dependencies: the workspace crates `laris-evidence`, and
  `sha2`, already in the workspace) folds a session's log with `Session`, exactly as replay does, and each `done`
  event closes a turn. A completed turn that passes the gate gives up to three examples with content-derived ids
  (first 16 hex digits of a SHA-256) and `ts` taken from the log, so the same log gives the same bytes: `sft` (the
  conversation up to the answer, without the loop's own retry and notice messages and without drafts the loop sent
  back; tool results kept, cut or `[omitted]` by settings), `retrieval` (query of a retrieval tool, cited-source hits
  as positives, up to five others as negatives, passage text or only its SHA-256) and `preference` (a draft sent back
  against the answer that stood). The gate leaves a turn out as `not_completed`, `injection_flag` (a tool result with
  an `injection_warning`), `sensitive` (anything the `Redactor` would hide: rejected, not repaired), `unverified` (the
  T137 `Gate` marks the answer: fabricated citation, missing span, unsupported or absence claim) or `short_answer`.
  `collect(store, session, ..)` keeps the rows in the `learning` table of the client store (new `Store::put_learning`,
  `learning`, `purge_learning`, `sessions`; the unique index of migration 2 makes a repeat a duplicate); with
  `learning.collect` off it reads and writes nothing. `rate`, `ratings`, `stats`, `export` (JSONL plus manifest with
  count, rating rule and SHA-256; a down-rated example never leaves, `exportMinRating: up` keeps only up-rated ones,
  pairs follow the example they came from) and `purge`. `write_export` refuses a path inside a Git work tree.
  Settings `learning.*` gain `minAnswerChars` (40), `maxToolResultChars` (3000), `storeToolResults` (true),
  `storePassageText` (true), `exportMinRating` (none) and `retrievalTools` (`search_corpus`), the generation-1
  values; the schema was regenerated. `laris-cli` becomes a library and the `laris` binary with `laris learn stats |
  collect [--session ID] | export --kind sft|retrieval|preference --out FILE [--min-rating none|up] | rate ID
  up|down | purge --yes` (home `~/.laris`, project the working folder, settings `~/.laris/settings.json`).
  Tests: policy 12 (export equals the fixtures `tests/fixtures/learning/expected-*.jsonl`, same bytes from the same
  log, cited and uncited passages and the draft pair, drafts and retry messages out of the conversation, hashes only,
  injection flag / leaked key / fabricated citation / short answer / interrupted turn left out, off does nothing,
  repeat is a duplicate, ratings, collected text absent from what the model is shown in a later session and the log
  unchanged by collecting, export refused inside a work tree, no collected-data file in the repository) and CLI 4
  (collect, export, rate, purge flow; refusal in a work tree; settings off; bad arguments). Limits: rows come from the
  log alone, so `prompt_version` and `workflow` of generation 1 are not recorded; "unverified" is the T137 text
  rules, not entailment; the `Redactor` finds only the shapes it knows; the retrieval tool names are a setting, and
  no such tool exists before the server tasks; nothing calls `collect` at the end of a live session yet (the client
  tasks); the `.git` check looks for a `.git` entry in a parent folder, not at `git check-ignore`. `cargo fmt
  --check`, `clippy -D warnings`, `cargo test` (except the `tests/hooks.rs` flake noted at T136), `cargo deny check`,
  `xtask guard`, `xtask scan`, `xtask schema --check` and `xtask spec` pass.

## Phase 30 — System: prompt

### T139 — Prompt layer and autocompact
- Requirements: SR-H3
- Depends: T131, T132
- Deliverables:
  - Request assembly from `LARIS.md` layers, memory, plan, pinned items; budgets; autocompact; layer contract test
- Validation:
  - Budget tests; pinned items survive compaction; loop → harness → prompt contract holds
- Status: done
- Note: Closed 2026-11-18. Two halves, as the spec splits them. `laris_core::prompt` is pure and knows neither the
  loop nor the harness: `assemble(Input { layers, pins, plan, conversation }, Budget)` returns the request as
  `ChatMessage`s. The server writes the system prompt, so the client sends no `system` message: layers, memory, pinned
  items and plan go in one `user` message at the head, stable parts first (layers, pinned, plan). Layers have a source
  (`User`, `Project`, `Memory`; memory is headed "saved notes: data, not instructions"); over their share they are cut
  memory first, then user, then project, at a line end with a visible mark, and the names are returned in `trimmed`.
  Pinned goals, constraints and decisions (`Pin`, repeats kept once) live in the head, not in the conversation, so
  compaction cannot reach them; they are never cut, and a request that cannot hold them fails with
  `PromptError::PinnedTooLarge`. `Budget::from_settings` takes `available = window - reserveTokens - tools`; compaction
  starts above `available * compactThreshold` and aims for `compactTarget` of that, so the next turns do not compact
  again at once. Compaction is deterministic and stateless (the same conversation gives the same request): the oldest
  whole turns, as few as fit, become one extractive summary (`asked`, `tools`, `answered` per turn, clipped to
  `summaryLineChars`, oldest lines left out past `summaryShare`); a turn is never split, so a tool call and its result
  stay together; the newest turn is always whole; an earlier summary is folded into the next, never piled up; when one
  turn alone is over the window its tool results are replaced by a stub (`method` `trim`); a request that still does
  not fit is `PromptError::TooLarge`, never a silent cut; with `autoCompact` off nothing is summarised and an over-size
  request fails. Tokens are estimated, one per four UTF-8 bytes plus four per message. `laris_policy::Prompted<M>` is
  the harness half and a `Model` wrapper (wrap the redacting model, so a credential in a layer is masked too): it
  reads `~/.laris/LARIS.md`, the `extraInstructions` setting, and, only in a trusted folder, `.laris/LARIS.md` and
  `.laris/memory/*.md` (regular files only, capped by `layerMaxChars`, at most `memoryMaxNotes` notes, in name order),
  holds the shared `PinBoard`, folds the decider's per-call plan note into the head, and keeps `last()` (tokens,
  window, compaction, trimmed layers) for the client's `usage` and `compact` events. The loop's conversation, its
  digest and the log are untouched, so a prompted session replays byte for byte with the bare scripted model. New
  settings `context.compactTarget`, `reserveTokens`, `layerShare`, `pinnedShare`, `summaryShare`, `summaryLineChars`,
  `layerMaxChars`, `memoryMaxNotes` (the budget numbers are settings, not constants); the schema was regenerated. No
  new dependency. Tests: core 13 in `tests/prompt.rs` (nothing to add leaves the conversation alone, head order and
  no system message, layer cuts, pins never cut and repeats, budget arithmetic, below trigger, summary and newest turn,
  determinism and carried summary, auto-compact off, huge single turn, unfittable request, token estimate, and a
  400-case seeded property test that pinned items survive, the request fits the window, the latest message is last
  and every tool call keeps its result) and policy 9 in `tests/prompted.rs` (trust rule, caps, symbolic link and note
  limit, pins, the loop → harness → prompt contract with a driven session, replay without the prompt layer, a long
  session compacted in the request only with pins intact, an unfittable request ends the turn without asking the model,
  masking inside a layer). Limits: nothing emits the `usage` and `compact` events or sets the pins yet (the client
  tasks: `/pin`, status line), and the loop has no token budget of its own; the summary is extractive, not written by
  a model, so it keeps what was asked, which tools ran and a clip of each answer, not reasoning; compaction is
  recomputed for each request from the whole log, so the cut moves as the session grows (a server-side prefix cache
  sees a changing prefix after each compaction); the estimate is bytes over four, not the model's tokenizer; the
  project layer and memory are ignored in an untrusted folder, which is the safe side but means an untrusted folder
  gets no project memory; pins are not persisted across a restart (a client task). `cargo fmt --check`, `clippy -D
  warnings`, `cargo test` (except the `tests/hooks.rs` flake noted at T136, which passes alone), `cargo deny check`,
  `xtask guard`, `xtask scan`, `xtask schema --check` and `xtask spec` pass.

### T140 — Model-free evaluation runner
- Requirements: SR-H15
- Depends: T135, T136, T137, T138, T139
- Deliverables:
  - One command replaying golden and Agentic scenarios, evidence checks, leak and injection tests and vault round trips;
    report outside the specifications
- Validation:
  - Reproducible run; seeded regression fails
- Status: done
- Note: Closed 2026-11-18. `cargo xtask eval [--out FILE] [--baseline FILE] [--write-baseline] [--seed-regression
  PERCENT]` (`xtask/src/eval.rs`, no new crate) runs the model-free suites as the workspace's own test targets, one
  `cargo test -p P --test T -- --test-threads=1` each (one thread, because `tests/hooks.rs` flakes under parallel
  runs, T136), and sums the `test result` lines. Suites: golden (protocol fixtures and core events, vault index and
  writer golden, retrieval golden, store), agentic (the translated scenarios and event-log replay), evidence,
  leak (`redact`), injection (`shield`, `hooks`, `trust`), vault round trips (`vault_fs`, `writer_fs`), retrieval
  behaviour, prompt, permissions (policy and tools) and sandbox (Linux, Python environment, sandboxed `Bash`). The
  runner also measures retrieval on the fixture vault itself (BM25 and graph recall@5, MRR, nDCG@5 from
  `tests/fixtures/retrieval`). `reports/model_free/baseline.json` holds the passed count per suite, those six figures
  and `tolerancePercent` (20; the file is the authority, not the code). A figure worse than its baseline by the
  tolerance or more fails, so does any failed test, a suite or figure missing from the baseline, and a suite that
  did not build. The report `reports/model_free/rust_report.json` has no timestamp or duration and sorted keys: two
  runs gave the same bytes. `--seed-regression P` makes every figure P percent worse before the comparison, writes no
  default report and must exit 1: at 20 every suite and figure fails, at 19 the unit test shows it passes. The
  generation-1 `reports/model_free/report.json` is left as it was. Tests: 7 unit tests in `xtask` (counts parsing, a
  run with no result line, inclusive threshold, seeded 20 fails and 19 passes, failed or lost test or unknown figure,
  same bytes, arguments). Limits: the suites are the existing tests, so the runner adds no new check, only one
  command, one baseline and one report; benchmarks are not run (the budgets are fixed from measurements in T154); the
  baseline is the Linux development machine (a platform that runs fewer sandbox tests must not use it); a passed
  count only has to stay within the tolerance, so a lost test below 20 percent is not caught, a new test needs a
  baseline refresh with `--write-baseline` only to raise the floor; a scripted model plays the model, so nothing
  shows capability of the foundation model, which is NOT QUALIFIED. The sandbox suite covers Linux only (macOS and Windows runs are T214). `cargo fmt --check`, `clippy -D warnings`, `cargo test` for
  `xtask`, `cargo deny check`, `xtask guard` and `xtask scan` pass.

## Phase 31 — Server: LLM

### T141 — laris-server: hardened API
- Requirements: SR-S1
- Depends: T123, T125
- Deliverables:
  - axum app, configuration, health, body validation, trusted proxies, content-free logs, mid-stream error events
- Validation:
  - Tests for 400, 411, 413, mid-stream error, slow client, proxy rules
- Status: done
- Note: Closed 2026-11-18. `laris-server` is now a library plus the binary. `config`: `ServerConfig::from_env` reads
  `LARIS_SERVER__*` passed in by `main` (the library never reads the environment); `BIND` is required and has no
  default; body limit, trusted proxies, header, body and stream-idle timeouts, connection limit, embed input limit and
  shutdown grace have defaults in code and are settings; an error names the variable, never the value. `proxy`:
  `Cidr`, `TrustedProxies::client_ip` (an untrusted peer is the client and `X-Forwarded-For` is ignored; from a trusted
  peer the chain is read from the right, trusted hops skipped, the first other address is the client; garbage ends the
  walk at the address a trusted proxy vouched for; IPv4-mapped IPv6 is normalised). `app`: routes `GET /health`,
  `POST /v1/laris/chat`, `POST /v1/laris/embed`; JSON 404 and 405; order of checks `X-Laris-Protocol` (426), no
  `Content-Length` or `Transfer-Encoding` (411), non-number (400), over the limit (413, decided from the header before
  any body byte is read), content type (400), body read under a total deadline (408), parse and rules (400: empty
  messages, system role, `stream:false`, session id form, embed input empty or over the limit); error bodies are
  `{"error": ...}` as in generation 1. `ApiError` carries all of 400, 401, 403, 404, 405, 408, 411, 413, 426, 429
  (with `Retry-After`), 500, 502; 401, 403 and 429 are produced from T143 on, the tests only prove the mapping through a
  refusing backend. `backend::Backend` is the seam to the model (chat stream, embed); `NoBackend` answers 502 until T144.
  A failure inside the answer stream, or silence longer than `stream_idle`, becomes an `error` event then `[DONE]`
  (status 200 already sent). `log`: one record per request (id, method, route name, status, body bytes, duration,
  client address, outcome), written once even for a client that leaves (status 499, `client_gone`); there is no field
  for path, query, header, body, key or message text, and the route is a fixed name, so `unmatched` stands for any
  unknown URL; `X-Request-Id` is made by the server. `serve`: own accept loop on hyper (header read timeout, 32 KiB
  header buffer, connection limit that sheds the extra connection, graceful stop with grace). Tests: 19 over real
  sockets in `tests/api.rs` (raw bytes: 400 cases, 411 for missing length and chunked, 413 answered before the body is
  sent and exactly at the limit, 426, mid-stream error and idle stream with the event sequence, client leaving,
  slow body 408, slow headers cut, connection limit, trusted and untrusted proxy, no marker from body, key, cookie,
  query, path or message in the log, unique server-made ids, shutdown), `tests/config.rs` 4, `tests/proxy.rs` 6,
  `tests/log.rs` 2, `error` unit tests 2. Dependencies (approved in T119): `axum` 0.8.9 with `http1` and `tokio` only;
  `cargo vendor` added `axum`, `axum-core`, `matchit`, `mime`, `httpdate`, `errno`, `signal-hook-registry` (listed in
  `deny.toml` and `THIRD_PARTY.md`); `hyper` and `hyper-util` (already vendored) are used directly for the header
  timeout, not on the T119 direct list (owner confirmed 2026-11-18); `futures-util`, `tokio` (`signal`, `rt-multi-thread`),
  `thiserror`, `serde`, `serde_json` as before. Limits: no TLS (Caddy in front, SR-S1); no keys, roles, quotas or
  storage yet (T143, T142); the model is behind `Backend` and `NoBackend` (T144); a client that reads slowly
  is cut by the write-stall guard (see the amendment below), so the slow-client rules cover both directions; only `/health`, `chat` and `embed` exist, the other P1 routes come
  with their tasks; `stream:false` is refused with 400 (generation 1 had no recorded non-streaming chat); the
  access log goes to standard error as JSON lines, no subscriber crate. Amendment 2026-11-18 (branch
  `feature/T141-write-stall`, owner asked after the first close): `stall::StallGuard` wraps each accepted socket; a
  write or flush that stays blocked by the peer for `LARIS_SERVER__WRITE_STALL_MS` (default 30000) fails with
  `TimedOut`, hyper ends the connection, the answer stream is dropped (the backend stops) and the log says
  `client_gone`. The clock runs only while the peer blocks a write and restarts on every write that progresses, so
  waiting for the model or for the next request is not counted. Tests: a client that stops reading a 320 MB lazy
  stream is cut within 3 s and its only connection slot is free again while it keeps the socket open; a client that
  reads steadily but slower than the server is not cut (all bytes and `[DONE]` arrive); with the guard disabled the
  first test fails. Limit: the guard bounds one blocked write, not the total time of an answer, so a client that reads
  one buffer just under every `write_stall` can still hold a slot for the length of the answer (the model's own
  limits bound that; a total-time limit per answer is not set). `cargo fmt --check`, `clippy -D warnings`,
  `cargo test`, `cargo deny check`, `xtask guard`, `xtask scan`, `xtask schema --check` and `xtask spec` pass.

### T142 — PostgreSQL storage
- Requirements: SR-S3
- Depends: T141
- Deliverables:
  - Migrations continuing generation 1, pool, partitions, retention, daily summary
- Validation:
  - Tests under `LARIS_TEST_PG_DSN`; generation-1 dump migrates without loss
- Status: done
- Note: Closed 2026-11-18. Module `laris_server::storage`. `migrate`: `0001` to `0003` are the generation-1 files byte
  for byte (`crates/laris-server/migrations/`), the version table is the same `schema_version`, the advisory lock id is
  generation 1's (7260001), so a generation-1 database is already at version 3 and a restored dump is continued, never
  rewritten; each migration and its version row commit together; a database with a version this build does not know
  (newer server) or a version recorded under another file name is refused and left untouched. There is no `0004`: the
  generation-1 schema already holds the daily summary and what T143 needs; the next task that needs a column adds it.
  `StorageConfig::from_env` (`LARIS_SERVER__DATABASE_URL` required, `DATABASE_SCHEMA`, `DB_POOL_MAX`,
  `DB_ACQUIRE_TIMEOUT_MS`, `USAGE_RETENTION_DAYS` 90, `TRACE_RETENTION_DAYS` 30, `RETENTION_INTERVAL_S` 3600); `Debug`
  hides the connection string and no error text holds address, user or password. `Storage::connect` opens a bounded
  `sqlx` pool (`runtime-tokio` and `postgres` only: no TLS, since PostgreSQL sits on the compose network; no macros, no
  `migrate`), migrates and makes the partitions of the previous, this and the next two months;
  `ensure_current_partitions` repeats it once per month per process and `begin` calls it before a transaction.
  `Maintenance`: `ensure_partitions`, `partitions`, `summarise` (one `usage_daily` row per key and UTC day, rebuilt
  from the last summarised day, idempotent), `daily`, `purge` (drops whole months before the cutoff, summarising usage
  first, then trims the straddling month; usage 90 days, traces 30), `run_once`; `RetentionHandle::spawn` repeats a
  round every interval, keeps the last error in `Storage::last_retention_error` and stops on request. Every maintenance
  step takes the generation-1 advisory lock 7260002. Tests: 13 in `tests/storage.rs` against PostgreSQL 16 (fresh
  database, concurrent start applies once, dump at version 2 (before partitioning) migrates with every usage, trace and
  key row equal and the id sequence continuing, dump at version 3 taken as it is with `applied_at` unchanged, newer
  version and renamed version refused, partitions and the missing-month failure, summary at the UTC day boundary and
  re-run, retention keeping the summary, retention task, pool bound and timeout, unreachable error without secrets,
  settings), 3 unit tests. The two dumps are `pg_dump` output of synthetic rows built from the generation-1 SQL by
  `tests/fixtures/make_gen1_dumps.sh`; the real trial database was not touched. Without `LARIS_TEST_PG_DSN` the
  PostgreSQL tests print a notice and pass, so they prove nothing there: run them with a throwaway PostgreSQL 16
  (`docker run --rm -e POSTGRES_PASSWORD=... -p 127.0.0.1:55432:5432 postgres:16`). Dependencies (sqlx approved in
  T119): `sqlx` 0.8.6 vendored with its transitive crates (about 60 new directories in `vendor/`) (`deny.toml`, `THIRD_PARTY.md`). Limits: storage is not wired
  into `main` or `AppState` yet (T143 needs it); no key, usage or trace store yet (T143, T144); the real
  generation-1 dump of the trial server is restored by the owner at deployment (T160 range), the fixtures stand in for
  it. `cargo fmt --check`, `clippy -D warnings`, `cargo test`, `cargo deny check` and `xtask spec` pass.

### T143 — Keys, roles, quotas, admin
- Requirements: SR-S2
- Depends: T142
- Deliverables:
  - Digest-only keys, roles, quota reservation and settlement, expiry, revocation, admin and account routes
- Validation:
  - 401, 403, 429; parallel quota test; no key printed
- Status: done
- Note: Closed 2026-11-18. Module `laris_server::access`, routes in `admin`. Keys: `lk_<id>_<secret>` (4 random bytes of
  id, 24 of secret from `/dev/urandom`, Unix only like the container); the table is the generation-1 `keys` table, the
  stored digest is `HMAC-SHA256` under a lookup key derived from the master secret with the generation-1 steps, so keys
  made by generation 1 verify (checked against a digest computed by the generation-1 Python); a plain SHA-256 digest of
  an older key is accepted once and rewritten keyed. No encrypted copy of a key is kept (`secret_enc` stays NULL): a
  key is shown once, in the answer that creates it, and cannot be revealed later; a generation-1 `keys reveal` has no
  counterpart. The master secret comes from `LARIS_SERVER__MASTER_FILE` (a Docker secret) or `LARIS_SERVER__MASTER`,
  at least 16 characters, never in the database, `Debug` or an error. Roles are generation 1's (`user`, `readonly`,
  `auditor`, `admin`) as defaults in code, replaced by `LARIS_SERVER__ROLES` (JSON); privileged permissions
  (`usage.read`, `reasoning.read`, `keys.manage`) go to privileged roles only. Order of checks on every route: 426,
  then the key (401: missing, wrong scheme, unknown id, wrong secret, revoked, expired and a forbidden address answer
  with the same body; the same digests are computed whether or not the id exists), then the permission (403), then the
  body rules, then the reservation (429). Address rules (`allowed_ips`, CIDR or `@server` = loopback plus
  `LARIS_SERVER__SERVER_IPS`) use the client address of T141's trusted-proxy logic. Quota: `access::reserve` is one
  `UPDATE` that adds to `tokens_reserved` only while `tokens_used + tokens_reserved + need <= token_limit` and the key
  is not revoked or expired; `settle` writes the usage row and frees the reservation in one transaction; `release` frees
  it; a reservation dropped without either is released in the background; chat is settled when its stream ends,
  fails or the client leaves (what was produced is charged: the model's own `usage` when a chunk carries it, else the
  prompt estimate plus visible characters over `LARIS_SERVER__CHARS_PER_TOKEN`, default 4); a model failure before the
  stream, or a refused embed, charges nothing. Routes: `GET /v1/laris/account` (role, permissions, limit, used, left),
  `GET /v1/admin/usage` (`usage.read`), `GET` and `POST /v1/admin/keys`, `POST /v1/admin/keys/{id}/revoke` and
  `/limit` (set, add, lift) (`keys.manage`); the listings never hold a digest or key text. First start: `main` makes
  the built-in admin key (every permission, no limit, `@server` only) when none exists and writes it to
  `LARIS_SERVER__FIRST_ADMIN_FILE` (0600), refusing to start without that variable until a key exists; the text is not
  printed. `main` now connects storage, runs the retention task and builds the access layer; `AppState::open` (no keys)
  exists for the T141 HTTP tests only. Tests: `tests/access.rs` 14 against PostgreSQL 16 (digest-only storage and
  master separation; generation-1 keyed and plain digests; expiry and revocation; six kinds of invalid key give one
  401 body; 403 by role and extras; 429 and nothing charged; 40 parallel reservations of 10 against a limit of 95
  give exactly 9; 16 parallel HTTP chats against a quota for 4 give 4 and 12 429s; model down releases, a client that
  leaves is charged for what it was sent, embed settles with reported usage; account; the admin life of a key with
  400, 404 and 405; address rules; no key text in answers, access log or `Debug`; settings), 8 unit tests, the 21 T141
  API tests unchanged. Without `LARIS_TEST_PG_DSN` the PostgreSQL tests pass without proving anything (see T142).
  Dependencies: `hmac` 0.12 and `sha2` 0.10 (approved, already vendored). Limits: no key-lookup cache (every request
  reads the database; the generation-1 TTL cache is not rebuilt, so a revocation applies at once); the reservation is
  the prompt estimate only, so one request can pass a limit by what the answer adds beyond it (the ADR-018 rule: one
  request may overshoot); `@server` does not discover the machine's own addresses (list them in
  `LARIS_SERVER__SERVER_IPS`); reasoning routes and `/v1/models`, workflows and help come with their tasks (T144 and
  later); the Python model service is not involved yet. `cargo fmt --check`, `clippy -D warnings`, `cargo test`
  (470 tests with PostgreSQL), `cargo deny check`, `xtask guard`, `xtask scan`, `xtask schema --check` and
  `xtask spec` pass.

### T144 — Model proxy and the LLM rung
- Requirements: SR-S6, SR-M1, SR-S9
- Depends: T143
- Deliverables:
  - P2 client with bounded concurrency and stream passthrough; `/chat` and `/embed` end to end; LLM-rung scenario
- Validation:
  - Contract tests against the Python model service (placeholder); first-chunk latency measured; scenario passes
  - Behind the T146 gateway: reasoning from the model service never appears in a chat body; the system prompt and
    the canary never leave
- Status: done
- Note: Closed 2026-11-19. New module `laris-server::model`: `ModelConfig` (`LARIS_SERVER__MODEL_URL`, `_NAME`,
  `_MAX_CONCURRENT`, `_QUEUE_WAIT_MS`, `_CONNECT_TIMEOUT_MS`, `_HEADER_TIMEOUT_MS`, `_IDLE_MS`, `_MAX_EVENT_BYTES`;
  no URL means no model and `main` keeps `NoBackend`, 502, with a line on stderr; `Debug` hides the address) and
  `ModelBackend`, a `Backend` that speaks P2 (`/v1/chat/completions`, `/v1/embeddings`) with `reqwest`: no redirects,
  no environment proxy. A semaphore bounds the calls open at once (chat and embed share it); a call waits
  `queue_wait` and is then refused with the new `ApiError::Unavailable` (503); the place is held for the whole stream
  and returns when the stream ends or is dropped (client gone, request to the model closed). Streaming is pulled
  event by event (`SseDecoder`, no buffering of the answer); the first event is read before `chat` returns, so a
  refusal, a 503, a first-event `error` or garbage is a status and not an empty stream; after that a model `error`
  event, a stream cut without `[DONE]`, silence over `_IDLE_MS`, a broken event or an oversized one ends the stream
  with one `StreamFailure` (kinds `model_error`, `model_truncated`, `model_idle`, `model_protocol`,
  `model_connection`). Messages are fixed: neither the model's own text nor its address reaches a client. Only the
  conversation, the tools and a numeric `temperature` go to the model; the `laris` block and unknown fields stay
  behind. Reasoning stays in the chunk for the policy gateway. Tests (`tests/model.rs`, 17, plus 6 unit tests):
  pass-through with usage, what reaches the model, embed, every failure before and after the first chunk, an
  unreachable model, concurrency limit (third call refused after its wait, refused calls never reach the model, a
  dropped stream frees its place, a waiting call gets a finished answer's place), first-chunk latency, behind the
  gateway over HTTP (reasoning and `<think>` never in a chat body and kept for the operator; a model told to repeat
  its system prompt is stopped, the canary never leaves; a dead model is a 502), the LLM-rung scenario (core loop ->
  P1 client -> server with policy gateway -> `ModelBackend` -> model: answer, usage, prompt and reasoning stay
  server-side, embed through the P1 client, a mid-answer failure ends the turn without the model's words) and a
  contract test against the real Python model service with its placeholder backend. The Python test runs only when
  `LARIS_TEST_MODEL_PYTHON` names a Python with the repository's dependencies; without it the test passes without
  proving anything (as the PostgreSQL tests do); run here with `.venv/bin/python`: 20 chats parsed, a refused embed
  (the placeholder has no encoder). First-chunk latency through the proxy on localhost, measured here: fake model
  median 0.43 ms, P95 0.67 ms; Python placeholder median 1.2 ms, P95 2.3 ms; this is the proxy's own cost, not a
  model's. Dependencies: `reqwest` 0.12 (rustls) and `bytes` 1 added to `laris-server`, both already vendored and
  approved for the client. Limits: `/tools/{name}` is T149; one model address, no retry or failover (a failed call is
  a failure, the client decides); the reservation of quota is unchanged (T143). The model is a script or a
  placeholder, so only mechanics are proved; the foundation model is NOT QUALIFIED. `cargo fmt --check`,
  `clippy -D warnings`, `cargo test` (without PostgreSQL), `cargo deny check`, `xtask guard`, `xtask scan` and
  `xtask schema --check` pass.

## Phase 32 — Server: RAG

### T145 — laris-retrieval
- Requirements: SR-L3
- Depends: T126
- Deliverables:
  - BM25, graph expansion, fusion, span provenance, dense channel interface (not qualified); benchmark report
- Validation:
  - Rankings equal generation 1 on the fixture; metrics computed; P95 measured
- Status: done
- Note: Closed 2026-11-18. `laris-retrieval` (depends only on `laris-vault`; no new crate) holds `search` (`NoteSearch`:
  Okapi BM25 over body and title, title words count three times, k1 1.5, b 0.75, inverted index, terms summed in
  sorted order so every score is built as generation 1 builds it), `graph` (`GraphRetriever`: BM25 seeds plus the
  notes linked around them with the decayed score; folder filter), `fusion` (`fuse_with_corpus` with generation 1's
  Source-note naming rule, and `fuse_ranked`, a weighted reciprocal-rank fusion over any channels with ties by id),
  `provenance` (`cite` gives each result the best paragraph as a byte range of the note body with the verbatim text
  and the note's SHA-256; `verify_span` fails closed on a missing note, a changed note, a bad range or a different
  text), `dense` (`DenseChannel` trait, `NoDense`; `qualified()` is `false` by default and a fused result lists
  `unqualified_channels`, so an answer that used a dense hit carries the label until stage 1 passes G12) and
  `metrics` (recall@k, MRR, nDCG@k, `evaluate`). Parity: `tests/golden/retrieval/cases.json` is written by
  `generate.py` from the generation-1 code on `tests/fixtures/retrieval/` (15 queries of BM25, 90 graph cases over
  three configurations, corpus fusion, metrics); the Rust output equals it on every order and every number. Checked
  beyond the committed tests (not committed): 200 queries on a deterministic 800-note vault gave no difference
  from generation 1 in BM25 or graph results. Metrics on the fixture qrels, k=5: graph expansion recall 1.0, MRR 1.0, nDCG 1.0 (BM25 alone
  recall 0.5833, MRR 1.0, nDCG 0.6739). Benchmark (`cargo run --release -p laris-retrieval --example bench`, outside the test suite, report
  `reports/performance/retrieval.json`): 10 000 notes, 200 queries, BM25 P95 1.25 ms and graph expansion P95 1.28 ms
  against the 300 ms target; index build 0.21 s, search index 0.10 s; measured on the development workstation.
  Known differences from generation 1: `tokens` lower-cases with Rust's Unicode tables (Python's differ for a few
  special letters); `source_title` reproduces pathlib's stem rule for POSIX separators only. The dense channel is an
  interface: nothing embeds yet (the model block, T144). `cargo fmt --check`, `clippy -D warnings`, `cargo test`,
  `cargo deny check`, `xtask guard`, `xtask scan` and `xtask schema --check` pass.

### T146 — Policy gateway, integrity lock, leak guard
- Requirements: SR-S4
- Depends: T141
- Deliverables:
  - Composition from `.laris/`, integrity lock compatible with `integrity.lock`, leak guard, private reasoning,
    `/workflows` and `/help`
- Validation:
  - Confidentiality suite; changed policy stops the server; no reasoning in chat bodies
- Status: done
- Note: Closed 2026-11-18, before T144. `Depends` was T144 and is now T141: the gateway is a `Backend` that wraps
  another `Backend`, so it needs the T141 seam and not the P2 client, and its validation ran against a scripted
  model; T144 puts the P2 client behind it and repeats the "no reasoning in chat bodies" check with the real model
  service (added to T144's validation)
  (`main` wraps `NoBackend` for now, so a running server still answers 502 until T144). No new crate (`regex`,
  already vendored for `laris-policy`, added to `laris-server`). New module `laris-server::policy`: `integrity`
  (reads every protected file once into a `Snapshot`, hashes those bytes, compares with `.laris/integrity.lock`, and
  everything served is built from the same bytes, so a file changed after the check cannot reach the prompt; the
  protected set is generation 1's: `LARIS.md`, help, `prompts`, `rules`, `workflows`, `brain`, `vault`; symlinks and
  oversized trees are refused; `render_lock` reproduces the committed lock byte for byte, which a test asserts, so
  the Python harness and this one read each other's locks), `yaml` (a reader for the YAML subset the policy files
  use; no YAML crate is approved, so unsupported syntax is an error, never a guess; owner may later replace it with
  an approved crate), `compose` (manifest, modules, `LARIS.md` then `rules/*.md` inside `internal_policy`, the
  client's own layers before the rules, undeclared placeholder is an error, instruction files over the limit fail
  closed, client text is not re-expanded and a label cannot break its comment), `workflows` (the seven
  workflows; every file must load; phases and instructions stay on the server), `guard` (`SecretRedactor`:
  environment secrets by name marker, with `MASTER` and `DSN` added so the server's own secrets are covered, token
  shapes, own paths; `LeakDetector`: hashed 7-word shingles, two hits make a leak, plus a per-session HMAC canary;
  `StreamGuard`: 160-character hold-back, a leak ends the answer), `reasoning` (`ThinkSplitter` for inline tags cut
  anywhere, `reasoning_content` and `reasoning`/`thinking`/`thoughts` keys diverted, `ReasoningSink`,
  `MemoryReasoning` bounded ring), `gateway` (`Policy::load`, `PolicyGateway`: one system message from the server,
  a client `system` message dropped, tools narrowed to the workflow list with `update_plan` kept, summary kind has no
  tools, tool calls assembled and dropped if their arguments repeat internal text, reasoning recorded when the
  answer ends, fails or the client leaves) and `routes` (`GET /v1/laris/workflows`, `GET /v1/laris/help`, `GET
  /v1/admin/reasoning` with `reasoning.read`). `main` loads the policy before it listens and exits 1 if it differs
  from the lock; `laris-server policy verify|lock` checks and refreshes the lock (the owner runs `lock` after
  approving a policy change). Settings: `LARIS_SERVER__POLICY_ROOT` (required), `ASSISTANT_NAME`, `REPLY_LANGUAGE`
  (default English), `THINK_TAGS`, `REASONING_KEEP`, the prompt limits and the guard numbers, each with its
  generation-1 default. Tests: `tests/policy.rs` 28 (lock identity with generation 1; changed, added, missing, broken
  lock and link; the owner's relock; composition; the gateway over a scripted model; the confidentiality suite of 336
  attacks (verbatim, upper-case, spaced, fenced, inside and after `<think>`, delivered in random 1 to 40 character
  pieces, from every confidential source) in which every attack was blocked and no run of 8 words of internal text
  reached the client; with leak detection switched off the suite fails, checked once by hand), 7 unit tests in
  `yaml`, `reasoning`, `integrity` and `gateway`. `cargo fmt --check`, `clippy -D warnings`, `cargo test` (511 pass,
  no PostgreSQL in this run), `cargo deny check`, `xtask guard`, `xtask scan` and `xtask schema --check` pass.
  Follow-up, same day (branch `feature/T146-limits`): (1) [superseded by the Claude Code style skills described further down] skills are chosen by context and never listed in the
  prompt: `policy::skills` reads `.laris/skills/*/SKILL.md` (front matter name and description), and per turn picks
  one skill from the user's message, task line and workflow request: a `/name` the user typed wins, otherwise BM25
  over name (x3) and description, chosen when the score reaches `SKILL_MIN_SCORE` (5.0) and beats the runner-up by
  `SKILL_MARGIN` (1.2); otherwise none. Only the chosen skill's text enters the prompt, as `<skill ...
  authority="low">` after the workflow's place and below the policy; its name goes to the client in a `laris`
  event (`skills`) before the text; a summary never gets one. Calibrated on 16 skills and 17 requests (all ten
  fitting requests chosen, the five unrelated ones none, one two-way tie none); `SKILL_SELECTION`,
  `SKILL_MAX_CHARS` (12000) too. A broken skill is skipped and named, not fatal; skills stay outside the lock, as in
  generation 1. (2) Reasoning is stored in PostgreSQL with the key id: `Backend::chat_for(request, caller)` (default
  calls `chat`), `PgReasoning` writes the generation-1 `traces` row (key, session, model, prompt hash, reasoning; no
  answer text; best effort, failures counted), `/v1/admin/reasoning` reads it back, `main` uses it; the in-memory
  ring stays for tests. `LARIS_SERVER__REASONING_KEEP` is gone. (3) The guard sees through disguises: invisible
  characters dropped, Cyrillic, Greek and full-width look-alikes folded, letters spread out by spaces or dots
  joined, and the canary compared on letters and digits only; tests stop each, and fail with the view switched off.
  (4) One answer id on every event (the gateway's own). (5) The PostgreSQL tests were run: throwaway
  `postgres:16` container on 127.0.0.1:55432 (not the trial server's), 522 tests pass including the T142 and T143
  ones, plus the new PostgreSQL reasoning test. 11 more tests in `tests/policy.rs`.
  Limits that remain: the guard is a rule over text. It stops copies and disguised copies of the internal text; a
  paraphrase, a translation or an encoding such as base64 is not stopped, so the limit is "no run of 8 words", not
  "no information". Skill matching is by words: a request in Vietnamese reaches a skill only by name until the
  descriptions carry Vietnamese terms (a change to the skills, the owner's call); a skill's `references/` files are
  not sent. A secret spelled out letter by letter is not redacted (only internal text is checked that way). The
  brain consult, the brain tools, the `LarisMeta` evidence list and the brain texts in the guard are T147. Guard
  messages are English constants by design (default English); `strings.yaml` is read by nothing on the server.
  Independence from generation 1 (same day, branch `feature/T146-independent-policy`, owner decision in the ADR-021
  addendum): `.laris/` was rewritten and `LARIS.md`, `prompts/manifest.yaml`, the Vietnamese runtime strings, the
  YAML workflows, `help/how-to-use.md` and `integrity.lock` were removed. New layout: `policy.toml` (sections, order,
  variables, optional and confidential sections), `prompts/*.md` (12 sections), `rules/*.md` (8 files, rule ids
  `PREC`, `CONF`, `UNT`, `EVD`, `TOOL`, `OUT`, `MEM`, `LIM`), `workflows/*.toml` (the same seven ideas, written
  again, limited to tools that exist: `Read`, `Grep`, `Glob`, `Write`, `update_plan`; T148 adds the corpus tools),
  `help.md`, `integrity.toml` (TOML, covers `policy.toml`, `help.md`, `prompts`, `rules`, `workflows`). The YAML
  reader is deleted. Crate approved by the owner: `toml` 0.9 with `toml_datetime`, `toml_parser`, `serde_spanned`,
  `winnow` (`deny.toml` and `THIRD_PARTY.md` updated). The policy text is new and the owner approved it on
  2026-11-18 (the lock was written after that approval).
  Skills work as in Claude Code (owner decision 2026-11-18, replacing the BM25 selector of the first follow-up):
  `.laris/skills/<name>/SKILL.md` with a `name` and `description` front matter and optional `references/*.md`;
  the 16 existing skill folders load unchanged. The prompt lists only `name: description` (each cut to 260
  characters, inside the 8000-character index budget); the server offers the tool `use_system_skill` and the model
  loads a skill, or one of its own reference files, when the context calls for it. The gateway answers that call
  itself and runs the next model step inside the same stream: one answer id, usage summed over the steps and sent
  once, reasoning of every step kept for the operator, calls for the client win over skill calls, at most
  `SKILL_MAX_LOADS` (3) loads and `max_loads + 2` model calls, a reference must be one the skill lists (no path),
  a client cannot offer a tool with that name, and a workflow that does not list the tool gets no skills. A user
  who starts a message with `/name` loads that skill before the first step. Skill text is tagged low authority.
  Settings `LARIS_SERVER__SKILLS`, `SKILL_MAX_CHARS`, `SKILL_MAX_LOADS`. The skills stay outside the lock. The
  skill folders are the owner's existing content (Claude Code format); whether to rewrite them is the owner's call.
  `.laris/skills`, `.laris/brain` and `.laris/vault` still hold generation-1 content, unread by the server and
  outside the lock; T215 and T147 deal with them. 519 tests pass with PostgreSQL (one `laris-policy` hook test,
  `control_characters_cannot_reach_the_terminal`, failed once under load and passed in isolation and on the
  previous commit: a flaky test of an earlier task, not investigated).

### T215 — Remove generation-1 coupling
- Requirements: SR-S3, SR-L2, SR-L3, SR-H8
- Depends: T146
- Deliverables:
  - Remove what ties generation 2 to generation 1 and fix the spec to match: the generation-1 migrations and dump
    fixtures of `laris-server` (T142), the generation-1 key digest forms (T143), the generation-1 parity fixtures and
    `generate.py` of `laris-retrieval` (T145), the generation-1 P1/P2 fixtures and wording in `laris-protocol` (T124),
    the legacy flat `settings.json` conversion in `laris-config` (T125), and
    in `laris-vault`, `.laris/skills`, `.laris/brain` and `.laris/vault` (generation-1 content, rewritten with T147
    and the skills task), the Python tests that read the old `.laris/` files, and every requirement in `spec.md`
    that cites generation 1
- Validation:
  - `grep -ri "generation" crates xtask` finds nothing that is not history; `cargo xtask spec` passes; all Rust
    checks pass
- Status: done
- Note: Closed 2026-11-18, branch `feature/T215-remove-generation-1`. `laris-server`: the three migrations became one
  `0001_initial.sql` (partitioned `usage` and `traces` from the start, `tokens_reserved` in `keys`); the dump fixtures
  `gen1_v2.sql`, `gen1_v3.sql`, `make_gen1_dumps.sh` and their two tests are gone; key digests are the keyed form
  only (plain SHA-256 acceptance and upgrade removed, one test removed); the dummy digest for an unknown key is
  keyed. `laris-config`: the flat `settings.json` conversion, its fixture and tests, and the test that compared the
  schema with generation 1's schema file are gone. `laris-retrieval`: `generate.py` removed, `cases.json` moved to
  `tests/fixtures/retrieval/expected.json` and `tests/golden.rs` renamed `recorded.rs`: they stay as recorded
  expectations (regression snapshots, measured evidence kept), no longer called parity. `laris-vault`: `generate.py`
  removed, `tests/golden/vault/*.json` stay as recorded expectations (index, writer, lint; the YAML cases are PyYAML's
  values). `laris-store`: the `generation1.sqlite` fixture and test replaced by a fresh-store test; migrations 1 and 2
  stay as the schema. `laris-protocol`: `scripts/record_protocol_fixtures.py` removed, the committed P1/P2 fixtures
  stay as the wire fixtures; wording fixed in every crate. Python: the `project` fixture and
  `test_brain_leak_adversarial.py` (read the old `.laris/`) removed, `test_layers.py` needles updated. `spec.md`,
  `plan` and these tasks no longer cite generation 1 as a requirement. 520 tests pass with PostgreSQL 16 (throwaway
  container), `fmt`, `clippy -D warnings`, `cargo deny check`, `cargo xtask spec`, `grep -ri generation crates xtask`
  empty. Left for later, by design: `.laris/brain` is rewritten in T147, `.laris/vault/schema.yaml` in T148, `.laris/skills` in the skills task (owner's
  content); T149 and T160/T161 and the closed-task notes above still tell the history; the Python source tree
  `src/laris` (generation 1 code) is untouched.

### T217 — Remove the Python model-free evaluation runner
- Requirements: SR-G4
- Depends: T140, T215
- Deliverables:
  - Remove the Python duplicate of the Rust model-free runner (T140): `research/evaluation/suite.py` (retrieval, citation,
    injection, vault, extraction, leak suites), the `suite` command of the model CLI, its test, and
    `shared/harness/guard.py` (`InjectionScanner`, `LeakDetector`), which only that runner used
- Validation:
  - No Python import of the removed modules; the Python tests of evaluation, architecture, cli, model, scholarly and
    vault pass; `cargo xtask spec` / `validate_spec.py` pass
- Status: done
- Note: Closed 2026-11-20, branch `feature/T217-model-block-independence`. Checked import by import before cutting:
  the other generation-1 duplicates stay because the model block still uses them: `shared/vault` and `shared/text`
  (used by `scholarly`, served as remote tools, D41), `shared/retrieval` and `shared/graph` (BM25 baseline and
  provenance gate of the language evaluation), `shared/config` (`schemas.py` is the training configuration;
  `runtime_schemas.py` holds `model_service` settings), `shared/harness/strings.py` and `shared/offline.py` (the
  placeholder backend), `src/cli` (entry point `laris-model` and the training scripts). `tests/documentation` was
  failing before this change (3 front-matter errors in `docs/deployment/RUNBOOK.md` and `docs/guide/DISTRIBUTION.md`);
  untouched here. Empty directories `shared/policy`, `shared/skills`, `laris/client`, `laris/server` hold only
  untracked `__pycache__`.

### T147 — System brain service
- Requirements: SR-S5
- Depends: T127, T145, T146
- Deliverables:
  - Progressive-disclosure operations over `.laris/brain/`, budgets, brain brief, evidence list in `LarisMeta`, brain tools
- Validation:
  - Each direction reaches its playbook within `brain.max_depth`; no write path
- Status: done
- Note: Closed 2026-11-18, branch `feature/T147-brain-service`. Module `laris_server::brain` (new dependency edge
  `laris-server` -> `laris-vault`, a workspace crate; no new third-party crate). `Brain::load(root, settings)` reads
  `.laris/brain/` with `VaultIndex`, finds `Brain Index`, parses its `route: name -> [[Hub]]` lines and the depth of
  every note through `children`; a missing folder, root or route is a named problem, never a crash. Operations:
  `brief(route)` (hub, its children and playbook, summaries only, cut to `brief_chars`), and the tool
  `use_system_brain` with `index`, `open <id>` (summary, parent, children, uses, feeds, sections; no body) and
  `read <id>` (text). An id is a title or `[[link]]`; a note deeper than `max_depth` or outside the tree, an unknown
  id and an unknown action are answered with an error text the model reads. Budgets per answer: `max_calls` (6),
  `turn_chars` (6000), one result `open_chars` (3500), `index_chars` (2500), `brief_chars` (2200); every result ends
  with `[brain budget: n of m calls, x of y characters]`. Settings: `LARIS_SERVER__BRAIN`, `BRAIN_ROOT_NOTE`,
  `BRAIN_MAX_DEPTH` (3), `BRAIN_SUMMARY_CHARS`, `BRAIN_INDEX_CHARS`, `BRAIN_OPEN_CHARS`, `BRAIN_TURN_CHARS`,
  `BRAIN_BRIEF_CHARS`, `BRAIN_MAX_CALLS`. Gateway: a workflow with a route gets `<brain route=... authority="low">`
  (the brief) after the skill's place in the prompt; the tool is offered when no workflow is active or the workflow
  lists `use_system_brain` (none of the seven workflows does yet: that is a policy change, the owner's); the server
  answers the call itself and runs the next step in the same stream, like skills; a client cannot offer a tool of
  that name; a brain call earns one more model step up to `max_calls`, skills keep their own limit. The evidence
  list is the cumulative `LarisMeta.brain` (titles of the notes in the brief and every note opened, in order), sent
  before the text and again whenever it grows; the client gate keeps the last one. The audit record
  (`ReasoningRecord.brain`, column `traces.brain`) holds the titles only, and is written even when there is no
  reasoning. The text of every note is added to the leak detector (all 65 fit the default budget; a test fails when
  it truncates), so a copy of 8 words in an answer or a tool call is stopped. No write path: `Brain` holds a
  `VaultIndex` and only reads; a test consults every note with `open` and `read` and compares the folder byte for
  byte, and another refuses file-writing calls in `brain.rs`. `Brain Index` got the routes `literature-map` and
  `kg-explore` so that each of the seven workflows has one (test). Tests: 13 in `tests/brain.rs` (tree within
  `max_depth`, `lint_hierarchy` clean, every route reaches hub and playbook in at most `max_depth` calls, budgets,
  depth refusal, no write, missing and broken brain, bad route, guard budget) and 9 in `tests/policy.rs` (brief,
  tool offer, client name clash, index-hub-playbook walk with evidence and audit, call limit, a workflow that lists
  the tool after a lock refresh, leak of brain text, environment settings). 541 tests pass with PostgreSQL 16,
  `fmt`, `clippy -D warnings`, `cargo deny check`. Not done, by design: the brain notes were not rewritten (they
  already follow the vault format and pass the hub-tree lint; rewriting their prose is the owner's call); adding
  `use_system_brain` to the workflows and any prompt text about the brain needs the owner's approval and
  `laris-server policy lock`; `/v1/admin/reasoning` does not show the brain ids yet (T150, traces). The model never
  saw this service: with the placeholder backend the tests prove mechanics only, and the foundation model is NOT
  QUALIFIED.

### T148 — Ingestion, project vault and the RAG rung
- Requirements: SR-H8, SR-H13, SR-S9
- Depends: T127, T132, T137, T145, T147
- Deliverables:
  - Ingestion (text, Markdown, PDF text layer), Source notes, vault lifecycle, memory, proposals inbox; RAG-rung scenario
    through server and system with the evidence gate
- Validation:
  - An existing vault is adopted byte for byte; every passage is exactly the characters its span points at; the
    scenario passes (a faithful answer clean, a made-up citation caught)
- Status: done
- Note: Closed 2026-11-19, branch `feature/T148-ingestion-vault-rag`. Code lives in `laris-tools` (the crate list of
  the spec is fixed): `ingest` (text, Markdown, PDF; `read_document`, `split`), `project_vault` (`ProjectVault`),
  `knowledge` (tools). New edges `laris-tools` -> `laris-vault`, `laris-retrieval`, `laris-store`; no third-party
  crate. PDF reader written in house (owner's choice): own zlib/DEFLATE, xref tables and streams, object streams,
  content-stream text operators, ToUnicode and WinAnsi; scans (no text layer, stage-3 OCR), encryption, other
  filters (LZW ...), fonts without a map and damaged files are refused with a message, never guessed; stream size and
  page count are limited, and every prefix and byte flip of a fixture runs without a panic. Passages: paragraphs
  merged up to `vault.passage_max_chars`, a heading starts one, long paragraphs cut at a sentence, a space, then
  anywhere; spans in characters and exact (test). Passages live in the `chunks` table (`Store::replace_document`,
  `chunks`); the same file again replaces them. `ProjectVault::init` refuses to nest a vault in another or around
  one, writes only `.obsidian/app.json` and `Index.md` in a new vault and nothing in an existing one; Source notes in
  `Sources/` (collision gets its own note), the managed block `laris` (a person's text around it survives, an edit
  inside it is a conflict), memory in `Memory/`, schema enforced, titles cannot leave the vault. Proposals go to
  `_inbox/` (`propose`, `accept`, `reject`); accept never overwrites. `_inbox` is invisible to `NoteSearch` and
  to link expansion. Tools: `ingest_document`, `search_corpus` (passages and notes fused with `fuse_ranked`; hits
  `{source, rank, text, ...}`, marked untrusted), `write_vault_note`, `propose_note`; registered only when the
  context has a vault and a database (`Context::with_knowledge`). Settings `vault.*` (note size, write rate,
  backup, ingest size, passage size, result count). `.laris/vault/schema.yaml` removed (identical to the built-in
  table; the test now checks that a file can replace it). RAG scenario `laris-server/tests/rag_rung.rs`: HTTP server
  with policy gateway and brain, `laris-model-client`, the core loop with the real tools, scripted model, evidence
  gate; 4 tests (faithful answer, made-up citation and unlisted note, injected document plus leak guard, empty
  corpus). 570 tests pass with PostgreSQL 16; `fmt`, `clippy -D warnings`, `cargo deny check`, `cargo xtask spec`,
  `guard`, `scan`, `schema --check`. Not done, by design: OCR (stage 3); the model proxy is T144, so the model is a
  script and only mechanics are proved; the foundation model is NOT QUALIFIED.

## Phase 33 — Server: Agent

### T149 — Scientific tools as remote tools
- Requirements: SR-M2, SR-S6
- Depends: T144
- Deliverables:
  - Inventory of the Python call sites; tool routes in the Python model service; server `/tools/{name}`; schemas
- Validation:
  - Fixture tests reproduce the extraction results through the server
- Status: done
- Note: Closed 2026-11-19. Inventory (also in the docstring of `laris.model.tools`): the generation-1 scientific and
  scholarly code is called from `research/evaluation/extraction.py` (`extract_spans`, the macro-F1 gate),
  `research/evaluation/suite.py` (`suite_citation`: bibliography, citations, `Doc`) and tests only; no Python
  client code calls it, so the client has nothing to port and the research tooling keeps its direct calls. Six tools,
  all deterministic and model-free, so they bypass the GPU queue: `extract_discourse`, `detect_limitations`,
  `normalize_quantities`, `parse_bibliography`, `analyse_citations`, `mine_literature` (`laris/model/tools.py`).
  P2 gains `GET /v1/tools` (function schemas, sorted) and `POST /v1/tools/{name}` (`{"arguments"}` in; `{"result"}` or
  `{"error": {"message", "type"}}` out; unknown name 404). A refusal is a tool result with a type
  (`invalid_arguments`, `input_too_large`, `rejected`, `tool_failed`), never an HTTP failure, and carries no input text
  (a library error is reported by class name only). Limits are configuration: `model_service.tool_max_chars`
  (2 000 000) and `tool_max_documents` (200). `laris-protocol` gets `scientific` (names, argument and result types,
  error codes) and `ToolList`; the schema export has the new `scientific` group (regenerated). Server: `GET
  /v1/laris/tools` and `POST /v1/laris/tools/{name}` behind the usual gate with the new permission `tools` (roles
  `user` and `admin`; not `readonly` or `auditor`). `Backend` gets `tools()` and `tool()` (default 502; the policy
  gateway passes them on); `ModelBackend` sends them to P2 through the same bounded places as chat and embed, passes
  on only `arguments`, answers 404 for a name the service does not serve, validates the name before it reaches an
  address (`[a-z0-9_]`, at most 64), refuses an answer with both or neither of `result` and `error`, and never shows
  the service's text or address (502/503). Character offsets are Unicode scalar values, not bytes; the protocol docs
  and a test say so. Fixtures are recorded from the real tool box by `scripts/record_scientific_fixtures.py`
  (`tests/fixtures/scientific`, round-tripped and schema-validated). Tests: 25 Python cases (`tests/unit/model/test_tools.py`, 11 tests:
  baseline macro-F1 0.9433 through the tool equals the library, gold citation edges, refusals, no leak, ASGI route) and
  9 Rust in `tests/tools.rs` (fake model: list, arguments only, refusal, 404 and bad names, failures, dead model,
  shared places) plus 3 in `laris-protocol`. With `LARIS_TEST_MODEL_PYTHON` set (run here with `.venv/bin/python`)
  the real service is driven through the server: the extraction fixtures score macro F1 0.9433, equal to
  `baseline.json` type by type, the recorded results come back, and the citation fixture gives exactly its gold edges;
  without it those two tests pass without proving anything. Not done, by design: the client's `RemoteTools` over this
  route (client programme), metering or rate limits for tool calls (they spend no tokens; keys are still checked),
  per-tool permissions, a trace of the tool name (T150), the Agent rung (T151). The foundation model is NOT
  QUALIFIED; these tools use no model. `cargo fmt --check`, `clippy -D warnings`, `cargo test` (without PostgreSQL),
  `cargo deny check`, `xtask guard`, `xtask scan`, `xtask schema --check` and `xtask spec` pass.

### T150 — Traces and audit
- Requirements: SR-S7
- Depends: T142
- Deliverables:
  - Content-free trace per request; operator query; retention
- Validation:
  - Trace on success, error, disconnect; no message text in rows
- Status: done
- Note: Closed 2026-11-19. One row per request in the existing partitioned `traces` table (migration
  `0002_request_traces.sql` adds `kind`, `request_id`, `route`, `status`, `outcome`, `duration_ms`, `prompt_tokens`,
  `completion_tokens`; the SR-S4 reasoning rows keep `kind = 'reasoning'`, request rows are `'request'`, and the
  reasoning route still shows only reasoning). Retention is the existing T142 task (`LARIS_SERVER__TRACE_RETENTION_DAYS`,
  default 30), proved on request rows too. `laris_server::trace`: `TraceRecord` (request id, key id, route, status,
  outcome, duration, session id, model, tokens, tool names, brain titles, answer length: no field can hold text),
  `TraceDraft` (collects what a request learns; a tool name or brain title with characters outside plain letters,
  digits and `_-.:/` (brain titles also spaces), or past 64/120 characters, is dropped whole, never cut; at most 32 tools
  and 64 titles), `TraceSink`/`TraceStore`, `MemoryTraces`, and `PgTraces`: a bounded queue (1024) and one writer task,
  so a request never waits for the database and a flood loses rows (`dropped()`, `failures()`) instead of memory;
  `flush()` is called at shutdown. `RequestScope::finish` writes the trace together with the access record, so a
  success, an error before or after the stream starts (`midstream_error`, `stream_idle`) and a client that leaves
  (`client_gone`, 499 before an answer) all leave one row; `health` and unknown paths are not traced. The key id is set
  by the gate, so 401 (empty key) and 403 (the key that was refused) are traced. Tokens are what the key was charged
  (reported, else estimated) and for an open server what the model reported; model and brain titles come from the
  stream, tool names from the model's calls to client tools and from `/tools/{name}` only when the service served the
  name (an unknown name is 404 and leaves nothing). `GET /v1/admin/traces` (new permission `traces.read`, privileged;
  roles `admin` and `auditor`) filters by `key_id`, `route`, `outcome`, `since`, `until` and `limit` (1 to 500,
  default 50); an unknown parameter or a malformed value is 400. Tests (`tests/traces.rs`, 9): memory traces for
  success, failed request, failed stream, disconnect, tool naming, untraced routes and query validation; with
  PostgreSQL 16 the same through real keys, the whole `traces` table dumped as text and searched for the question, the
  answer, the tool arguments, a hostile tool name and the key text (none found), the operator permissions and filters,
  and the purge of an old request row. 196 `laris-server` tests pass with PostgreSQL 16; `fmt`, `clippy -D warnings`,
  `cargo deny check`, `xtask guard`, `scan`, `schema --check`. Not done, by design: tool names of the brain and skill
  calls the gateway answers itself (the brain titles are in the row; per-tool traces of local tools are the Agent rung,
  T151), per-call arguments or results (never kept), the target key of an admin action (the route and the acting key
  are), metrics export. The foundation model is NOT QUALIFIED; nothing here measures it.

### T151 — The Agent rung
- Requirements: SR-S9, SR-H4
- Depends: T133, T148, T149, T150
- Deliverables:
  - Agent-rung scenarios mixing local tools (files, shell in sandbox) and remote tools (brain, scientific) end to end
- Validation:
  - Scenarios pass; traces show tool names only
- Status: done
- Note: Closed 2026-11-19, branch `feature/T151-agent-rung`. Scenario suite `laris-server/tests/agent_rung.rs` (3 tests,
  Linux), in one process like the RAG rung: the core loop with the permission gate (`PolicyGate`, rules `allow Read`,
  `deny Write(secret/**)`, everything else asked), the real local tools with `Bash` inside the OS sandbox
  (`laris-sandbox`, bubblewrap or Landlock, helper built on demand), the HTTP server with the policy gateway and the
  system brain, `GET /v1/laris/tools` and `POST /v1/laris/tools/{name}`, `MemoryTraces`, and a scripted model. The
  registry holds the local tools and a test-side `RemoteTools` over the server's tool routes (the client's own
  `RemoteTools` is the client programme), so the loop treats both kinds alike. Scenario 1: the brain (index, then the
  Playbook, server side only), `Read`, `extract_discourse`, `normalize_quantities`, `Write report.md`, a `Write` into
  `secret/` (refused by the rule, never written), `Bash` (`wc`, output seen) and `Bash` that tries to write outside the
  project (the file does not exist afterwards), then the answer. Checked: the order of what ran; asks only for
  remote tools, writes and commands; remote results equal the recorded tool-box outputs and are marked untrusted; the
  model was offered local and remote schemas and saw the extraction; nothing of the brain reached the client; one
  trace row per request with the tool names of the model's calls (`Read`, `extract_discourse`, ... one per request),
  one `tools` row per remote call with its name, the brain titles on the first row, and a dump of every row holding
  none of the paper text, the report, the shell text, the denied text, file names, the question or the brain's text.
  Scenario 2: nothing approved, so nothing ran, no call reached the server and no `tools` row names a tool. Scenario 3:
  a refusal by the tool box is a typed, untrusted result and the loop ends with its answer. The remote answers are the
  outputs recorded by the real tool box (`tests/tools.rs` proves the real service reproduces them), not a live service.
  New dev-dependencies of `laris-server`: `laris-policy`, `laris-sandbox` (workspace crates only). 623 workspace tests
  pass (without PostgreSQL); `fmt`, `clippy -D warnings`, `cargo deny check`, `xtask guard`, `scan`, `schema --check`.
  Not done, by design: the report of the suite against the compose stack (T153/T154); the Agent rung with a qualified
  model; the client's `RemoteTools`. The backend is a script, so this proves mechanics only; the foundation model is
  NOT QUALIFIED.

## Phase 34 — Server: Agentic

### T152 — The Agentic rung
- Requirements: SR-S9, SR-H15
- Depends: T140, T151
- Deliverables:
  - Agentic suite through the stack: visible plan, resumable progress, bounded replanning, completion check, memory in
    the vault, bounded autonomy; report naming the backend
- Validation:
  - Suite passes; the report states that mechanics, not model capability, were shown
- Status: done
- Note: Closed 2026-11-19, branch `feature/T152-agentic-rung`. Scenario suite `laris-server/tests/agentic_rung.rs`
  (5 tests, Linux) over the same stack as the Agent rung: the harness moved to `tests/support/mod.rs` and is shared by
  `agent_rung.rs` (unchanged scenarios) and the new suite (`Options`: session id, agent limits, project vault, memory
  folder). Scenarios: (1) the model's plan is shown before the first tool, its steps move to done as local and remote
  tools run, an answer given while a step is open is sent back once with the step named, the goal ends complete, a
  `memory` note with provenance is written into the project vault (`write_vault_note`), and no trace row holds the
  plan text, the note, the report or the paper; (2) a model stream that breaks mid-goal ends the turn as
  `provider_error`, a new loop over the same store resumes the plan (`resumed`, shown to the model), does not run
  the finished `Read` again and completes; (3) replans are bounded (`max_replans` 2, the limit said once) while a
  tool box that refuses every call is called four times and the model reports the gap; (4) a goal the model will not
  finish is reported open with its open step; (5) autonomy: the step ceiling ends a planner that never stops
  (`max_steps`, exactly that many model calls), a refused approval and a denied path run and write nothing and reach
  no server, more calls in one step than `maxToolCallsPerStep` get a typed `too_many_calls` result. Repeating the same
  call is refused by the loop, so the replan scenario varies its arguments. `cargo xtask eval` has a `ladder` suite
  (`rag_rung`, `agent_rung`, `agentic_rung`; 12 tests) and its report now carries `backend` naming what stood in:
  a scripted model and recorded tool-box outputs in one process, mechanics only, no capability shown. Fixed on the way:
  the `golden` suite of the runner pointed at `laris-retrieval/tests/golden.rs`, removed in T215, so it had failed
  since then; it now runs `recorded` (baseline 41 -> 45). 628 workspace tests pass (without PostgreSQL); `fmt`,
  `clippy -D warnings`, `cargo deny check`, `xtask guard`, `scan`, `schema --check`, `xtask eval` (and the seeded 20
  percent regression fails). Not done, by design: the run against the compose stack (T153/T154), the Agentic rung
  with a qualified model, the client. The backend is a script, so this proves mechanics only; the foundation model is
  NOT QUALIFIED.

### T153 — Docker deployment
- Requirements: SR-S8
- Depends: T147, T150
- Deliverables:
  - Static non-root API image, model image, Caddyfile, `compose.yaml`, secrets, backup script, runbook
- Validation:
  - `docker compose config`; smoke test; no policy or weights in images; trial-server volumes (`caddy_data`, PostgreSQL)
    survive the upgrade (owner runs it)
- Status: done
- Note: Closed 2026-11-19, branch `feature/T153-docker-deployment`. Files in `docker/`: `compose.yaml` (project `laris`,
  volumes `caddy_data`, `caddy_config`, `pgdata` so the trial server's `laris_*` volumes are reused; only Caddy publishes
  ports; the internal network has no route out; read-only root file systems, dropped capabilities), `server.Dockerfile`
  (musl static binary on distroless `nonroot`, vendored offline build), `model.Dockerfile` (Python, uid 10001, code and
  `configs/` only), `Caddyfile` (TLS, SSE without buffering, authority endpoint for pinning, no `Authorization` in logs),
  `init-secrets.sh`, `backup.sh`, `restore.sh`, `verify-images.sh`, `smoke_test.sh`, and `.dockerignore` (no `.laris`,
  weights, data or secrets in the build context). Runbook: `docs/deployment/RUNBOOK.md`. Code: `laris-server` reads
  `LARIS_SERVER__DATABASE_URL_FILE` (Docker secret; a direct URL wins; errors never name the content) and has
  `laris-server probe HOST:PORT/PATH` for the container health check (the image has no shell); one new test. Generation 2
  uses the schema `laris2` of the same database, so generation 1's tables stay untouched. Measured: `docker compose
  config` valid; both images built; `verify-images.sh` finds no policy, weights or secrets and both run non-root;
  `smoke_test.sh` (separate project `laris-smoke`, own volumes, ports 28080/28443) passes: only Caddy publishes ports,
  health, first admin key (works only from the edge gateway, i.e. the machine itself), user key, a streamed chat answer
  from the placeholder backend, account, a trace without message text, policy lock. 629 workspace tests pass (without
  PostgreSQL); `fmt`, `clippy -D warnings`, `cargo deny check`, `xtask guard`, `scan`, `schema --check`. Not done, by
  design: the upgrade of the trial server (owner runs it; the old `laris-caddy-1` container was already stopped, the
  volumes were not touched), the ladder suites against the compose stack (T154 reports), GPU override. The backend is
  the placeholder, so this proves mechanics only; the foundation model is NOT QUALIFIED.

### T154 — Security suite and performance budgets
- Requirements: SR-G5, SR-H15
- Depends: T122, T152, T153
- Deliverables:
  - Security suite for every threat row in CI; budgets fixed from measurements
- Validation:
  - Suite and budgets pass
- Status: done
- Note: Closed 2026-11-19, branch `feature/T154-security-suite-budgets`. Security: `cargo xtask security` reads the 30
  threat rows of `docs/architecture/THREAT_MODEL.md` and `tests/security/suite.json` (exact test names per test id, plus
  commands), runs them and writes `reports/security/report.json`. It fails on a threat without an entry, an entry
  without a threat, a named test that does not exist or fails, a PostgreSQL test that was skipped (`not_run`; allowed only
  with `--without-postgres`), and a deferral to a task that is already done. Result: 27 passed, 1 partial (`SEC-SUP-01`:
  `cargo deny`, guard and scan run; release signing is T159), 2 deferred to programme 3 (`SEC-BRAIN-01` T164, `SEC-DATA-03`
  T168). New test file `crates/laris-server/tests/deployment.rs` (`SEC-DEP-01`, static half of `SEC-NET-01`: no policy,
  weights or secrets copied into an image, read-only mounts, one published port, secrets as files, non-root users, TLS
  at the gateway, no `Authorization` in its log). Seeded faults caught: a Caddyfile that logs keys, a Dockerfile that
  copies weights, a renamed test, no database. Performance: `cargo xtask bench` runs `laris-server --example
  server_bench` (HTTP health and chat stream, 32 parallel streams, the redactor on 64 KiB, the evidence gate on 40
  citations, peak memory) and the retrieval benchmark (10,000 notes), five runs each; a figure is the median; a budget is
  the worst run times 3, never below a floor per unit (2 ms, 1 s, 32 MB) and never above the specification target
  (`reports/performance/rust_budgets.json`, `rust_bench.json`). Measured on the development workstation: chat stream
  p95 0.08 ms, 32 parallel streams p95 9 ms, redactor 0.5 ms, evidence gate 0.03 ms, retrieval p95 1.2 ms, peak 9.6 MB.
  A seeded slowdown of 50 times fails. CI: job `security` with a throwaway PostgreSQL service; job `performance`
  (non-blocking until the owner has seen its figures on the runner). 644 workspace tests pass with PostgreSQL;
  `fmt`, `clippy -D warnings`, `cargo deny check`, `xtask guard`, `scan`, `schema --check`. One flaky test seen once:
  `laris-policy` `hooks::control_characters_cannot_reach_the_terminal` failed in a parallel workspace run (the shell's
  working folder had disappeared), passed alone six times and in the rerun; not changed here. Not done, by design: the
  suite against the compose stack (`docker/verify-images.sh`, `smoke_test.sh` need built images; the owner runs them),
  the macOS and Windows sandbox backends, the Agentic-rung suite against the compose stack, benchmarks of a model. The
  figures are the cost of the system around a scripted backend; the foundation model is NOT QUALIFIED.

## Phase 35 — Client (after the model is finished)

### T155 — Global home, settings and login
- Requirements: SR-C3, SR-C4
- Depends: T128, T129
- Deliverables:
  - `~/.laris` layout, settings schema, project-folder rules, packaged default server, login inside the interface
- Validation:
  - Fresh home; an existing home with foreign files unchanged; wrong key shows the form again; overrides work
- Status: done
- Note: Closed 2026-11-19 at the owner's explicit request, ahead of the plan order (the model is not finished: T118 is
  still pending). `Depends` no longer lists T118: nothing here needs the model, and the validator refuses a done task
  with an open dependency; restore the line if the owner wants the client held back until T118. `laris_config::home`:
  `LARIS_HOME` (absolute) or `~/.laris`; `Home::ensure` adds only what is missing (the folder, private on Unix;
  `commands/`, `skills/`, `projects/`; an empty `settings.json` created with `create_new`) and never rewrites, moves or
  deletes an entry, so a home that already holds foreign files (other YAML, cache folders, other project files) stays byte for byte as it was.
  `ProjectFolder`: a project's `./.laris/` holds only `LARIS.md`, `skills/`, `commands/`, `memory/`; `create_dir`
  refuses any other name, `stray()` lists what else is there, and none of it is read (a planted `settings.json` is
  ignored); the project root is the nearest folder with its own `.laris` (never the global home) or `.git`.
  `laris_cli`: `credentials` (apiKey and the server that accepted it, mode 0600 from creation, atomic, a loose file is
  tightened on read), `login` (`decide`, `LoginForm`, `sign_in`, `KeyVerifier`, `HttpVerifier` = `GET /v1/laris/account`
  through the P1 client with the pin and limits of `server`), `start` (home, settings, project), `account`
  (`laris login` reads the key from a pipe and refuses a terminal; `laris logout`; `laris status` as JSON, never the
  key). A key is saved only after the server accepts it; a refused key, an unreachable server and a malformed key leave
  the form open with the catalogue message (English by default, Vietnamese on `ui.language`) and write nothing; the
  environment key wins over the saved one; a saved key is used only for the server that accepted it (a key is never
  sent to a different server); the packaged address is the lowest layer, then `settings.json`, then `LARIS_*`.
  Catalogue group `login` (EN and VI). 23 new tests (7 in `laris-config/tests/home.rs`, 16 in
  `laris-cli/tests/login.rs`, among them the real HTTP path and the compiled binary against a local server); seeded
  faults caught: key saved when refused, saved key sent to any server, settings rewritten by `ensure`. 667 workspace
  tests pass; `fmt`, `clippy -D warnings`, `cargo deny check`. The flaky `laris-policy` `hooks` test
  (`control_characters_cannot_reach_the_terminal`, working folder gone) failed once more in a run right after a build and
  passed in the next five runs. Fixed afterwards (branch `fix/policy-test-temp-dir-collision`): four tests of
  `hooks.rs` shared the folder name `again`, and the test helper `temp_dir` emptied it, so a hook's shell lost its working
  folder; `temp_dir` now gives every call its own folder (eight full `laris-policy` runs, no failure). Not done, by design: the masked login form in the terminal interface
  (T157, T158; this task provides its state and checks), the settings panel, `laris -p` (T156), the packaged build that
  carries the server address (T159; here `LARIS_PACKAGED_DEFAULTS` and `defaults.json` beside the binary are tested).

### T156 — Headless mode
- Requirements: SR-C5
- Depends: T155
- Deliverables:
  - `laris -p` with stdin, output formats, resume, continue, flags, exit codes
- Validation:
  - Tests with a scripted model per format and exit code
- Status: done
- Note: Closed 2026-11-19, branch `feature/T156-headless-mode`, with T157 in the same session at the owner's request.
  `laris_cli::headless`: `args` (`-p/--print`, the request as words, `--output-format text|json|stream-json`,
  `--continue/-c`, `--resume/-r ID`, `--max-turns`, `--permission-mode`, `--allowedTools`, `--disallowedTools`; `--flag=value`
  and `--` accepted; rule lists split on commas and spaces outside parentheses), `run` (`read_request`: argument, then
  a blank line, then standard input, or either alone, 4 MiB cap, a terminal is never read; `engine`: settings'
  permissions plus the flags' rules, deny wins, a rule that does not parse is a usage error, `bypass` refused because no
  policy supplies `allow_bypass` yet; `open_session`; `execute`), `server` (`ServerModel`: the sync `Model` over the P1
  client on a small runtime, which closes the gap T131 left; `HttpRemote`: the server's remote tools over
  `GET /v1/laris/tools` and `POST /v1/laris/tools/{name}`), `real` (everything wired: key from `LARIS_API_KEY` or the saved
  one for that server only, pinned client, tools with checkpoints, memory folder and skills, sandbox when the machine
  has one, redactor that knows the key, injection shield, hooks, `PolicyGate` with `NoApprover`, `Prompted` layers).
  Output: `text` prints only the answer; `json` one `result` object (`status`, `isError`, `result`, `session`,
  `modelCalls`, `goalComplete`, `usage`, `errors`, `exitCode`); `stream-json` is `ready` then the core events of
  `laris-protocol` as JSON lines, written the moment they happen (`Driver::with_sink`, new in `laris-core`; a test reads
  standard output from inside a running tool). Nobody can answer an approval, so a call that needs one gets the typed
  `approval_denied`; the flags say beforehand what may run. Every run is a session in the project's store:
  `--continue` takes the latest, `--resume ID` a named one, and a session killed mid-turn finishes that turn first.
  Exit codes: 0 completed, 1 failed (model, timeout, loop), 2 usage, 3 not signed in (`login_required` event or
  `result`), 4 turn limit (`max_turns` is `agent.maxSteps`, 1 to 10), 5 no such session. Catalogue group `headless` (EN
  and VI). `ApiKey::expose` is new, for the redactor only. 20 new tests in `laris-cli/tests/headless.rs` (every format,
  every exit code, permissions, resume, the pipe, the real path against a local server, the compiled binary); seeded
  faults caught: events written only at the end, a disallow rule that allows. 687 workspace tests pass; `fmt`, `clippy
  -D warnings`, `cargo deny check`, `xtask guard`, `scan`, `schema --check`. Not done, by design: interrupting by signal
  (no signal crate is approved; the OS ends the process and `--resume` finishes the turn), the project vault tools (no vault is opened), the Python
  environment, a policy-supplied `bypass`, the run against a compose stack, and anything that needs a qualified model:
  the foundation model is NOT QUALIFIED.

### T157 — Terminal interface on a recorded core
- Requirements: SR-C1
- Depends: T124, T155
- Deliverables:
  - Banner, input box, streaming Markdown, status line, footer, driven by a recorded core
- Validation:
  - Render tests at 60 and 100 columns; chat and interrupt scenarios pass
- Status: done
- Note: Closed 2026-11-19, branch `feature/T157-terminal-interface`, after T156 in the same session. Built with no new
  crate: ratatui and crossterm are approved (T119) but not vendored, and the owner chose on 2026-11-19 to build the
  parts that do not touch the terminal first and vendor them with T158. `laris-tui`: `width` (columns with wide and
  combining characters, word wrap with hanging indents, column wrap, ellipsis), `style` (spans, lines, theme with a
  mono mode, `plain` and `ansi`), `markdown` (headings, paragraphs, lists, quotes, rules, tables as rows, fences with
  `highlight` for Python, Rust, JS/TS, shell, JSON, TOML; inline code, bold, italic, links; `render_open` returns the
  lines that are final and the paragraph that may still grow, and the tests prove a final line never changes as text
  streams in, at every cut of four documents and four widths), `input` (multi-line buffer, cursor, history with the
  unsent draft, backslash-Enter, cleaned paste), `app` (`App::update(Input) -> Vec<Command>`: Enter sends a user
  message or a `/command`, Esc interrupts a running turn, Ctrl+C clears the box, then twice leaves, Shift+Tab asks for
  the next mode, typing while the agent works sends and the core queues; core events become banner, conversation, tool
  blocks, plan, notices, status line), `view` (`App::layout(width)`: `committed` lines that are final and `live` lines
  that are redrawn, banner, `●` answers, `⎿` tool results, spinner, bordered growing input box with the cursor,
  status line that drops fields to fit, footer hints, the armed-exit prompt) and `replay` (a scenario of
  `laris-protocol` typed as keystrokes, commands checked against the step, events fed in, a screen kept per step).
  Everything from the core is stripped of control characters before it is drawn (an escape sequence in a tool result
  or a model answer cannot reach the terminal). A `ready` of another version stops the interface (the `mismatch`
  scenario). Catalogue group `ui` (EN and VI). `laris replay FILE [--width N] [--color] [--steps]` shows a recorded
  scenario through the interface for review (no server, no key). Tests: 27 in `laris-tui` (the chat and interrupt
  scenarios at 60 and 100 columns with text snapshots in `tests/snapshots/`, queued typing and slash commands, every one
  of the eleven scenarios within every width from 20 to 160, Ctrl+C and Esc, the exit prompt expiring, hostile
  output, themes, Vietnamese, the growing box, wide and combining characters, streaming stability, the input
  buffer) and 2 in `laris-cli` for the binary. Seeded faults caught: a paragraph committed before it ended, control
  characters left in drawn text. 716 workspace tests pass; `fmt`, `clippy -D warnings`, `cargo deny check`, `xtask
  guard`, `scan`, `schema --check`. Not done, by design: the raw-mode loop that reads the keyboard and prints to the
  screen (crossterm; T158), tool and diff blocks, approvals, the login form, history search, `@path` and completion,
  `# note`, `!command` (T158), the owner's screenshot review (T158), a settings panel; a resize reflows the live part
  only (lines already printed keep the width they were printed at). The interface is shown only against recorded
  scenarios; the foundation model is NOT QUALIFIED.

### T158 — Interface on the real core and commands
- Requirements: SR-C1, SR-C2
- Depends: T152, T157
- Deliverables:
  - Tool and diff blocks, approvals, login form, queued input, history search; slash and custom commands, `@path`,
    `!command`, `# note`; guide entries
- Validation:
  - All translated golden scenarios pass; owner screenshot review on Linux and Windows
- Status: done
- Note: CLOSED by the owner on 2026-11-20 ("duyệt T158") after the screenshot review the validation requires; Windows console output stays unverified by the agent. Work below is merged into `laris-v2`. Branch `feature/T158-interface-commands`. The owner approved vendoring on 2026-11-19 and chose
  the whole task in one session. Vendored `crossterm` 0.29 with its transitive crates (`convert_case`, `derive_more`,
  `signal-hook`, `signal-hook-mio`, `unicode-segmentation`, `winapi` and its import crates, `crossterm_winapi`,
  `document-features`, `litrs`, `rustc_version`, `semver`; `mio` and `signal-hook-registry` were already there) into
  `vendor/`, `deny.toml` and `THIRD_PARTY.md`; `ratatui` is NOT vendored because the T157 core draws its own lines and it
  would have no use (still approved in T119). `laris-tui`: `diff` (unified diff block, 24 rows then a count), approvals
  (`App::approval`: tool, arguments, reason, rule, diff, choices once, session, project, everywhere, no; keys arrows,
  Enter, `y`, `n`, Esc, digits; the answer is a `permission_response` and the diff and the answer stay in the
  conversation), the login form (`SignIn`: server, certificate fingerprint `y`/`n`, key masked as dots; the typed text is
  not in `Debug`, not in the chat box, and the field is emptied when sent; `Esc`/Ctrl+C leave), history search (Ctrl+R),
  completion (Tab asks the core with `complete`, one candidate is inserted, several open a menu), `/exit`, `/quit` and
  `/clear` local, other `/name args` sent as `command`, a message typed while a turn runs waits below the conversation
  marked `(queued)` until the core's `queued` status says it started, `term` (`key_of` for crossterm keys, `RawMode` with
  bracketed paste restored on drop and on panic, `Screen`: final lines are printed once into the scrollback, the live part
  is erased and redrawn, an unchanged frame writes nothing, a live part taller than the window shows its last rows). A bug
  of T157 found on the way: a tool call printed with `…` kept it forever in the scrollback when its result came later;
  a block that waits for its result (and the last plan) is now live, with everything after it. The replay types
  `complete`, `permission_response`, `login` (server, `y`, key) and `set_mode` steps, so all eleven golden scenarios replay
  without skipping a step (the T157 `skip_unsupported` is no longer used). `laris-cli`: `interactive` (`commands`: built-in
  list, custom commands from `~/.laris/commands` and `.laris/commands` with `description:`, `$ARGUMENTS`, `$1`..`$9`, links
  and files over 64 KiB ignored, a custom one never replaces a built-in; `files`: `@path` completion and attaching, only
  what `Scope::resolve` allows; `front`: the session side, a turn, `/help`, `/mode`, `/status`, `/rewind`, custom
  commands, `!command` through the Bash tool (shown as a tool block, kept for the next message), `# note` appended to
  `.laris/LARIS.md`, `@path`, completion, Shift+Tab; `worker`: the session on its own thread with the approver waiting for
  the person's answer over a channel, the interrupt flag, the queue counter; `control`: keys and events, sign-in and
  sign-out, checking a key is drawn as "checking" before the wait; `terminal`: the raw-mode loop). `laris` with no
  arguments is the interface (a terminal is required; `laris -p` stays for pipes). `laris_cli::headless::real::build` now
  builds the parts both modes share; `Driver::with_interrupt_flag` is new in `laris-core`. Guide: `docs/guide/CLIENT.md`
  (a test requires every built-in command and input form in it). Tests: 24 in `laris-cli/tests/interactive.rs` (real local
  tools, real gate, real store, scripted model, keys typed into the controller: a turn, the queue, an approval granted,
  refused, remembered and with a diff, `/help`, custom commands, `/mode`, `!`, `#`, `@`, `/rewind`, `/status`, sign-in with a
  wrong then a right key, `/logout`, a session that cannot start, links and huge files), 19 in `laris-tui/tests/interact.rs`,
  9 in `laris-tui/tests/term.rs` (the bytes of the screen are played into a small terminal emulator and what is left equals
  what the interface shows, after every event of all eleven scenarios at 60 and 100 columns, with and without colour),
  snapshots of six more scenarios in `tests/snapshots/`. Seeded faults caught: a stale approval answer taken for the new
  request, a tool block committed before its result, Esc not refusing an approval. 769 workspace tests pass (three runs);
  `fmt`, `clippy -D warnings`, `cargo deny check`, `xtask guard`, `scan`, `schema --check`. A flaky test of T157
  (`laris-cli/tests/replay.rs`: two tests shared one home folder and raced on `settings.json`) now has a home per call.
  Smoke test on a pseudo-terminal against an unreachable server: the form draws, the key is not echoed, "Checking the
  key…" shows before the wait, the reason is shown, Ctrl+C leaves with code 0. Not done, by design: the owner's screenshot
  review on Linux and on Windows (needs a real terminal; Windows output was not run, and the screen writes its own escape
  sequences, which the legacy Windows console may not accept: to be seen in that review); a model call is not interrupted (Esc ends the turn before its next step, as in T156);
  `--continue`/`--resume` for the interface (the session store holds the log; the conversation is not drawn again); a
  server address or certificate prompt in the form (the packaged or configured address is used; the protocol and the
  golden scenarios for it replay); `/workflow`; Shift+Enter shows as a new line only on terminals that report it (Alt+Enter,
  Ctrl+J and backslash-Enter always work); a chat against the compose stack. The foundation model is NOT QUALIFIED. Follow-up 2026-11-20 (owner request, branch `feature/T158b-slash-suggestions`): suggestions while typing, as in Claude Code. `/` as first word or an `@` word asks the core after every edit (ids `s<n>`, apart from the Tab ids), the answer opens the menu without a Tab, each character narrows it, no match or another word closes it silently; Enter chooses, Esc closes. `/name` candidates are names that start with the text, then names that contain it. Tests: `suggestions_follow_each_character_typed` and the menu test changed.

### T159 — Distribution
- Requirements: SR-C6
- Depends: T156
- Deliverables:
  - Release builds per platform, `install.sh`, `install.ps1`, checksums and signatures, npm wrapper, size report
- Validation:
  - One-command install on a clean machine per platform; tampered binary refused
- Status: done
- Note: CLOSED by the owner on 2026-11-20 ("duyệt T159") although the validation asks for a clean machine per platform and only Linux
  x86_64 with a local mirror was run; the macOS, Windows and aarch64 runs and `install.ps1` stay unverified and are recorded as accepted risk. Branch `feature/T159-distribution`. Signing: the owner chose `openssl` on
  2026-11-19 because `minisign` is not installed and no tool may be installed without approval; the signature is ECDSA
  P-256 over SHA-256 (not Ed25519, which Windows PowerShell cannot check), recorded in the ADR-021 addendum.
  `[profile.release]` (fat LTO, one codegen unit, stripped symbols); `laris --version`. `cargo xtask dist`: `keygen`,
  `package` (one member per archive: `laris-<target>.tar.gz`, `.zip` for Windows), `manifest` (`SHA256SUMS` and
  `size-report.md`), `sign` (key file from `LARIS_RELEASE_KEY`, never in Git), `verify`, `scripts` (renders
  `distribution/install.sh`, `install.ps1` and the npm wrapper with the https release address and the public key: the
  templates hold neither; the address is an argument or `LARIS_RELEASE_URL`); `sha2` added to xtask (already
  approved and vendored). `install.sh` (openssl, tar, curl or wget) and the npm wrapper (Node 18, no dependencies)
  check the signature of `SHA256SUMS`, then the archive's line, then that the archive holds only `laris`, and install
  atomically only after that; `install.ps1` does the same with .NET CNG. `.github/workflows/release-build` (manual,
  uploads artifacts only: `cross` for musl, native runners for macOS and Windows, then sign). Guide:
  `docs/guide/DISTRIBUTION.md`. Tests: 13 in `xtask/tests/dist.rs` (fake binary: good install and start; a changed
  archive, changed list with a stale signature, changed or foreign-key signature, unlisted archive, archive with
  extra files, plain-http or unrendered address; the npm wrapper installs, launches and refuses two tampering kinds;
  rendered files hold the key and no placeholder). Seeded faults caught: the signature check removed from
  `install.sh` (3 tests failed) and from the npm wrapper (1 failed). Real release build on Linux (gnu): 9.45 MiB
  binary, 4.42 MiB archive; installed from a local mirror with `install.sh` and the npm wrapper, and a changed archive
  was refused. Not done, by design: a run on a clean macOS, Windows or aarch64 machine (`install.ps1` has not been
  run at all, there is no PowerShell here); the musl, macOS and Windows builds (CI only, the workflow has not run);
  macOS notarisation and Windows Authenticode (no certificates); key rotation; `npm publish`. The foundation model is
  NOT QUALIFIED.

## Phase 36 — Acceptance and release 1.0.0

### T160 — Acceptance checklist
- Requirements: SR-G4
- Depends: T154, T158, T159
- Deliverables:
  - Acceptance checklist (behaviours, commands, data) against this ledger's specification alone; home, project
    databases, vaults and server database checked for loss across upgrades of generation 2
- Validation:
  - Checklist complete; no open regression
- Status: done
- Note: Done 2026-11-20 on the owner's order. Checklist, against this ledger alone: `cargo fmt --check`, `cargo clippy --workspace
  --all-targets -D warnings`, `cargo test --workspace` (813 passed, 0 failed, with `LARIS_TEST_PG_DSN` on the throwaway
  container `laris-test-pg`; the trial database was not touched), `cargo deny check`, `cargo xtask spec|guard|scan|schema
  --check` pass, `cargo xtask security` passes (30 threats: 27 passed, 1 partial, 2 deferred). Upgrade without loss is covered
  by the migration tests of `laris-store` (home and project databases, vault) and `laris-server` (`tests/storage.rs`: a fresh
  database gets every migration once, a newer one is refused). Not measured: the model (NOT QUALIFIED), Windows and macOS
  builds, a real GPU run. No open regression.

### T161 — Documentation and release 1.0.0
- Requirements: SR-G4
- Depends: T160
- Deliverables:
  - Guide, architecture documents, runbook, changelog; PR `laris-v2` into `main`; tag and release with authorisation
- Validation:
  - Release checklist recorded; `laris-v1` untouched
- Status: done
- Note: Done 2026-11-20 on the owner's explicit order, with a changed version: the release is **1.0.0** (tag `v1.0.0`), not
  3.0.0, because generation 2 stands alone. Release checklist: workspace version 1.0.0 (`laris --version` prints it);
  CHANGELOG rewritten as one 1.0.0 entry; the old tag `v2.1.0` and its GitHub release deleted locally and on the remote
  (the only tag and release); runbook free of generation-1 steps; `laris-v1` untouched; `laris-v2` merged into `main`.

## Phase 45 — One-command server and zero-setup client

### T236 — One-command server and zero-setup client (1.0.1)
- Requirements: SR-S8, SR-C1
- Depends: T235
- Deliverables:
  - `docker/laris.sh` (up, down, status, key) with a Tailscale certificate for the Caddy site; the client release built with its server address compiled in; release 1.0.1 (GitHub release and npm)
- Validation:
  - A local build with `LARIS_BUILD_DEFAULTS` reports the address in `laris status`; the release workflow succeeds; `npm view @ntdev204/laris` shows 1.0.1
- Status: in_progress
- Note: 2026-11-20 (owner: "1 lệnh để bật/tắt server, client chỉ nhập key", then "phát hành"). Script written and its `status` checked; `up`, `down` and `key` were not run by the agent. The release address is the tailnet name (`https://vthlab.tail3e814e.ts.net:38443`), reachable from the owner's tailnet only; `tailscale cert` needs `sudo tailscale set --operator=$USER` once. Version raised to 1.0.1 because npm cannot replace a published version.

## Phase 46 — Full-screen terminal interface

### T237 — Full-screen interface with the session history kept
- Requirements: SR-C1
- Depends: T236
- Deliverables:
  - The interactive client runs on the alternate screen like `vim`: a header, a conversation area that scrolls (keys and mouse wheel), the input box and the status line fixed at the bottom; on exit the terminal is restored. The conversation of a session is read back from the event log when it is resumed (`--resume`), so the history of a session is kept; no flicker (one synchronised frame, a slow spinner)
- Validation:
  - Terminal emulator tests of the full-screen layout, the scrolling and the restore on exit and on a panic; the existing T158 scenarios still pass; the owner tries it on Windows Terminal
- Status: pending
- Note: 2026-11-20 (owner: "giống vim, nhưng lịch sử hội thoại vẫn giữ theo session"). The flicker part is already done in T236's follow-up: `Screen::draw` writes one synchronised update (`CSI ?2026h/l`) per frame and the spinner advances every 120 ms and only while a turn runs (it ran at 25 frames a second). Not yet verified on Windows.

## Phase 47 — Request pipeline in the server

Owner's direction 2026-11-20 ("tích hợp toàn bộ vào hệ thống", plan and tasks only): a request goes client, then the server, which authenticates, applies policy, runs the Prefilter, lexical retrieval, the main brain and the harness, and only then asks the model; the answer returns through the evidence gate. This reopens the decision of 2026-11-13 to keep the engine on the client; T238 settles what moves.

### T238 — ADR-025: request pipeline in the server
- Requirements: SR-S4, SR-S5, SR-K1
- Depends: T236
- Deliverables:
  - An ADR that fixes the order of stages (auth, policy, Prefilter, retrieval, brain decider, model, evidence gate, answer assembly), what stays on the client (tool execution in the sandbox, files, approvals) and what moves to the server (the decision loop, the vault and brain, the model call), where the vault and the main brain live (per user or shared), what the protocol P1 carries (step events, evidence list), the failure modes (model down, vault empty) and the threat-model changes
- Validation:
  - The owner accepts the ADR; no pipeline code before it
- Status: pending

### T239 — Server pipeline core: Prefilter, retrieval and harness in the chat route
- Requirements: SR-S4, SR-M11
- Depends: T238
- Deliverables:
  - `PrefilterModel` and `HarnessModel` (T229, T232) wired into the server's chat route behind configuration; a Prefilter hit never reaches the model; retrieved passages come from the server's vault; every stage and its time is recorded in the audit row without message text
- Validation:
  - Server tests with a scripted model: a Prefilter hit, a grounded answer, a missing source (abstains), an injected passage (ignored); the capability ladder still passes
- Status: pending

### T240 — Server-side vault and main brain
- Requirements: SR-S5, SR-K3
- Depends: T238, T239
- Deliverables:
  - The server holds the main-brain vault and the write gate (T164) behind its own storage and roles; clients cannot write it except through the gate; ingestion and retraction are admin operations
- Validation:
  - Tests: a model-only claim is refused through the API, a retracted source downgrades its claims, access follows the roles
- Status: pending

### T241 — Brain decider in the server turn
- Requirements: SR-K5, SR-S4
- Depends: T239, T240
- Deliverables:
  - The rule decider (T167) behind the server's decision seam, choosing among answer, abstain, ask, retrieve and ask the advisor; the decision network stays off (not promoted, T171); every decision is logged with its rule
- Validation:
  - Scenario tests through the HTTP API: stop on budget, abstain on no evidence, answer from accepted claims without calling the model
- Status: pending

### T242 — Protocol P1 step events and client display
- Requirements: SR-S1, SR-C1
- Depends: T239
- Deliverables:
  - P1 gains step events (stage name, outcome, time) and the evidence list in the answer; the schema is regenerated and checked; the client shows the stages in the interface (for example "checking the knowledge base", "asking the model") and the sources of an answer
- Validation:
  - Schema check, contract tests, emulator tests of the display
- Status: pending

### T243 — End-to-end acceptance of the pipeline with Qwen3.5-9B
- Requirements: SR-S8, SR-K7
- Depends: T241, T242
- Deliverables:
  - The compose stack runs the full pipeline; the smoke test is extended (a covered question is answered without the model, an uncovered one abstains, a free question reaches the model); the cognitive evaluation (T172) is repeated through the server; runbook and threat model updated
- Validation:
  - Smoke test passes; the report states system measurements only and no model qualification; the owner reviews
- Status: pending

## Phase 48 — Client fixes found in use

### T244 — Terminal flicker and the emoji icon (release 1.0.2)
- Requirements: SR-C1
- Depends: T236
- Deliverables:
  - No flicker while typing or while a turn runs: one synchronised frame per redraw and a slower spinner that moves only while a turn runs; no spinner glyph that a terminal can draw as a colour emoji; a test for each; a release that carries them (1.0.2, GitHub release and npm)
- Validation:
  - Emulator tests pass; the owner sees no flicker and no purple-on-blue icon on Windows Terminal
- Status: in_progress
- Note: 2026-11-20 (owner reports on 1.0.1: the screen reloads constantly while typing and answering, and the icon changes between purple and purple-on-blue). Causes found in the code: the spinner advanced every 40 ms tick (25 redraws a second, each erasing and printing the live block), and the glyph U+2733 is drawn as a coloured emoji box on Windows. Fixed: `Screen::draw` writes one `CSI ?2026h ... ?2026l` update per frame; the spinner steps every 120 ms and only while running; U+2733 became U+273A, and a test lists emoji-capable characters that no frame may use. Committed on `main`, not pushed, not released, not tried on Windows; the causes are read from the code, not seen on the owner's terminal. Closes when 1.0.2 is released and the owner confirms.

