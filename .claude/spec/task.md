# LARIS — Task ledger: Obsidian brain and scholarly harness

Version 0.1.0 · 2026-11-11 · Implements [plan.md](plan.md) for [spec.md](spec.md).

Status values: `pending`, `in_progress`, `done`, `blocked` (waiting for the owner). A task is `done`
only when every deliverable and validation item holds and a completion note is written. After each
task run `python scripts/validate_spec.py`. Do not start a task before its dependencies are `done`
(a blocked dependency means design may proceed but nothing merges).

## Phase 0 — Foundations and decisions

### T01 — Adopt the ledger and its validator
- Requirements: SR-H5
- Depends: none
- Deliverables:
  - `scripts/validate_spec.py` (ids, references, dependency order, coverage)
  - `tests/contract/test_spec_ledger.py`
  - Makefile target `spec` inside `check-no-training`
  - `AGENTS.md` points to `.claude/spec/`
- Validation:
  - Validator passes on the three files and fails on a seeded inconsistency
  - CI runs it
- Status: done
- Note: Completed with this ledger: validator, contract test, Makefile target and AGENTS.md pointer added.

### T02 — Vault format specification and golden fixture vault
- Requirements: SR-V1, SR-V5
- Depends: T01
- Deliverables:
  - `docs/specifications/OBSIDIAN_VAULT_FORMAT.md` citing the official rules in spec section 2
  - `tests/fixtures/vault/` covering every link form, properties, tags, embeds, code blocks, unresolved and ambiguous links, forbidden characters
  - List of unverified behaviours resolved or explicitly avoided (dot folders, `.obsidian/*.json` keys, JSON Canvas)
- Validation:
  - `validate_docs` passes
  - Fixture reviewed against the official pages
- Status: done
- Note: Delivered docs/specifications/OBSIDIAN_VAULT_FORMAT.md, golden fixture tests/fixtures/vault/ with tests/unit/vault/test_fixture.py; unverified behaviours (dot folders, .obsidian keys beyond app.json, JSON Canvas, licence) are listed and avoided.

### T03 — Threat model for the brain and the vault
- Requirements: SR-H1, SR-B1, SR-B3
- Depends: T01
- Deliverables:
  - `docs/architecture/BRAIN_THREAT_MODEL.md`: assets, attackers, threats, controls, tests per threat
  - Out-of-scope list (local administrator)
- Validation:
  - Every threat maps to a control and a task or test id
  - `validate_docs` passes
- Status: done
- Note: docs/architecture/BRAIN_THREAT_MODEL.md maps threats TH1 to TH12 to controls and tests; local administrator is out of scope; extraction suite is left to T33.

### T04 — ADR: Obsidian-compatible brain and owner decisions D1 to D9
- Requirements: SR-V1, SR-B1
- Depends: T02, T03
- Deliverables:
  - `docs/adr/ADR-014-obsidian-compatible-brain.md`
  - Owner confirmation or change of D1 to D9 recorded in the ADR
- Validation:
  - ADR validated by `validate_docs`
  - Owner decision recorded before Phase 1 code merges
- Status: done
- Note: ADR-014 records D1 to D9; the owner instructed the work to proceed on the defaults on 2026-11-11, each remains changeable by a later ADR.

### T40 — Local data plane and authenticated server
- Requirements: SR-H7
- Depends: T01
- Deliverables:
  - ADR-015; `serving.auth.KeyRing` (SHA-256 digests, env and file sources); `laris model serve` refuses to start without keys (`serving.require_auth`); `AuthError`, `check_key`, key check at `laris login` and at chat start
  - Contract tests: serving imports no tool/vault/learning/application code, writes no files, health reveals nothing
- Validation:
  - Wrong, missing and empty keys get 401; each configured key is accepted
  - A rejected key is not saved and stops the session with a clear message
- Status: done
- Note: Delivered with tests/unit/cli/test_server_auth.py. Not done: rate limiting of failed attempts, key rotation without restart, TLS (use a reverse proxy).

## Phase 1 — Vault core library

### T05 — Note parser: links, embeds, tags, properties, headings, blocks
- Requirements: SR-V1, SR-V2
- Depends: T02
- Deliverables:
  - `src/vault/parser.py` handling wikilinks (note, path, heading, block, alias), Markdown links, embeds, tags, YAML properties, headings, block ids; code blocks and inline code excluded
  - Property rules: unique names, no nesting, quoted links
