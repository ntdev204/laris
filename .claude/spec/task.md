# LARIS — Task ledger: Obsidian brain, scholarly harness and the second programme

Version 0.2.0 · 2026-11-12 (T48-T85: second programme) · Implements [plan.md](plan.md) for [spec.md](spec.md).

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

### T41 — Policy server and thin client
- Requirements: SR-H7
- Depends: T40
- Deliverables:
  - ADR-016; `src/gateway/` (prompt composition, brain consult and tools, leak/secret guard on the server); `POST /v1/laris/chat`, `GET /v1/laris/workflows|help`; client `PolicyServerProvider`, `RemoteComposer`, `RemoteWorkflows`, public message catalogue
  - `laris login --server`, `laris init`; global `~/.laris` and project `./.laris`; `packaging/npm` launcher and wheel build
- Validation:
  - An empty folder runs against the server; policy text never reaches the client or the stream; client `system` messages and the bare endpoint are refused
- Status: done
- Note: ADR-016; src/gateway (prompt composition, brain consult and tools, leak and secret guard on the server); POST /v1/laris/chat, GET /v1/laris/workflows|help|account; client PolicyServerProvider, RemoteComposer, RemoteWorkflows, public message catalogue; `laris login --server`, `laris init`; global ~/.laris with settings.json (server address, model, key) and project ./.laris; wheel compiled with Cython (no readable source; packaging/build_client.py) and the npm launcher (packaging/npm); TLS with trust on first use for private certificates (laris login shows and pins the fingerprint). Not done and not part of the deliverables: key rotation helper, automatic backups, per-role rate limits. Publishing to npm needs the owner's login.

### T47 — Server database, managed keys, quotas, private reasoning
- Requirements: SR-H9
- Depends: T40
- Deliverables:
  - ADR-018; `src/serverdata/` (SQLite, keys, usage, traces, cache); `serving/ports.py`; gateway diverts reasoning and meters tokens; `laris-server keys|usage|reasoning`; `laris whoami` shows role and balance
- Validation:
  - tests/unit/serverdata pass; reasoning is absent from every chat response and present in the database
- Status: done
- Note: Keys are stored encrypted (master secret outside the database) and the first start creates a built-in server-only admin key (tests/unit/serverdata). User guide (locked policy) does not yet tell users that reasoning traces are stored; needs owner approval. Not done: key rotation helper, database backup, per-role rate limits, a vetted AEAD library instead of the standard-library construction.

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
- Status: done
- Note: src/vault/notes.py parses wikilinks, aliases, headings, block ids (`blocks`), embeds, Markdown links, tags, properties; code and comments are excluded. tests/unit/vault/test_vault_phase1.py holds the never-raises random-text test and block-id test.

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
- Status: done
- Note: src/vault/index.py: shortest-path resolution, ambiguity, backlinks, orphans, incremental reuse, deterministic `dumps()` and a disposable on-disk cache (`cache_file`; deleting or corrupting it loses nothing). Tests assert byte-identical output and per-note change.

### T07 — Safe writer with managed blocks and conflict detection
- Requirements: SR-V4, SR-V5, SR-H1
- Depends: T06
- Deliverables:
  - `src/vault/writer.py`: atomic write, path confinement to the vault, symlink and junction refusal, filename sanitisation and collision suffixes, size and rate limits, secret redaction, injection scan, managed-block markers, hash-based user-edit detection, backup before rewrite
- Validation:
  - Crash during write leaves the old file
  - User text outside managed blocks survives 100 rewrites (property test)
  - Traversal, symlink and forbidden-character tests pass
- Status: done
- Note: src/vault/writer.py: atomic write (crash test), confinement, symlink refusal, managed blocks with hash conflict detection, size cap, injection scan, redaction hook, backup before rewrite under `.laris/backups/` (never indexed), rate limit (`vault.max_writes_per_minute`), 100-rewrite test keeps user text.

### T08 — Note schema registry
- Requirements: SR-V5
- Depends: T06
- Deliverables:
  - `vault` section in `LarisConfig` and `configs/default.yaml`; `.laris/vault/schema.yaml` (types, required properties, relation properties, filename rules) under the integrity lock
  - Schema validator
- Validation:
  - Failing note is reported with a code
  - Defaults equal the schema defaults (existing test pattern)
- Status: done
- Note: `.laris/vault/schema.yaml` (under the integrity lock via `prompts.vault_dir`) and src/vault/schema.py (type, required, link, folder rules with codes); the built-in table equals the file (test). Lock refreshed with the owner's instruction to complete the tasks.

### T09 — Vault graph analytics
- Requirements: SR-V2, SR-A5, SR-B6
- Depends: T06
- Deliverables:
  - `src/vault/graph.py`: degree, PageRank, components, shortest path, local graph to depth N, neighbours by relation
- Validation:
  - Known small graphs reproduce expected values
  - Deterministic ordering
- Status: done
- Note: src/vault/graph.py: degree, PageRank (normalised, deterministic), weak components, shortest path (directed or not), local graph to depth N, neighbours by relation. Known small graphs tested.

### T10 — Vault lint command
- Requirements: SR-V2, SR-H1, SR-H3, SR-B6
- Depends: T07, T08
- Deliverables:
  - `laris vault check`: broken links, orphans, duplicate aliases, schema failures, forbidden characters, secrets, oversize notes; exit codes
  - Structural lint for hierarchy: levels, single parent, max depth, max children per hub, summaries, no orphans (config `brain.*`)
- Validation:
  - Fixture with seeded defects is detected exactly
  - Clean fixture passes
- Status: done
- Note: `laris vault check` runs format, schema and content lint (oversize, duplicate aliases, secrets) and writes the index cache; hierarchy and brain lint under `laris brain check`. Seeded-defect fixture found exactly; clean fixture passes.

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
- Status: done
- Note: ProjectVault.ensure and `laris vault init`; bootstrap on first ingest or answered turn; `_templates/` (Source, Concept, Question, Session; not indexed), `.obsidian/app.json`, `.gitignore`; a vault inside another Obsidian vault is refused (`vault.allow_nested`); an adopted vault keeps every existing byte; init twice changes nothing (tests). Scope decision: graph colour groups and plugin files are not written (docs/specifications/OBSIDIAN_VAULT_FORMAT.md section 6, unverified keys); the Obsidian manual graph check is replaced by an automated connectivity test, since Obsidian is not available to the agent.

### T12 — Source notes on ingest
- Requirements: SR-V4, SR-A1
- Depends: T11
- Deliverables:
  - Hook in `SearchService.ingest`: one Source note per document (metadata, hash, passage count, links to concepts), updated on re-ingest inside managed blocks
- Validation:
  - Re-ingest updates, never duplicates
  - Notes lint clean
  - Hook failure never fails ingestion
- Status: done
- Note: Ingest hook writes Source notes with doc_id, sha256 of the cleaned text, character count, passage count and the passage span range; re-ingest updates and never duplicates; a refused vault never fails ingestion (tests/unit/vault/test_project_lifecycle.py).

### T13 — Session and question-answer notes
- Requirements: SR-V4, SR-A2
- Depends: T11, T12
- Deliverables:
  - After each completed turn: Session daily-note entry, Question and Answer notes linking every cited Source; opt-out in config and settings
- Validation:
  - Every answer note links all cited sources
  - Turns blocked by guards write nothing
  - Secrets never reach notes
- Status: done
- Note: Verified turns write Question and Session notes linked to cited sources; blocked or failed turns write nothing; secrets redacted; per-user opt-out `vault_record` in settings.json (`vault.auto_record`).

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
- Status: done
- Note: `save_memory`, the prompt memory section and the remote client layer use `vault/Memory/` (src/vault/memory.py); `laris vault migrate-memory [--undo]` copies legacy `.laris/memory` files idempotently and reversibly; the tool's arguments and result are unchanged; prompt memory is capped by `prompts.max_memory_chars`.

### T15 — Concept and claim notes from extraction
- Requirements: SR-V4, SR-A6
- Depends: T12
- Deliverables:
  - Extraction results become Concept, Method, Dataset, Metric, Claim and Limitation notes with character-span provenance and links to Sources
- Validation:
  - Spans match source text
  - Duplicate concepts merge by stable id and alias
- Status: done
- Note: src/vault/entities.py: method, dataset and metric notes (Concepts/) and claim and limitation notes (Claims/) with character spans of the cleaned document, stable ids (hash of type and normalised name) and mentions merged across documents; spans verified against the rebuilt text; extraction is best effort and never fails ingestion.

### T16 — User-edit safety, sync and repair
- Requirements: SR-V4
- Depends: T07, T13
- Deliverables:
  - `laris vault sync` and `laris vault repair`; conflict policy documented; backups restorable
- Validation:
  - Interleaved user and system edits never lose user text
  - Repair is idempotent
- Status: done
- Note: `laris vault sync [--accept]` and `laris vault repair [--restore NOTE]` (src/vault/repair.py): hand edits inside managed blocks are reported and adopted on request, broken block markers closed, temp files removed, newest backup restorable; interleaved edit test never loses user text; repair is idempotent. Conflict policy is in the user guide.

### T17 — Vault user experience
- Requirements: SR-H3
- Depends: T10, T13
- Deliverables:
  - `laris vault` commands, chat `/vault`, web Vault panel (search, open note, graph export), string catalogue entries, guide update and coverage test
- Validation:
  - Guide-coverage test lists every new command
  - Web script passes `node --check`
- Status: done
- Note: `laris vault` init, status, check, search, show, graph, sync, repair, migrate-memory; chat `/vault [words]`; guide section 11 and a coverage test listing every vault command. The web panel is dropped: the product is terminal-only (test_web_is_removed); `vault graph --format json` is the export.

## Phase 3 — System brain

### T18 — System brain loader and protected access
- Requirements: SR-B1
- Depends: T06, T04
- Deliverables:
  - Brain path from configuration or packaged data; deny-read globs; integrity lock covers brain notes; read-only enforcement; no model-controlled paths
- Validation:
  - `read_file`, `list_files`, `ingest_path`, `save_skill` and path tricks are denied
  - Tampered brain note stops the session
- Status: done
- Note: Brain folder is in integrity.lock, denied to file tools (folder and contents, symlink and dot-dot tricks tested), read-only class; a tampered brain note stops the session (policy tests); the project vault may not overlap the brain (`ProjectVault(protected=...)`).

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
- Status: done
- Note: brain_open_root, brain_route, brain_open, brain_neighbors, brain_search, brain_consult with budgets, internal marking and no paths; workflow allow-lists include or exclude them.

### T20 — Leak guard for brain content
- Requirements: SR-B3
- Depends: T19
- Deliverables:
  - Brain notes feed the shingle detector with a memory budget; egress rule extended to brain content
- Validation:
  - Adversarial extraction cases produce no shingles above the limit
  - Detector memory stays under budget
- Status: done
- Note: Brain text feeds the shingle detector under a memory budget (`security.leak_max_shingles`; the real brain uses about 5k of 200k shingles, under 1 MB) and audit logs store titles only. tests/unit/vault/test_brain_leak_adversarial.py: verbatim, upper-case, one-word-per-line, punctuation-spaced, bulleted, emphasised, quoted and 12-word-window copies are all blocked, also when streamed in 3-character chunks. Encodings and paraphrase are outside a shingle detector (documented in T33).

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
- Status: done
- Note: Owner approved the content on 2026-11-11 ("Duyệt brain") after agent review: structure lint clean, all tool names real, Vietnamese routing keywords added. Dependencies T08 and T18 are done.