- Validation:
  - Golden fixture parses to expected output
  - Property-based test: parser never raises on random text
  - `ruff`, `mypy`, unit tests pass
- Status: in_progress
- Note: Parser is src/vault/notes.py: wikilinks, aliases, headings, embeds, Markdown links, tags, properties, code and comment exclusion. Missing: block-id extraction as its own field, property-based never-raises test.

### T06 — Vault model and incremental index
- Requirements: SR-V2, SR-H4
- Depends: T05
- Deliverables:
  - `src/vault/index.py`: scan, hashes, link resolution (path, shortest unique name, ambiguity flag), backlinks, orphans, unresolved, disposable cache under `.laris/cache/`
  - Deterministic serialisation
- Validation:
  - Two runs are byte-identical
  - Editing one note changes only its entries
  - Deleting the cache loses nothing
- Status: in_progress
- Note: src/vault/index.py: shortest-path resolution, ambiguity, backlinks, orphans, incremental reuse. Missing: on-disk disposable cache and byte-identical serialisation.

### T07 — Safe writer with managed blocks and conflict detection
- Requirements: SR-V4, SR-V5, SR-H1
- Depends: T06
- Deliverables:
  - `src/vault/writer.py`: atomic write, path confinement to the vault, symlink and junction refusal, filename sanitisation and collision suffixes, size and rate limits, secret redaction, injection scan, managed-block markers, hash-based user-edit detection, backup before rewrite
- Validation:
  - Crash during write leaves the old file
  - User text outside managed blocks survives 100 rewrites (property test)
  - Traversal, symlink and forbidden-character tests pass
- Status: in_progress
- Note: src/vault/writer.py: atomic write, path confinement, symlink escape refusal, managed blocks with hash conflict detection, size cap, injection scan hook. Missing: backup before rewrite, rate limits, crash and 100-rewrite property tests.

### T08 — Note schema registry
- Requirements: SR-V5
- Depends: T06
- Deliverables:
  - `vault` section in `LarisConfig` and `configs/default.yaml`; `.laris/vault/schema.yaml` (types, required properties, relation properties, filename rules) under the integrity lock
  - Schema validator
- Validation:
  - Failing note is reported with a code
  - Defaults equal the schema defaults (existing test pattern)
- Status: in_progress
- Note: VaultConfig and BrainConfig exist in LarisConfig and configs/default.yaml. Missing: .laris/vault/schema.yaml and the schema validator.

### T09 — Vault graph analytics
- Requirements: SR-V2, SR-A5, SR-B6
- Depends: T06
- Deliverables:
  - `src/vault/graph.py`: degree, PageRank, components, shortest path, local graph to depth N, neighbours by relation
- Validation:
  - Known small graphs reproduce expected values
  - Deterministic ordering
- Status: pending

### T10 — Vault lint command
- Requirements: SR-V2, SR-H1, SR-H3, SR-B6
- Depends: T07, T08
- Deliverables:
  - `laris vault check`: broken links, orphans, duplicate aliases, schema failures, forbidden characters, secrets, oversize notes; exit codes
  - Structural lint for hierarchy: levels, single parent, max depth, max children per hub, summaries, no orphans (config `brain.*`)
- Validation:
  - Fixture with seeded defects is detected exactly
  - Clean fixture passes
- Status: in_progress
- Note: Format lint and hierarchy lint (levels, single parent, depth, width, summaries, orphans, relations) plus laris vault check and laris brain check. Missing: secrets, oversize and duplicate-alias checks.

## Phase 2 — Project vault lifecycle

### T11 — Project vault bootstrap
- Requirements: SR-V3
- Depends: T07, T08, T04
- Deliverables:
  - `laris vault init` and automatic bootstrap on first ingest or session
  - Folders, `_templates`, `00 Index.md`, minimal `.obsidian/` (wikilinks on, graph colour groups per type, core plugins), `.gitignore` entries, vault-in-vault refusal, adoption of an existing vault
- Validation:
  - Init twice changes nothing
  - Adopting a user vault rewrites no note
  - Opening in Obsidian shows a connected graph (manual check recorded)
- Status: in_progress
- Note: ProjectVault.ensure and laris vault init; bootstrap on first ingest or answered turn; .obsidian/app.json and .gitignore. Missing: _templates, vault-in-vault refusal, adoption of an existing vault.