### T22 — Reasoning playbooks and workflow links
- Requirements: SR-B2, SR-B4, SR-B6
- Depends: T21, T19
- Deliverables:
  - One playbook per direction (decide, verify, stop); workflows reference playbooks; `.laris/workflows` updated under the lock
- Validation:
  - `laris workflows check` passes
  - Each playbook is reachable from the brain index
- Status: done
- Note: Six playbooks (Decide, Verify, Stop) reachable from the root in two steps; workflows routed through the root table and allowed brain tools (workflows 1.1.0); owner approved T21 content.

### T23 — Proposals inbox and owner review
- Requirements: SR-B5
- Depends: T13, T18
- Deliverables:
  - Runtime learnings written to `vault/_inbox/`; `laris brain propose|review|accept|reject`; accepted items enter the project vault, never the system brain
- Validation:
  - No runtime write path to the system brain (test)
  - Proposals are excluded from retrieval until accepted
- Status: done
- Note: src/vault/proposals.py: runtime learnings go to `_inbox/`, are excluded from retrieval and memory until accepted; `laris vault propose|review|accept|reject` (also `laris-server brain ...`); accepting copies into the project vault (memory, decision or concept); tests prove the system brain tree hash is unchanged and an overlapping vault is refused.

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
- Status: done
- Note: src/vault/retrieval.py: BM25 over notes (vault/search.py), link-neighbourhood expansion with decay, reciprocal-rank fusion with corpus search, provenance on every result (bm25, link with its seed, corpus), token estimate; navigation-first over the brain (`navigate`: route and expand through the consult, `brain.search` only as fallback). Measured on tests/fixtures/retrieval (12 notes, 4 queries): BM25 alone Recall@5 0.583, MRR 1.0, nDCG@5 0.674; graph retrieval Recall@5 1.0, MRR 1.0, nDCG@5 1.0; ordering deterministic.

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
- Status: done
- Note: Consult step in the loop with config toggle (brain.consult), audit of titles, hidden brief and visible title trace; the path of ids is kept in `last_turn.brain_trace`; prompt 1.2.0 and lock refreshed; navigation-first retrieval (T24) reported with token use.

### T26 — Reasoning trace and explainable answers
- Requirements: SR-B4, SR-A2
- Depends: T25, T13
- Deliverables:
  - Answer notes cite vault notes and sources; trace stored with the answer note
- Validation:
  - Every cited note exists
  - Verifier checks still pass
- Status: done
- Note: Answer notes carry the brain path (titles only) in a `trace` managed block and `notes_used` links to project notes that exist (nonexistent titles are dropped), besides the cited Sources; lint and schema stay clean, unresolved links none; verifier tests unchanged.

## Phase 5 — Scholarly analytics

### T27 — Bibliographic metadata extraction
- Requirements: SR-A1, SR-A3
- Depends: T12
- Deliverables:
  - Title, authors, year, DOI and arXiv id from text and PDF metadata; stored in Source properties
- Validation:
  - Fixture accuracy reported
  - Missing values stay empty, never guessed
- Status: done
- Note: src/scholarly/biblio.py: title, authors, year, DOI and arXiv id from the first page and from PDF metadata (`pdf_metadata`), written to Source properties (`bib_title`, `authors`, `year`, `doi`, `arxiv`) by the ingest hook; a field is filled only from explicit evidence (metadata, DOI/arXiv pattern, publication or copyright line, strict title/author shape). Fixture of 10 cases (50 fields): 50 correct, 0 missing, 0 wrong; empty cases stay empty.

### T28 — Literature mining analytics
- Requirements: SR-A1
- Depends: T27, T09
- Deliverables:
  - Corpus overview tool, term frequency and trends over time, near-duplicate detection, document grouping; Analysis notes; workflow `literature-map`
- Validation:
  - Metrics reproduce on the fixture
  - Duplicate detection precision and recall reported
  - Every statistic names its scope
- Status: done
- Note: src/scholarly/mining.py and tools corpus_overview, term_trends, find_duplicates, group_documents, save_analysis (Analysis notes with their scope); workflow `literature-map` 1.0.0 (lock refreshed). Every result names its scope (documents, documents with a year, left out). Near-duplicates (MinHash buckets plus exact Jaccard) match the brute-force reference on the fixture: precision 1.00, recall 1.00; trends, overview and groups reproduce exactly.

### T29 — Citation extraction and citation graph
- Requirements: SR-A3
- Depends: T27, T09
- Deliverables:
  - In-text and reference-list extraction (numeric, author-year, DOI, arXiv), resolution to corpus documents, graph with in-degree, out-degree, co-citation, coupling, centrality; unresolved list; workflow `citation-analysis`
- Validation:
  - Known reference lists reproduce expected edges
  - Ambiguous matches flagged
- Status: done
- Note: src/scholarly/citations.py: reference list (numbered and author-year) and in-text citation extraction (numeric with ranges, author-year, narrative), resolution to corpus documents by DOI, arXiv id or whole-title containment with a compatible year; weak (author and year only) and ambiguous matches are flagged and never become edges; graph with in/out degree, co-citation, coupling, PageRank centrality, unresolved list; tool `citation_graph`, workflow `citation-analysis` 1.0.0. A bibliography bug found by the fixture (a cited DOI was read as the paper's own) is fixed: identifiers are read before the reference list only.

### T30 — Knowledge graph build, query and export
- Requirements: SR-A5
- Depends: T15, T29, T09
- Deliverables:
  - Scholarly graph from vault and extraction with provenance; neighbour, path and subgraph queries; export JSON, GraphML and Obsidian canvas; workflow `kg-explore`
- Validation:
  - Exports validate against their formats
  - Every edge has provenance
  - Queries deterministic
- Status: done
- Note: src/scholarly/kg.py: graph from vault links, claim/limitation/entity notes (character spans) and resolved citations (reference line); an edge without provenance is rejected; neighbour, path, subgraph, find queries; exports JSON, GraphML and Obsidian canvas (JSON Canvas 1.0, write-only; docs/specifications/OBSIDIAN_VAULT_FORMAT.md updated), all validated by tests; tool `kg_query`, `laris vault graph --format graphml|canvas --out`, workflow `kg-explore` 1.0.0.

### T31 — Research QA and scientific RAG workflows
- Requirements: SR-A2, SR-A3, SR-A4, SR-A5
- Depends: T26, T28, T29, T30
- Deliverables:
  - `grounded-qa` uses the brain consult; new workflows registered; `laris workflows check` passes; guide updated
- Validation:
  - Existing workflow tests pass
  - New workflow tests pass with a scripted provider
- Status: done
- Note: `grounded-qa` 1.2.0 follows the brain brief's playbook and can call `search_vault` (graph-aware vault retrieval, inbox excluded); new workflows literature-map, citation-analysis, kg-explore registered (7 valid workflows, `laris workflows check` passes); scripted-provider tests run each workflow, check allow-lists and the brain brief; guide updated and covered by the guide test.

### T32 — Scientific NLP extraction evaluation harness
- Requirements: SR-A6, SR-H2
- Depends: T15
- Deliverables:
  - Labelled fixture annotations; per-type precision, recall, F1 report; regression gate
- Validation:
  - Report reproducible
  - Regression fails the test
- Status: done
- Note: src/evaluation/extraction.py: labelled fixture (tests/fixtures/extraction, 4 documents including a text with no entities and cases the extractor misses), per-type precision, recall and F1 with IoU span matching, micro and macro averages, byte-reproducible report, regression gate against tests/fixtures/extraction/baseline.json. Measured: micro precision 1.00, recall 0.88, F1 0.936; macro F1 0.943 (claim 0.889, method 1.0, dataset 0.857, metric 1.0, result 1.0, limitation 0.857, assumption 1.0). A degraded extractor fails the gate.

## Phase 6 — Hardening and release

### T33 — Security test suite
- Requirements: SR-H1, SR-B3
- Depends: T20, T23, T16
- Deliverables:
  - Tests for traversal, symlinks, embed and link escape, YAML bombs, injection through notes and documents, secrets in notes, brain extraction attempts
- Validation:
  - Suite runs in CI
  - Each threat in the threat model has a passing test
- Status: done
- Note: tests/unit/security/test_security_suite.py plus the earlier brain, vault and server tests: traversal, symlinked folders and notes, link and embed escape, YAML bombs, injection through documents and notes, secrets in notes, brain extraction (tools, ingest, bulk sweep) and adversarial leak variants. Real holes found and fixed: a symlinked note pointing outside the vault was read into the index; YAML aliases could expand without bound (now refused, with size and depth caps). docs/architecture/BRAIN_THREAT_MODEL.md has TH1 to TH21; a test checks that every row names tests that exist. Residual risk (paraphrase, translation, encoding) is recorded as accepted.

### T34 — Model-free evaluation harness
- Requirements: SR-H2, SR-A4
- Depends: T24, T32, T33
- Deliverables:
  - One command runs retrieval, citation, extraction, leak, injection and vault round-trip suites; reports under `reports/`
- Validation:
  - Reproducible results
  - CI runs the fast subset
- Status: done
- Note: `laris-server evaluate suite [--fast] [--only a,b] [--out FILE]` (src/evaluation/suite.py): retrieval (BM25 vs graph), citation edges against gold, extraction against the baseline gate, leak (adversarial brain copies), injection (recall and false positives) and vault round-trip (lint, identical rebuild, user text, conflicts). The report is byte-reproducible (reports/model_free/report.json, committed). CI runs the fast subset and the model-free test group through `make check-no-training` (`test-model-free`, `eval-fast`); the install step now adds the `server` extra. States that the core model is NOT QUALIFIED.

### T35 — Performance and scale benchmarks
- Requirements: SR-H4
- Depends: T24, T28
- Deliverables:
  - Benchmark script for 10,000 notes: full index, incremental update, memory, search P95; budgets recorded from measurements
- Validation:
  - Targets in the spec met or the gap reported
  - 20 percent regression gate
- Status: done
- Note: scripts/benchmark_vault.py (10,000 synthetic notes): full index 2.6 s (target 30), one-note incremental update 0.52 s with the disposable cache (target 1), peak memory 182 MB (target 500), BM25 search P95 18 ms (target 300) on the development workstation; budgets recorded in reports/performance/budgets.json; `--check` fails on a target miss or a figure more than 20 percent over its budget (`make bench-vault`). Not part of CI because timings depend on the machine.

### T36 — Documentation
- Requirements: SR-H3, SR-H5
- Depends: T31, T17
- Deliverables:
  - Architecture document for brain and vault, user guide update, owner runbook, links from the ADR
- Validation:
  - `validate_docs` passes
  - Guide-coverage test passes
- Status: done
- Note: docs/architecture/BRAIN_AND_VAULT.md (vault, brain, retrieval, analytics, measured figures, limits), docs/development/OWNER_RUNBOOK.md (server, TLS, keys, reasoning traces, policy changes, backups, build and release), docs/development/CLI.md, user guide sections 6 and 11 with the guide-coverage tests, links from ADR-014 and AGENT_HARNESS.md; validate_docs passes.

### T37 — Release 1.4.0
- Requirements: SR-H5
- Depends: T34, T35, T36
- Deliverables:
  - Version bump, changelog, pull requests, tag and release under the git flow
- Validation:
  - CI green on all jobs
  - Owner authorisation recorded
- Status: done
- Note: 1.4.0 was released earlier under the owner's authorisation (PRs 329 to 331, tag v1.4.0). The work added since then (client and server split, TLS, database keys, agentic loop, vault and scholarly analytics) is released as 1.5.0 under the owner's authorisation of 2026-11-11 (commit, merge, push, delete branches, npm publish); dependencies T34, T35, T36 are done.

## Phase 7 — Return to the core model (owner gate)

### T38 — Model boundary contract and resumption criteria
- Requirements: SR-H6
- Depends: T37
- Deliverables:
  - Document of the interfaces the model must satisfy (`ChatProvider`, embedder, tool calls, brain consult), contract tests with a scripted provider, resumption criteria
- Validation:
  - Contract tests pass
  - Criteria reviewed by the owner
- Status: blocked
- Note: docs/architecture/MODEL_BOUNDARY.md lists the interfaces (ChatProvider, stream with reasoning, backend loading, embedder, tool calls, plan tool, brain brief, usage) and the six criteria for resuming the model; tests/unit/agent/test_model_boundary.py checks every interface with a scripted reference model (6 tests). Waiting for the owner's review of the criteria before this task is done.

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

## Phase 8 — Layers and Agentic

### T42 — Layer contract: loop, harness, prompt
- Requirements: SR-H8
- Depends: T40
- Deliverables:
  - ADR-017; a contract test: the prompt layer imports neither the loop nor tools, the loop holds no policy path or prompt text
- Validation:
  - Contract test passes
- Status: done
- Note: tests/unit/architecture/test_layers.py. It caught one violation, fixed by moving the API-key helpers to `harness/credentials.py` (`cli/credentials.py` re-exports them).

### T43 — Plan state
- Requirements: SR-H8
- Depends: T42
- Deliverables:
  - A visible plan (steps with status) created before the first tool call of a multi-step goal, kept in the session and written to the vault
- Validation:
  - Scripted scenario shows the plan before any tool call and its status after each step
- Status: done
- Note: `agent/plan.py`, tool `update_plan`, `plan` events, ephemeral plan view each step, harness-recorded plan when the model acts without one (`agent.plan.mode`: off|auto|always).

### T44 — Reflect, replan and completion check
- Requirements: SR-H8
- Depends: T43
- Deliverables:
  - Progress check after each tool result; bounded replan on a failed or empty step; the goal closes only when its done-criteria hold
- Validation:
  - Scenarios: a failing step replans within the budget; an unmet criterion keeps the loop going or reports what is missing
- Status: done
- Note: `agent/reflect.py`; `agent.reflect.max_replans`, `completion_retries`; failed steps are reported, open steps hold the goal; `goal` events.

### T45 — Resume goals across sessions
- Requirements: SR-H8
- Depends: T43
- Deliverables:
  - Interrupted goals continue after `laris --resume`; finished results are recalled from the vault in later sessions
- Validation:
  - Scenario: stop mid-plan, resume, finish without repeating completed steps
- Status: done
- Note: The plan is saved in the conversation (`plan`) and resumed (`plan` event source `resumed`); the finished goal and its plan are written to the vault note.

### T46 — Agentic scenario suite
- Requirements: SR-H8
- Depends: T44, T45
- Deliverables:
  - Scripted-provider scenarios covering the six criteria of ADR-017 section 3; a report that states the model is NOT QUALIFIED
- Validation:
  - Suite passes; limits hold in every scenario
- Status: done
- Note: tests/unit/agent/test_agentic_scenarios.py (14 scenarios) and docs/testing/AGENTIC_SCENARIOS.md; the report states the model is NOT QUALIFIED. Scripted provider only: says nothing about a trained model's planning quality.

## Phase 9 — Decisions of the second programme

### T48 — ADR-019 and dependency approvals
- Requirements: SR-S1, SR-S2, SR-H5
- Depends: T46
- Deliverables:
  - ADR-019 "Three blocks, two protocols, two SQL engines, Docker, terminal client" with D10 to D21
  - Amendments to ADR-015 (embedding path, server storage, client data in the global home), ADR-016 (no offline mode, protocol version, global home and isolated runtime, project `.laris/` without configuration, login without `--server`), ADR-018 (PostgreSQL, trusted proxy)
  - `pyproject.toml` extras: `server` (fastapi, uvicorn, psycopg[binary], psycopg_pool, cryptography), `model` (fastapi, uvicorn); `ink`, `react` recorded as approved (2026-11-12) with pinned versions; `prompt_toolkit` and `rich` recorded as approved then dropped (D22); `uv` recorded as approved (2026-11-12) for sandbox provisioning, its binary pinned per platform
- Validation:
  - `validate_docs` and `validate_spec` pass; ADR index lists ADR-019
- Status: pending

## Phase 10 — Three blocks

### T49 — Protocol package and removal of import cycles
- Requirements: SR-S1, SR-S2
- Depends: T48
- Deliverables:
  - `laris.protocol`: `Message`, `ToolCall`, `AssistantTurn`, `ChatProvider`, SSE encode and decode, `Chunk`, P1 and P2 pydantic schemas, protocol version constant
  - Cycles removed: `Chunk` out of `application/workspace.py`, provider types out of `agent/provider.py`, `check_key` out of `harness/credentials.py`, `config/loader.py` no longer imports `harness.prefs`
- Validation:
  - No cycle among `agent`, `harness`, `vault`, `application`, `learning`; the no-training suite passes unchanged
- Status: pending

### T50 — Move packages into blocks
- Requirements: SR-S1
- Depends: T49
- Deliverables:
  - A one-off import-rewrite script; packages moved to `src/laris/{shared,client,server,model,research}` as listed in spec SR-S1 (brain to server, project vault to client, `serving` and `serverdata` to server, `execution` and `language/inference` to model, training and evaluation to research)
  - Tests, configuration, `pyproject.toml`, Makefile and CI paths updated
- Validation:
  - `ruff`, `mypy`, `validate_docs`, `make check-no-training` pass with the same results as before the move
- Status: pending

### T51 — Block-boundary contract test
- Requirements: SR-S1
- Depends: T50
- Deliverables:
  - `tests/unit/architecture/test_blocks.py`: blocks import only `protocol` and `shared`; nothing imports `research`; `shared` and `protocol` import no block
- Validation:
  - Test passes and fails on a planted violation
- Status: pending

### T52 — Entry points and the client wheel by block
- Requirements: SR-S1
- Depends: T51
- Deliverables:
  - Entry points `laris`, `laris-server`, `laris-model`; `cli/main.py` role switch removed
  - `packaging/build_client.py` builds from `client`, `protocol`, `shared` instead of an import closure; `client-package.yml` updated
- Validation:
  - Built wheel contains no server, model, research module and no `.laris/` policy; npm smoke test in an empty folder passes
- Status: pending

## Phase 11 — Model service

### T53 — Model service on P2
- Requirements: SR-S3, SR-S2
- Depends: T52
- Deliverables:
  - `laris-model serve` (FastAPI, uvicorn): `/v1/chat/completions` (stream, tools, reasoning), `/v1/embeddings`, `/health`; backend loader and `OfflinePlanner` placeholder moved here; encoder from `language/inference`
  - The client loses its offline mode (D16)
- Validation:
  - Model boundary tests (SR-H6) pass over HTTP with the scripted backend; P2 contract tests pass
- Status: pending

### T54 — GPU queue from the execution package
- Requirements: SR-S3
- Depends: T53
- Deliverables:
  - Task router, weight staging and headroom governor wired into the model service: one queue, load and release by VRAM budget (configuration only)
- Validation:
  - Scripted backends with declared sizes never exceed the configured budget; queue order and timeouts tested
- Status: pending

### T55 — Server calls the model over P2
- Requirements: SR-S3
- Depends: T54
- Deliverables:
  - Gateway backend is an `HttpChatProvider` to `model_api.internal_url`; bounded concurrency `serving.model_concurrency`; no model code in the server process
- Validation:
  - Gateway tests pass against a model service; pointing the URL at another OpenAI-compatible server needs no code change
- Status: pending

## Phase 12 — Server API

### T56 — FastAPI server for P1
- Requirements: SR-S4, SR-S2
- Depends: T55
- Deliverables:
  - P1 routes on FastAPI and uvicorn replacing `serving/model_server.py`; body validation (size, negative or missing `Content-Length`, shape); SSE `error` event mid-stream; protocol header check; brain lock narrowed to the brain budget
- Validation:
  - Tests for 400, 401, 403, 411, 413, 429, version mismatch, error mid-stream, a slow client not blocking others; `test_policy_server.py` passes
- Status: pending

### T57 — Trusted proxy and address rules
- Requirements: SR-S4
- Depends: T56
- Deliverables:
  - `serving.trusted_proxies`; real address from `X-Forwarded-For` only from a trusted proxy; `@server` and CIDR rules use it
- Validation:
  - Tests with trusted, untrusted and forged headers
- Status: pending

### T58 — Embedding through the server
- Requirements: SR-S2, SR-S4
- Depends: T56, T53
- Deliverables:
  - `POST /v1/laris/embed` (permission `embed`, metered, text never stored); client dense search embeds through it; the client no longer loads an encoder
- Validation:
  - Dense search works end to end with a scripted encoder; a test shows no request text in the database
- Status: pending

### T59 — Default key handling
- Requirements: SR-S4
- Depends: T56
- Deliverables:
  - The default key is no longer printed; `laris-server keys reveal default` or a 0600 secret file delivers it
- Validation:
  - Start-up output and logs contain no key (test)
- Status: pending

## Phase 13 — Server storage on PostgreSQL

### T60 — PostgreSQL adapter and migrations
- Requirements: SR-S5
- Depends: T52
- Deliverables:
  - `laris.server.storage` on `psycopg_pool` implementing the ports; numbered SQL migrations; `laris-server db migrate`; key logic of `serverdata/keys.py`, `crypto.py`, `cache.py`, `netcheck.py` reused with new SQL
- Validation:
  - Storage tests pass with `LARIS_TEST_PG_DSN`; CI runs them against a PostgreSQL service
- Status: pending

### T61 — Atomic quota
- Requirements: SR-S5
- Depends: T60, T56
- Deliverables:
  - Reserve before the model call, settle after it in one transaction, in `finally`
- Validation:
  - N parallel requests never pass a limit; a disconnect is still settled
- Status: pending

### T62 — Partitions and retention
- Requirements: SR-S5
- Depends: T60
- Deliverables:
  - Monthly partitions for `usage` and `traces`; background retention on `serving.retention_interval_s`; daily usage summary
- Validation:
  - Expired partitions removed by the task; summaries match raw usage
- Status: pending

### T63 — Import from the SQLite server database
- Requirements: SR-S5
- Depends: T60
- Deliverables:
  - `laris-server db import-sqlite PATH` for keys, usage and traces
- Validation:
  - Lossless on a fixture database; imported keys verify and reveal
- Status: pending

## Phase 14 — Client storage on SQLite

### T64 — Client store and automatic migration
- Requirements: SR-S6
- Depends: T52
- Deliverables:
  - `laris.client.store`: one SQLite file per private space at `~/.laris/projects/<slug>/<key-fp>.sqlite` (WAL, busy timeout, numbered migrations); one-time idempotent migration of existing files (including the project's `artifacts/chat/users/<fp>/`) with backups
- Validation:
  - Migration tests on fixtures; second run changes nothing; backups present
- Status: pending

### T65 — Workspace and embedding cache in SQLite
- Requirements: SR-S6
- Depends: T64, T58
- Deliverables:
  - `Workspace` and `SearchService` on the store with the same public interface; vectors cached by passage and model id; BM25 ranking unchanged
- Validation:
  - Rankings identical before and after on the retrieval fixture; two concurrent ingests lose nothing
- Status: pending

### T66 — Conversations, learning data and vault index cache in SQLite
- Requirements: SR-S6
- Depends: T64
- Deliverables:
  - `ConversationStore`, `Collector` storage and the vault index cache on the store; `laris learn export` still writes JSONL; vault notes stay Markdown
- Validation:
  - Existing conversation, learning and vault tests pass; export matches the earlier format
- Status: pending

## Phase 15 — Deployment with Docker

### T67 — API and model images
- Requirements: SR-S7
- Depends: T55, T56
- Deliverables:
  - `docker/api.Dockerfile` (slim, non-root, `.[server]`), `docker/model.Dockerfile` (CUDA base, inference only); `.dockerignore` keeps policy, weights and data out
- Validation:
  - Images build; an image scan shows no `.laris/`, weights or data
- Status: pending

### T68 — Compose, Caddy and secrets
- Requirements: SR-S7, SR-S4
- Depends: T67, T60, T57
- Deliverables:
  - `docker/compose.yaml` (caddy, api, model with GPU reservation, postgres; internal network), `docker/Caddyfile` (TLS, SSE flush, body limit, timeouts), read-only mounts, Docker secrets, health checks
- Validation:
  - `docker compose config` validates; only Caddy publishes ports; integrity check runs at API start
- Status: pending

### T69 — Backup, runbook and smoke test
- Requirements: SR-S7
- Depends: T68, T62
- Deliverables:
  - `pg_dump` backup and restore scripts; operator runbook; end-to-end smoke test (empty folder, fresh home: login, chat with the placeholder, dense search)
- Validation:
  - Smoke test passes on the stack, or its commands are handed to the owner when no Docker or GPU is available
- Status: pending

## Phase 16 — Terminal client like Claude Code

### T70 — Engine and engine protocol E1
- Requirements: SR-C7
- Depends: T52, T48
- Deliverables:
  - `laris engine --stdio`: the agent session behind E1 (JSON lines; events and commands of SR-C7; version in `ready`); JSON Schema in `laris.protocol`; the existing `AgentSession.send()` events mapped onto E1
- Validation:
  - Contract tests for every event and command; a scripted session produces a stable, schema-valid transcript
- Status: pending

### T71 — Global home, credentials and Claude-Code-style settings
- Requirements: SR-C6, SR-C2
- Depends: T52
- Deliverables:
  - Global home layout of SR-C6; `settings.json` with a shipped JSON Schema (server, model, ui, permissions, env, hooks, statusLine, sandbox, vault, learning, cleanupPeriodDays, autoUpdates); environment and flags override for one run; `laris config get|set` and `/config`
  - Project `./.laris/` limited to `LARIS.md`, `skills/`, `commands/`, `memory/`; configuration files there ignored with a warning; `laris init` creates only that layout
  - `laris login` without `--server`: reads `server.url`, hidden key prompt, check, certificate pin into `server.caFingerprint`, key saved to `~/.laris/.credentials.json` (0600)
  - One-time migration of a 1.x home (`config.yaml`, `api_key`, legacy `runtime/<version>/`) with backups
- Validation:
  - Schema errors name the JSON path; first start in an empty home creates the layout; migration is idempotent; login refuses without `server.url`; a planted project `settings.json` changes nothing
- Status: pending

### T72 — Automatic sandbox
- Requirements: SR-C8, SR-C5
- Depends: T71
- Deliverables:
  - Background check at start and health check before each use; silent build and repair of `~/.laris/.venv/` with the bundled `uv` (standalone Python into `~/.laris/python/` from a configured source with checksums, else a suitable system Python); `sandbox.packages`; built-in `allow` rule for installs into the sandbox (user rules may tighten it); file lock; status-line hints; `/sandbox` and `/sandbox reset`
  - Command environment: sandbox first on `PATH`, `VIRTUAL_ENV`, `PIP_REQUIRE_VIRTUALENV=1`
- Validation:
  - Temporary-home tests: an install into the sandbox runs without a prompt and a user `ask` rule restores the prompt; first use builds it without user action; deleted or corrupted sandbox repaired; two parallel sessions build once; offline without Python gives a clear message and the program keeps working; nothing written to system or user site-packages
- Status: pending

### T73 — Slash-command registry and custom commands
- Requirements: SR-C2
- Depends: T70
- Deliverables:
  - Registry in the engine replacing the `if/elif` chain in `cli/commands/agent.py`; built-in commands of SR-C2; custom commands from `~/.laris/commands` and `./.laris/commands` with `$ARGUMENTS`; completion served through E1 `complete`
- Validation:
  - Tests for each built-in command, completion and custom-command expansion
- Status: pending

### T74 — Permission modes and rules
- Requirements: SR-C3
- Depends: T71, T70
- Deliverables:
  - Modes `default`, `acceptEdits`, `plan`, policy-gated `bypass`; `allow`, `ask`, `deny` rules with patterns; `permission_request` and `permission_response` over E1; "always allow" written to `~/.laris/projects/<slug>/state.json` (or `permissions.allow` in `~/.laris/settings.json` for "everywhere"); Shift+Tab cycles modes
- Validation:
  - Rule precedence (deny wins), each mode, persistence of answers
- Status: pending

### T75 — Coding tools, diffs and checkpoints
- Requirements: SR-C3, SR-C5
- Depends: T74, T72
- Deliverables:
  - `Read`, `Write`, `Edit`, `Glob`, `Grep`, `Bash` under the path policy and guards; `Bash` runs in the sandbox; built-in deny rule for installs outside the sandbox; diff carried in `permission_request`; checkpoint per edit (in `~/.laris/projects/<slug>/checkpoints/`) and `/rewind`
- Validation:
  - `Edit` uniqueness, denied paths never written, `Bash` timeout and confinement, `pip install --user` or a system interpreter install denied, rewind restores files
- Status: pending

### T76 — Input forms
- Requirements: SR-C2
- Depends: T73
- Deliverables:
  - `@path` mentions with completion, `!command` (in the sandbox), `# note`, pasted long text and images (local OCR)
- Validation:
  - Tests for each form; `!command` follows permission rules
- Status: pending

### T77 — Headless mode
- Requirements: SR-C4
- Depends: T70, T74
- Deliverables:
  - `laris -p`, standard input, `--output-format text|json|stream-json` (stream-json is E1), `--continue`, `--resume`, `--max-turns`, `--permission-mode`, `--allowed-tools`, `--disallowed-tools`, documented exit codes
- Validation:
  - Scripted-provider tests for every format and exit code
- Status: pending

### T78 — Hooks and folder trust
- Requirements: SR-C4, SR-C5
- Depends: T74, T72
- Deliverables:
  - Hooks `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Stop` declared only in `~/.laris/settings.json`, run inside the sandbox, with JSON input, block decisions and timeouts; `/hooks`; a project's custom commands and skills used only after the folder is trusted (trust in `~/.laris/projects/<slug>/state.json`)
- Validation:
  - Allow, block, timeout and malformed-output tests; an untrusted folder runs nothing; hooks placed in a project folder are never run
- Status: pending

### T79 — Status, cost, context, interrupt and queued input
- Requirements: SR-C1
- Depends: T70, T56
- Deliverables:
  - `status` events (model, mode, context use, tokens left from `/v1/laris/account`, git branch, sandbox state); `/cost` and `/context`; `interrupt` closes the running stream and keeps a consistent conversation; messages sent while working are queued
- Validation:
  - Values match the account route and the context estimator; interrupt tests: saved conversation valid, usage recorded by the server
- Status: pending

### T80 — Plain-text mode (no dependencies)
- Requirements: SR-C1
- Depends: T79, T73, T76
- Deliverables:
  - `laris --plain`: minimal mode in the engine using only `input`/`print` over E1 (messages, approvals with diffs as text, slash commands, Ctrl+C); replaces the current `input()` REPL; offered by the npm launcher when the Ink front end cannot start
- Validation:
  - Pipe-input tests of the scenarios that apply to plain mode; no new dependency imported
- Status: pending

### T81 — Ink and React front end
- Requirements: SR-C1, SR-C7
- Depends: T79, T73, T76
- Deliverables:
  - TypeScript front end in the main npm package that starts the engine binary and speaks E1; multi-line input, history and search, completion, streamed Markdown with highlighting, spinner, approval dialogs with diffs, status line, Esc and Ctrl+C, queued input; version check against `ready`; build step and package layout (`packaging/npm`), Node engines field kept at 18 or newer
- Validation:
  - The scenario set passes through a recorded engine; npm smoke test in an empty folder with a fresh home starts the Ink interface; a version mismatch is reported
- Status: pending

### T82 — Client acceptance suite
- Requirements: SR-C1, SR-C2, SR-C3, SR-C4, SR-C6, SR-C7, SR-C8
- Depends: T75, T77, T78, T80, T81
- Deliverables:
  - End-to-end scripted sessions (Ink front end, plain mode and headless) covering the phase's features; user guide section drafted for owner approval (the guide is locked policy)
- Validation:
  - Suite passes in CI on Python 3.10 to 3.12 and Node 18 and 20
- Status: pending

## Phase 17 — Hardening and release 2.0.0

### T83 — Security tests for the new surfaces
- Requirements: SR-S4, SR-C5
- Depends: T69, T82
- Deliverables:
  - Tests for slow handshakes, oversized and malformed bodies, forged forwarding headers, container isolation (ports, mounts), untrusted folders, planted project configuration, hostile hook output, injected shell and install requests, a tampered sandbox download
- Validation:
  - Security suite passes in CI
- Status: pending

### T84 — Documentation of the restructured system
- Requirements: SR-H3, SR-S1
- Depends: T83
- Deliverables:
  - SYSTEM_OVERVIEW, DATA_FLOW, AGENT_HARNESS, MODEL_BOUNDARY, CLI reference (Ink front end, plain mode, headless, E1, settings schema), deployment runbook, migration guide 1.x to 2.0; guide changes under `.laris/help` only with the owner's approval, then `laris harness verify` and `lock`
- Validation:
  - `validate_docs` passes; documents describe the flow of plan.md section 8
- Status: pending

### T85 — Release 2.0.0
- Requirements: SR-H5
- Depends: T84
- Deliverables:
  - Release branch, changelog, npm packages (main with the Ink front end, per-platform engine binaries with `uv`) and server images under the git flow
- Validation:
  - CI green; owner authorisation recorded for push, merge, tag and release
- Status: pending