### T12 — Source notes on ingest
- Requirements: SR-V4, SR-A1
- Depends: T11
- Deliverables:
  - Hook in `SearchService.ingest`: one Source note per document (metadata, hash, passage count, links to concepts), updated on re-ingest inside managed blocks
- Validation:
  - Re-ingest updates, never duplicates
  - Notes lint clean
  - Hook failure never fails ingestion
- Status: in_progress
- Note: Ingest hook writes Source and Concept notes and, by owner instruction (2026-11-11), a Knowledge note by domain under vault/Knowledge/ (src/vault/knowledge.py); skills are no longer generated on ingestion (learning.skill_on_ingest false). Missing: content hash and passage-level metadata.

### T13 — Session and question-answer notes
- Requirements: SR-V4, SR-A2
- Depends: T11, T12
- Deliverables:
  - After each completed turn: Session daily-note entry, Question and Answer notes linking every cited Source; opt-out in config and settings
- Validation:
  - Every answer note links all cited sources
  - Turns blocked by guards write nothing
  - Secrets never reach notes
- Status: in_progress
- Note: Verified turns write Question and Session notes linked to cited sources; blocked or failed turns write nothing; secrets redacted. Missing: per-user opt-out in settings.

### T14 — Unified memory in the vault
- Requirements: SR-V6
- Depends: T11
- Deliverables:
  - `save_memory`, compaction summaries and prompt memory section use `vault/Memory/`
  - One-time reversible migration of `.laris/memory`
- Validation:
  - Migration idempotent and lossless
  - Prompt memory stays within its size limit
  - Old API unchanged
- Status: pending

### T15 — Concept and claim notes from extraction
- Requirements: SR-V4, SR-A6
- Depends: T12
- Deliverables:
  - Extraction results become Concept, Method, Dataset, Metric, Claim and Limitation notes with character-span provenance and links to Sources
- Validation:
  - Spans match source text
  - Duplicate concepts merge by stable id and alias
- Status: in_progress
- Note: Knowledge notes carry key terms, claims, methods, datasets and metrics from the extractor, linked to the Source note and listed beside the domain hub; save_knowledge adds taught knowledge. Missing: per-entity Concept/Claim notes with character-span provenance and stable-id merging.

### T16 — User-edit safety, sync and repair
- Requirements: SR-V4
- Depends: T07, T13
- Deliverables:
  - `laris vault sync` and `laris vault repair`; conflict policy documented; backups restorable
- Validation:
  - Interleaved user and system edits never lose user text
  - Repair is idempotent
- Status: pending

### T17 — Vault user experience
- Requirements: SR-H3
- Depends: T10, T13
- Deliverables:
  - `laris vault` commands, chat `/vault`, web Vault panel (search, open note, graph export), string catalogue entries, guide update and coverage test
- Validation:
  - Guide-coverage test lists every new command
  - Web script passes `node --check`
- Status: in_progress
- Note: laris vault and laris brain commands, guide section 11 and coverage test. Missing: chat /vault and web panel.

## Phase 3 — System brain

### T18 — System brain loader and protected access
- Requirements: SR-B1
- Depends: T06, T04
- Deliverables:
  - Brain path from configuration or packaged data; deny-read globs; integrity lock covers brain notes; read-only enforcement; no model-controlled paths
- Validation:
  - `read_file`, `list_files`, `ingest_path`, `save_skill` and path tricks are denied
  - Tampered brain note stops the session
- Status: in_progress
- Note: Brain folder is in integrity.lock, denied to file tools (folder and contents, symlink and dot-dot tricks tested), read-only class. Waits on T06 and T04 deps to be done before closing.

### T19 — Brain tools
- Requirements: SR-B1, SR-B3, SR-B6
- Depends: T18
- Deliverables:
  - Tools `brain_search`, `brain_read`, `brain_neighbors`: excerpts marked `internal`, size budgets, redaction, ids in audit only
  - `brain_open_root`, `brain_open(id)` returns summary plus child ids; full text only on request; per-turn budget and no repeat of opened ids
- Validation:
  - Tools respect budgets
  - No path or absolute location in results
  - Workflow allow-lists can include or exclude them
- Status: in_progress
- Note: brain_open_root, brain_route, brain_open, brain_neighbors, brain_search, brain_consult with budgets, internal marking and no paths; workflow allow-lists include or exclude them. Closes after T18.

### T20 — Leak guard for brain content
- Requirements: SR-B3
- Depends: T19
- Deliverables:
  - Brain notes feed the shingle detector with a memory budget; egress rule extended to brain content
- Validation:
  - Adversarial extraction cases produce no shingles above the limit
  - Detector memory stays under budget
- Status: in_progress
- Note: Brain text feeds the leak detector (shingles) and audit logs store titles only. Missing: adversarial extraction suite and memory budget measurement (T33).

### T21 — Brain content v1: ontology, vocabulary, concept maps
- Requirements: SR-B2, SR-B6
- Depends: T18, T08
- Deliverables:
  - Owner-reviewed notes: ontology, relation vocabulary, glossary, concept maps for the six directions, tool/skill/workflow map, rubrics
  - Brain authored as a hub tree: root with routing table, domain hubs, topic hubs, leaves; every note carries parent, children, summary, requires, typed related
- Validation:
  - `laris vault check` passes on the brain
  - No-secrets scan passes
  - Owner review recorded
- Status: blocked
- Note: Draft v1 shipped: 65 notes, ten domain hubs, six playbooks, passes laris brain check. Owner review of the content is still required and not recorded.

### T22 — Reasoning playbooks and workflow links
- Requirements: SR-B2, SR-B4, SR-B6
- Depends: T21, T19
- Deliverables:
  - One playbook per direction (decide, verify, stop); workflows reference playbooks; `.laris/workflows` updated under the lock
- Validation:
  - `laris workflows check` passes
  - Each playbook is reachable from the brain index
- Status: in_progress
- Note: Six playbooks (Decide, Verify, Stop) reachable from the root in two steps; workflows routed through the root table and allowed brain tools (workflows 1.1.0). Closes after owner review of T21.

### T23 — Proposals inbox and owner review
- Requirements: SR-B5
- Depends: T13, T18
- Deliverables:
  - Runtime learnings written to `vault/_inbox/`; `laris brain propose|review|accept|reject`; accepted items enter the project vault, never the system brain
- Validation:
  - No runtime write path to the system brain (test)
  - Proposals are excluded from retrieval until accepted
- Status: in_progress
- Note: ProjectVault.propose writes to _inbox/ outside retrieval. Missing: laris brain propose|review|accept|reject.

## Phase 4 — Brain-assisted reasoning

### T24 — Graph-aware retrieval
- Requirements: SR-A4, SR-B4, SR-B6
- Depends: T09, T19, T12
- Deliverables:
  - BM25 over notes, link-neighbourhood expansion, deterministic fusion with corpus search, provenance in results
  - Navigation-first retrieval: route by task type through hubs, expand along typed links; search only as fallback; token use reported
- Validation:
  - Deterministic ordering
  - Recall@k, MRR and nDCG computed on the fixture against BM25 alone
- Status: pending

### T25 — Loop integration of the consult step
- Requirements: SR-B4, SR-B6
- Depends: T24, T20
- Deliverables:
  - Prompt module and loop step that consults the brain before answering; config toggle; audit records note ids; short visible trace of titles
  - Consult step navigates root to leaf within budget and records the path of ids
- Validation:
  - Trace never contains internal text
  - Disabled toggle restores previous behaviour
  - Prompt version bumped and lock refreshed
- Status: in_progress
- Note: Consult step in the loop with config toggle (brain.consult), audit of titles, hidden brief and visible title trace; prompt 1.2.0 and lock refreshed. Closes after T24.

### T26 — Reasoning trace and explainable answers
- Requirements: SR-B4, SR-A2
- Depends: T25, T13
- Deliverables:
  - Answer notes cite vault notes and sources; trace stored with the answer note
- Validation:
  - Every cited note exists
  - Verifier checks still pass
- Status: pending

## Phase 5 — Scholarly analytics

### T27 — Bibliographic metadata extraction
- Requirements: SR-A1, SR-A3
- Depends: T12
- Deliverables:
  - Title, authors, year, DOI and arXiv id from text and PDF metadata; stored in Source properties
- Validation:
  - Fixture accuracy reported
  - Missing values stay empty, never guessed
- Status: pending

### T28 — Literature mining analytics
- Requirements: SR-A1
- Depends: T27, T09
- Deliverables:
  - Corpus overview tool, term frequency and trends over time, near-duplicate detection, document grouping; Analysis notes; workflow `literature-map`
- Validation:
  - Metrics reproduce on the fixture
  - Duplicate detection precision and recall reported
  - Every statistic names its scope
- Status: pending

### T29 — Citation extraction and citation graph
- Requirements: SR-A3
- Depends: T27, T09
- Deliverables:
  - In-text and reference-list extraction (numeric, author-year, DOI, arXiv), resolution to corpus documents, graph with in-degree, out-degree, co-citation, coupling, centrality; unresolved list; workflow `citation-analysis`
- Validation:
  - Known reference lists reproduce expected edges
  - Ambiguous matches flagged
- Status: pending

### T30 — Knowledge graph build, query and export
- Requirements: SR-A5
- Depends: T15, T29, T09
- Deliverables:
  - Scholarly graph from vault and extraction with provenance; neighbour, path and subgraph queries; export JSON, GraphML and Obsidian canvas; workflow `kg-explore`
- Validation:
  - Exports validate against their formats
  - Every edge has provenance
  - Queries deterministic
- Status: pending

### T31 — Research QA and scientific RAG workflows
- Requirements: SR-A2, SR-A3, SR-A4, SR-A5
- Depends: T26, T28, T29, T30
- Deliverables:
  - `grounded-qa` uses the brain consult; new workflows registered; `laris workflows check` passes; guide updated
- Validation:
  - Existing workflow tests pass
  - New workflow tests pass with a scripted provider
- Status: pending

### T32 — Scientific NLP extraction evaluation harness
- Requirements: SR-A6, SR-H2
- Depends: T15
- Deliverables:
  - Labelled fixture annotations; per-type precision, recall, F1 report; regression gate
- Validation:
  - Report reproducible
  - Regression fails the test
- Status: pending

## Phase 6 — Hardening and release

### T33 — Security test suite
- Requirements: SR-H1, SR-B3
- Depends: T20, T23, T16
- Deliverables:
  - Tests for traversal, symlinks, embed and link escape, YAML bombs, injection through notes and documents, secrets in notes, brain extraction attempts
- Validation:
  - Suite runs in CI
  - Each threat in the threat model has a passing test
- Status: pending

### T34 — Model-free evaluation harness
- Requirements: SR-H2, SR-A4
- Depends: T24, T32, T33
- Deliverables:
  - One command runs retrieval, citation, extraction, leak, injection and vault round-trip suites; reports under `reports/`
- Validation:
  - Reproducible results
  - CI runs the fast subset
- Status: pending

### T35 — Performance and scale benchmarks
- Requirements: SR-H4
- Depends: T24, T28
- Deliverables:
  - Benchmark script for 10,000 notes: full index, incremental update, memory, search P95; budgets recorded from measurements
- Validation:
  - Targets in the spec met or the gap reported
  - 20 percent regression gate
- Status: pending

### T36 — Documentation
- Requirements: SR-H3, SR-H5
- Depends: T31, T17
- Deliverables:
  - Architecture document for brain and vault, user guide update, owner runbook, links from the ADR
- Validation:
  - `validate_docs` passes
  - Guide-coverage test passes
- Status: pending

### T37 — Release 1.4.0
- Requirements: SR-H5
- Depends: T34, T35, T36
- Deliverables:
  - Version bump, changelog, pull requests, tag and release under the git flow
- Validation:
  - CI green on all jobs
  - Owner authorisation recorded
- Status: blocked
- Note: Needs the owner's authorisation to push, merge, tag and release.

## Phase 7 — Return to the core model (owner gate)

### T38 — Model boundary contract and resumption criteria
- Requirements: SR-H6
- Depends: T37
- Deliverables:
  - Document of the interfaces the model must satisfy (`ChatProvider`, embedder, tool calls, brain consult), contract tests with a scripted provider, resumption criteria
- Validation:
  - Contract tests pass
  - Criteria reviewed by the owner
- Status: pending

### T39 — Owner gate: resume the core model
- Requirements: SR-H6
- Depends: T38
- Deliverables:
  - Owner decision recorded; if approved, a new ledger for model work
- Validation:
  - Decision written in task.md
  - No agent training run
- Status: blocked
- Note: Owner decision. The agent never starts training.
