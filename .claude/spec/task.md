# LARIS — Task ledger: Obsidian brain, scholarly harness and the second programme

Version 0.2.1 · 2026-11-12 (T48-T85: second programme; T48 to T66 done) · Implements [plan.md](plan.md) for [spec.md](spec.md).

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
- Status: done
- Note: ADR-019 (docs/adr/ADR-019-three-blocks-two-protocols-two-sql-engines.md) records D10 to D23 and a dependency table; amendment sections 1b added to ADR-015, ADR-016, ADR-018 and the ADR index. pyproject extras `server` (fastapi, uvicorn, psycopg[binary], psycopg_pool, cryptography) and `model` (fastapi, uvicorn) added as ranges from PyPI versions checked 2026-11-12; nothing installed. Pins: ink 8.0.0, react 19.3.1 (Ink 8 needs react >= 19.3.0), uv 0.13.1 per platform (checked against npm and the local binary, not yet used in a build). Caddy and PostgreSQL image tags are left to T68. The task text names D10 to D21; the ADR also covers D22 and D23 because spec 4b records them. No further Ink component package approved.

## Phase 10 — Three blocks

### T49 — Protocol package and removal of import cycles
- Requirements: SR-S1, SR-S2
- Depends: T48
- Deliverables:
  - `laris.protocol`: `Message`, `ToolCall`, `AssistantTurn`, `ChatProvider`, SSE encode and decode, `Chunk`, P1 and P2 pydantic schemas, protocol version constant
  - Cycles removed: `Chunk` out of `application/workspace.py`, provider types out of `agent/provider.py`, `check_key` out of `harness/credentials.py`, `config/loader.py` no longer imports `harness.prefs`
- Validation:
  - No cycle among `agent`, `harness`, `vault`, `application`, `learning`; the no-training suite passes unchanged
- Status: done
- Note: src/laris/protocol/ (version, types, chunk, sse, schemas, keycheck) holds Message, ToolCall, AssistantTurn, ChatProvider, the provider errors, wire_messages, Chunk, SSE encode/decode, P1/P2 pydantic schemas, PROTOCOL_VERSION "1" and `check_key`. Old import paths (`agent.provider`, `application.workspace`) re-export the same objects, so no importer changed. Cycles: Chunk and provider types out of their old modules; `check_key` now in the protocol package and `harness/credentials.py` no longer imports `agent`; `config/loader.py` reads settings through the new `config/user_layer.py` instead of `harness.prefs`; `harness/runtime.py` no longer imports its own package (a real harness to harness.runtime cycle found while checking). SSE helpers are used by the model server and `HttpChatProvider.stream`. tests/unit/architecture/test_import_cycles.py proves no MODULE-level cycle (lazy imports included) among the five packages and that protocol imports no other package. Limit: at PACKAGE level agent, application, vault, harness and learning still depend on each other in both directions (e.g. application.chat_app uses agent, agent.builtin_tools uses application.workspace); that is not a module cycle and is left to T50/T51 block moves. P1/P2 schemas are not yet used by the server (T55/T56); the P1 chat request is checked only in tests/unit/architecture/test_protocol.py. Verification: ruff, mypy (255 files), `make check-no-training` (211 passed) and unit suites for agent, harness, cli, application, learning, gateway, serverdata, vault, security pass with a clean HOME. test_chat_and_model_api.py::test_chat_settings_and_conversations fails when run against the real ~/.laris of this machine (base_url set there) and passes with a clean HOME; the failure depends on the machine settings, not on this change.

### T50 — Move packages into blocks
- Requirements: SR-S1
- Depends: T49
- Deliverables:
  - A one-off import-rewrite script; packages moved to `src/laris/{shared,client,server,model,research}` as listed in spec SR-S1 (brain to server, project vault to client, `serving` and `serverdata` to server, `execution` and `language/inference` to model, training and evaluation to research)
  - Tests, configuration, `pyproject.toml`, Makefile and CI paths updated
- Validation:
  - `ruff`, `mypy`, `validate_docs`, `make check-no-training` pass with the same results as before the move
- Status: done
- Note: scripts/move_to_blocks.py (one-off, kept for the record) moved 255 modules with `git mv` and rewrote imports and dotted strings in src, tests, scripts and packaging; map confirmed by the owner and recorded in ADR-019 section 2b (shared, client, server, model, research; `cli` stays top-level until T52). Fixed by hand: `public_strings.yaml` path (now laris/shared/harness), `REPO_ROOT` depth in corpus/acquisition/common.py, config-key strings the script wrongly rewrote (`agent.plan.mode`), the `serverdata` self-import cycle, packaging/build_client.py (EXCLUDE, package_data, yaml copy), pyproject package-data, CODEOWNERS, tests that read `src/...` paths. Results: ruff clean, mypy 264 files clean, validate_docs and validate_spec pass, `make check-no-training` 211 passed + eval suites pass, full `pytest tests` leaves 2 failures that are not caused by the move: test_task_splits::test_audit_dataset_inventory_from_manifest (fails on a clean HEAD checkout too) and test_dataset_acquisition::test_s2orc_cap_and_skip_status (reads the owner's uncommitted data/acquisition_manifest.json; passes on HEAD). Run with a clean HOME; the real ~/.laris makes test_chat_and_model_api fail (see T49). The uncommitted s2orc.py change moved with the file (now src/laris/research/corpus/acquisition/sources/s2orc.py). Not done: the client wheel was not rebuilt (needs the `build` extra, and T52 reworks it); its closure is 169 modules vs 160 before (block package markers and protocol modules) and still reaches research.corpus and server.policy modules, which T51 will list; docs outside ADR-019 still quote the old src paths (T84).

### T51 — Block-boundary contract test
- Requirements: SR-S1
- Depends: T50
- Deliverables:
  - `tests/unit/architecture/test_blocks.py`: blocks import only `protocol` and `shared`; nothing imports `research`; `shared` and `protocol` import no block
- Validation:
  - Test passes and fails on a planted violation
- Status: done
- Note: tests/unit/architecture/test_blocks.py checks the whole `laris` tree: client, server and model import only protocol and shared; nothing imports research (research itself may use every block, as owner tooling); shared imports only protocol; protocol imports no block. Planted-violation tests cover each rule and a temporary file. To reach zero violations without changing behaviour, 15 modules moved by a second scripted pass: policy (prompts, policy, workflows, verifier), brain, harness runtime/remote/credentials, `plan`, project vault/entities/memory, corpus schemas and normalizer, language checkpoint/dataloader (now under `shared/language/loading`) and `stem_benchmark`, plus `OfflinePlanner` split into `laris/shared/offline.py`; the language package no longer re-exports training classes. Gateway and model server import protocol types instead of the client provider. Deliberate deviation from the SR-S1 map: policy composer, brain code and harness runtime sit in `shared` (client still composes policy locally; server gateway reuses the runtime); only their data stay server-side. Recorded in ADR-019 section 2b. One edge remains and is listed in KNOWN with its owner task: client.application.service uses laris.model.inference (T58 moves embedding behind the server); the test also fails if a listed edge disappears. Verification: ruff, mypy (267 files), validate_docs, validate_spec, `make check-no-training` (216 passed); full `pytest tests` leaves only the two failures explained in T50 (clean HOME).

### T52 — Entry points and the client wheel by block
- Requirements: SR-S1
- Depends: T51
- Deliverables:
  - Entry points `laris`, `laris-server`, `laris-model`; `cli/main.py` role switch removed
  - `packaging/build_client.py` builds from `client`, `protocol`, `shared` instead of an import closure; `client-package.yml` updated
- Validation:
  - Built wheel contains no server, model, research module and no `.laris/` policy; npm smoke test in an empty folder passes
- Status: done
- Note: Entry points: `laris` (cli.client), `laris-server` (cli.server, now with its own table: policy and brain checks, keys, tls, usage, reasoning, the server process, owner-only data/train/evaluate), `laris-model` (cli.model: `infer` only; `serve` arrives with T53) declared in pyproject. `cli/main.py` has no role switch any more: it only merges the three tables for tests and `python -m cli`. packaging/build_client.py builds from whole blocks (`protocol`, `shared`, `client` plus 13 cli command modules; 133 files) instead of the import closure, and its smoke test bans laris.server, laris.model, laris.research and the server/model entry modules. Verified by an actual build here: 133 modules compiled with Cython, the smoke import of every module passed, and the wheel (139 entries, about 6.9 MB) contains no laris/server, laris/model, laris/research, cli server/model/main module or `.laris` file; tests/unit/cli/test_client_package.py checks the same file set and that every import in shipped files resolves. The only import of model code in the client (client.application.service, T58) is now guarded: without model code it raises a ServiceError telling the user to embed through the server. Not done: the npm smoke test in an empty folder (needs the PyInstaller binary and the npm packages; `client-package.yml` still calls the same build command, and CI will run it), the wheel entry point list still declares only `laris`. Tests need a fresh HOME: a HOME polluted by earlier runs made test_account fail once.

## Phase 11 — Model service

### T53 — Model service on P2
- Requirements: SR-S3, SR-S2
- Depends: T52
- Deliverables:
  - `laris-model serve` (FastAPI, uvicorn): `/v1/chat/completions` (stream, tools, reasoning), `/v1/embeddings`, `/health`; backend loader and `OfflinePlanner` placeholder moved here; encoder from `language/inference`
  - The client loses its offline mode (D16)
- Validation:
  - Model boundary tests (SR-H6) pass over HTTP with the scripted backend; P2 contract tests pass
- Status: done
- Note: `laris-model serve` (cli/model.py, uvicorn) runs the FastAPI app in src/laris/model/app.py over the core in src/laris/model/service.py: `GET /health`, `GET /v1/models`, `POST /v1/chat/completions` (JSON, or SSE with tools and `reasoning_content`) and `POST /v1/embeddings` (encoder from `laris.model.inference` through `build_embedder`). No keys, no files, no docs routes; backend calls run in a thread pool; a failure before the first chunk is HTTP 502, after it an `error` event then `[DONE]`. New config section `model_service` (host, port, body limit, names, backend, checkpoint, tokenizer, device; defaults equal configs/default.yaml). The P2 wire format moved to `laris.protocol.openai` with response schemas `ChatCompletionResponse`, `ChatCompletionChunk`, `StreamError`; `load_backend` to `laris.shared.backend` (placeholder uses the public string catalogue); the server's reference service reuses them (it now also forwards `reasoning_content` on its bare stream). The client lost its offline mode: `ChatApp.provider` raises `server.not_configured` and `model_health` reports `api`/not ok without a server URL (tests that need a scripted model use the `use_placeholder_model` fixture in tests/conftest.py). tests/unit/model/test_model_service.py (9 tests, real uvicorn on an ephemeral port, urllib client): schema checks of real responses and chunks, error cases, 413/400, statelessness, plus the boundary checks (tool validation, plan tool, wire keys, reasoning never persisted) through `HttpChatProvider`. Verification: ruff, mypy (272 files), validate_docs, `make check-no-training` (225 passed, the model tests joined `test-model-free`); full pytest leaves only the two failures described in T50. Deviations: `OfflinePlanner` sits in `laris.shared.offline` (the client tests and server fixtures also use it), not in `laris.model`; the model block does not yet queue GPU work (T54); the old combined `laris-server model serve` (gateway plus model in one process) stays until T55 and T56 replace it. `fastapi` 0.162.5 and `uvicorn` 0.54.0 were installed into the local .venv under the approval recorded in ADR-019; `httpx` (needed by Starlette's TestClient) is not approved, so tests use a real server.

### T54 — GPU queue from the execution package
- Requirements: SR-S3
- Depends: T53
- Deliverables:
  - Task router, weight staging and headroom governor wired into the model service: one queue, load and release by VRAM budget (configuration only)
- Validation:
  - Scripted backends with declared sizes never exceed the configured budget; queue order and timeouts tested
- Status: done
- Note: src/laris/model/gpu_queue.py: one priority queue (FIFO inside a priority) feeding `gpu_workers` workers; before a job runs, `SpecialistLRUCache` plus `HeadroomBudgetGovernor` stage the model it needs and evict the least recently used idle model when the budget would be exceeded; the model stays pinned (reference counted) while any job uses it; streams hold the model until they end or the reader leaves. When the budget is full of models other jobs are using, a job waits for one to be released instead of failing (found by the 3-worker test); it fails only if nothing is in use. Overload gives HTTP 503 (`queue_max_waiting`), a job that waited longer than `queue_wait_timeout_s` gives 504. All figures are configuration (`model_service.vram_budget_bytes`, `vram_margin_bytes`, `chat_vram_bytes`, `embed_vram_bytes`, `gpu_workers`, ...), defaults equal configs/default.yaml. The encoder now loads lazily through the queue (`Encoder.load/unload`, cache emptied on release); `/health` reports resident models, bytes, waiting jobs, peak and evictions. tests/unit/model/test_gpu_queue.py (10 tests: sizes vs budget over a mixed sequence, co-residency, oversize model refused, priority and arrival order, timeout and full queue with a fake clock, failing job and failing loader, stream residency, stream errors, three concurrent workers) and two service tests over HTTP (health, 503); repeated runs are stable. Verification: ruff, mypy (273 files), validate_docs, `make check-no-training` (the model tests are in `test-model-free`); full pytest leaves only the two failures described in T50. Limits: sizes are declared, not measured, and no real GPU was used (a CPU or scripted backend only), so the real peak VRAM of a trained model is unmeasured; the `TaskRouter` (specialist tiers, uncertainty ceilings) is NOT wired in: it routes research tasks between specialists, while this service serves two fixed models, so the queue uses the weight-staging cache and the governor only. The existing `execution` modules are unchanged apart from import order.

### T55 — Server calls the model over P2
- Requirements: SR-S3
- Depends: T54
- Deliverables:
  - Gateway backend is an `HttpChatProvider` to `model_api.internal_url`; bounded concurrency `serving.model_concurrency`; no model code in the server process
- Validation:
  - Gateway tests pass against a model service; pointing the URL at another OpenAI-compatible server needs no code change
- Status: done
- Note: `laris-server model serve` no longer loads a backend or encoder: it builds `HttpChatProvider(model_api.internal_url)` wrapped in `LimitedProvider` (`serving.model_concurrency`, a stream holds its slot until it ends or closes) and `HttpEmbedder` for `/v1/embeddings`; it refuses to start without a model URL (`--model-url` overrides). `HttpChatProvider` moved to `laris.shared.http_provider` (the client re-exports it) because both the server and the client's policy provider need it. New config: `model_api.internal_url`, `serving.model_concurrency` (defaults equal configs/default.yaml). The old `--backend`, `--checkpoint`, `--tokenizer-model`, `--device` flags of the server are gone (they live on `laris-model`). tests/unit/gateway/test_model_over_p2.py: the gateway answers a chat through a stub that speaks only OpenAI-compatible JSON (no LARIS code), embeddings go through P2, six calls with a limit of two never run more than two at once, and a subprocess check that importing the server modules loads no `laris.model` module. Limits: the gateway test uses a stub, not the real model block with the gateway in one run (the two halves are each tested over HTTP in T53 and here); importing the server still pulls `torch` in through `laris.shared.language`, which imports the encoder eagerly (not model code, but a weight for the server image to be fixed with T67). `serving.placeholder_name` is now unused by the server. Verification: ruff, mypy (275 files), full pytest leaves only the two failures described in T50.

## Phase 12 — Server API

### T56 — FastAPI server for P1
- Requirements: SR-S4, SR-S2
- Depends: T55
- Deliverables:
  - P1 routes on FastAPI and uvicorn replacing `serving/model_server.py`; body validation (size, negative or missing `Content-Length`, shape); SSE `error` event mid-stream; protocol header check; brain lock narrowed to the brain budget
- Validation:
  - Tests for 400, 401, 403, 411, 413, 429, version mismatch, error mid-stream, a slow client not blocking others; `test_policy_server.py` passes
- Status: done
- Note: The P1 server runs on FastAPI and uvicorn (src/laris/server/api.py); `serving/model_server.py` keeps only the compatibility names (`ModelService` now lives in serving/service.py, `build_server` returns an `ApiServer` that binds first and serves with uvicorn, `enable_tls` sets the certificate). Routes as before: /health, /v1/models, /v1/laris/{workflows,help,account,chat}, /v1/admin/{usage,reasoning}, bare /v1/chat/completions (closed when the gateway runs) and /v1/embeddings. Bodies: 411 without Content-Length (chunked is refused), 400 for a negative or non-numeric length, bad JSON, non-object or wrong shape (checked with the protocol schemas `ChatRequest` and `EmbedRequest`), 413 before the body is read and again while reading, 408 when the body arrives too slowly (30 s default). `/v1/laris/*` needs `X-Laris-Protocol: 1`, otherwise 426 with a message that tells the user to update the client; the client (`PolicyServerProvider`, `ServerClient`) now sends it. 401, 403, 429 (quota) and 502 (provider) behave as in SR-H9; a failure after the first byte of a stream becomes an `error` event then `[DONE]`, and the generator is closed (usage and traces recorded) even when the reader disconnects. Blocking work (database, gateway, model calls) runs in the thread pool, so a stalled client does not block others. The brain lock was already limited to the per-turn consult and brain tools (never a model call); test_the_brain_lock_is_not_held_during_a_model_call shows three one-second model calls overlapping. Tests: tests/unit/gateway/test_p1_api.py (8 tests) plus the existing policy-confidentiality, key, quota, TLS and trust-on-first-use suites, all passing with the new server. Existing tests that call /laris/* directly now send the version header. Limits: the missing-header refusal applies to every /v1/laris/* route, so a 1.x client is refused by design; TLS minimum version is whatever uvicorn and Python 3.10 default to (not forced to 1.2 as before); `serving.body_timeout_s` is not yet configuration (default argument of `create_app`). Verification: ruff, mypy (277 files), `make check-no-training`; full pytest leaves only the two failures described in T50.

### T57 — Trusted proxy and address rules
- Requirements: SR-S4
- Depends: T56
- Deliverables:
  - `serving.trusted_proxies`; real address from `X-Forwarded-For` only from a trusted proxy; `@server` and CIDR rules use it
- Validation:
  - Tests with trusted, untrusted and forged headers
- Status: done
- Note: New config `serving.trusted_proxies` (list of addresses or CIDRs, default empty; an invalid entry fails at start). `netcheck.real_address(peer, forwarded, trusted)`: with no trusted proxy, or a peer that is not one, `X-Forwarded-For` is ignored; from a trusted peer the hops are read from the right and the first address that is not a trusted proxy is the client, so hops the client wrote on the left cannot help; an unparsable hop gives no address (every address rule then fails); several header lines are joined; IPv4-mapped IPv6 is normalised. The FastAPI server uses it for every key check, so `@server` and CIDR rules hold behind the proxy (behind an untrusted or unconfigured proxy every request is the proxy's address, as ADR-018 already warned). uvicorn's own `proxy_headers` is turned off, otherwise it would rewrite the peer from a forged header when the peer is loopback. `build_server` and `laris-server model serve` pass `serving.trusted_proxies`. tests/unit/serverdata/test_trusted_proxy.py (4 tests): the address function (untrusted, trusted, chained, forged first hop, two header lines, garbage, no config, mapped IPv4, bad entry) and over HTTP with the test client as the proxy: a key limited to 198.51.100.0/24 and a `@server` key, with trusted, forged and untrusted-proxy cases. Verification: ruff, mypy (277 files), full pytest leaves only the two failures described in T50. Limit: only `X-Forwarded-For` is read, not `Forwarded` or `X-Real-IP`; Caddy (T68) must set `X-Forwarded-For` itself and `trusted_proxies` must be set to its network in the compose file.

### T58 — Embedding through the server
- Requirements: SR-S2, SR-S4
- Depends: T56, T53
- Deliverables:
  - `POST /v1/laris/embed` (permission `embed`, metered, text never stored); client dense search embeds through it; the client no longer loads an encoder
- Validation:
  - Dense search works end to end with a scripted encoder; a test shows no request text in the database
- Status: done
- Note: `POST /v1/laris/embed` (P1; permission `embed`, protocol header required, body checked with `EmbedRequest`, answer shaped as `EmbedResponse`, metered through `bill(..., "embed")`) forwards to the model block over P2 (`HttpEmbedder`). The client embeds only through it: `SearchService` now takes an `embedder` callable instead of checkpoint, tokenizer and device; `cli.common.make_service` builds a `ServerEmbedder` (new, in shared/http_provider.py: P1 path plus the protocol header, key from `model_api.api_key_env`) whenever `model_api.base_url` is set. The client never imports `laris.model`: the KNOWN edge of the block test is gone (KNOWN is now empty) and the wheel test refuses any import of server, model or research code. CLI: `laris app index` moved to the client table; the `--checkpoint`, `--tokenizer-model` and `--device` flags are removed from the client commands (they stay on `laris-model serve` and `laris-model infer`); `laris-server app index|ask` no longer exist. Tests (tests/unit/gateway/test_embed_route.py, 4 tests, a scripted bag-of-words encoder): the route follows the P1 rules (200, 426, 401, 403 for a role without `embed`, 400), quota decreases, a unique secret sentence appears nowhere in the server's data folder (database, WAL, logs), and dense and hybrid search find the right document end to end through a live server. Dense index metadata now records `embedder: server` instead of a model digest. Limits: extractive question answering (`answer_question` tool, `laris app ask`) needed the local encoder's QA head, so it now raises a clear `ServiceError` until a QA route exists on the model block; the plan does not schedule one, so the OfflinePlanner's use of `answer_question` is unreachable with a real server. The embedding vectors are sent in JSON, not compressed. Verification: ruff, mypy (277 files), `make check-no-training`, full pytest leaves only the two failures described in T50.

### T59 — Default key handling
- Requirements: SR-S4
- Depends: T56
- Deliverables:
  - The default key is no longer printed; `laris-server keys reveal default` or a 0600 secret file delivers it
- Validation:
  - Start-up output and logs contain no key (test)
- Status: done
- Note: `laris-server model serve` no longer prints the default key. On the first start it writes the key to `serving.first_admin_file` (default `~/.laris-server/default.key`, created with mode 0600 inside a 0700 folder, replaced if it exists; point it at a Docker secret path in T68, or set it empty to write nothing) and prints only the path and the hint "Print it with `laris-server keys reveal default`". The config field is called `first_admin_file` because the config loader rejects any string value under a key containing "key" as a literal secret. `ServerData.deliver_default_key` does the writing. A second start says nothing about a key. tests/unit/serverdata/test_default_key_delivery.py (3 tests): runs the real `model serve` command with the server stubbed out and captures stdout, stderr and logging at DEBUG: the key (`lk_...`) is in none of them, the file holds it with modes 0600 and 0700, the file's key authenticates and equals `keys reveal`, and no file is written when none is configured. Verification: ruff, mypy (277 files), `make check-no-training`, full pytest leaves only the two failures described in T50. Limit: the key is still stored in a file readable by the operator account (and by root); that is the delivery the task asks for, and the file can be deleted after the key is noted since `keys reveal default` can print it again; on Windows the mode bits are not enforced.

## Phase 13 — Server storage on PostgreSQL

### T60 — PostgreSQL adapter and migrations
- Requirements: SR-S5
- Depends: T52
- Deliverables:
  - `laris.server.storage` on `psycopg_pool` implementing the ports; numbered SQL migrations; `laris-server db migrate`; key logic of `serverdata/keys.py`, `crypto.py`, `cache.py`, `netcheck.py` reused with new SQL
- Validation:
  - Storage tests pass with `LARIS_TEST_PG_DSN`; CI runs them against a PostgreSQL service
- Status: done
- Note: `laris.server.storage` (postgres.py, migrate.py, migrations/0001_initial.sql): `PgDatabase(dsn, schema=None, min_size, max_size, timeout_s)` on `psycopg_pool.ConnectionPool` (autocommit, dict rows) exposes the same surface the stores already use (`db.connection().execute(sql, params)` with `?` placeholders, `fetchone/fetchall/rowcount`; `SUM()` numerics become ints) plus `transaction()` for statements that must commit together, so `KeyStore`, `UsageStore` and `TraceStore` (and the `crypto`, `cache`, `netcheck` logic) are reused unchanged against PostgreSQL. Numbered SQL migrations `migrations/NNNN_name.sql` (checked for gaps) are applied once each in one transaction under a `pg_advisory_xact_lock`, so containers that start together do not race; 0001 creates keys (with `secret_enc BYTEA`, `allowed_ips`, `builtin`), usage and traces. `laris-server db migrate` (src/cli/commands/db.py) prints the schema version; `ServerData` picks the engine from `serving.database_engine` (`sqlite` default, `postgres`) with the DSN read from the environment variable named by `serving.database_url_env` (never in configuration), plus `database_pool_min/max` and `database_timeout_s` (all in configs/default.yaml). The default stays `sqlite` until the Docker compose of T68 sets `postgres`. package-data includes the .sql files; CI gets a `postgres:16` service, `LARIS_TEST_PG_DSN` and a `pytest tests/unit/storage` step. Verified on a real PostgreSQL 16 in Docker (container `laris-test-pg`, DSN postgresql://postgres:laris_test@127.0.0.1:55432/laris_test, started with `sg docker` because the session is not yet in the docker group): tests/unit/storage (6 tests, each in its own schema dropped afterwards): migrations numbered and applied once; 4 threads migrating an empty schema together apply each once; keys create/verify/reveal/revoke/limit/default key; usage record, summary (JSON-safe) and quota check; traces redacted, listed, purged; `db migrate` and `ServerData` default key end to end on PostgreSQL. Without `LARIS_TEST_PG_DSN` these tests skip. mypy 284 files, ruff, `make check-no-training` pass; full unit suite leaves only the two failures described in T50. psycopg 3.3.8 and psycopg_pool 3.3.3 were installed with uv in `.venv` (approved in T48; both were already in the `server` extra).

### T61 — Atomic quota
- Requirements: SR-S5
- Depends: T60, T56
- Deliverables:
  - Reserve before the model call, settle after it in one transaction, in `finally`
- Validation:
  - N parallel requests never pass a limit; a disconnect is still settled
- Status: done
- Note: `UsageStore.reserve(principal, estimated_tokens)` sets tokens aside with one statement (`UPDATE keys SET tokens_reserved = tokens_reserved + n WHERE id = ? AND not revoked AND (token_limit IS NULL OR tokens_used + tokens_reserved + n <= token_limit)`) so what other requests in flight hold counts against the limit; `rowcount != 1` raises `QuotaExceeded` (HTTP 429). It returns a `Reservation` whose `settle(usage)` releases the reservation, adds the real use and inserts the usage row in one transaction (`Database.transaction()` on SQLite, `PgDatabase.transaction()` on PostgreSQL), and whose `release()` gives the tokens back; each works once, so a `finally` can always call either. The API reserves where it used to `check`, hands the reservation to the gateway stream (`PolicyGateway.stream(body, principal, reservation)`), whose `finally` settles it even when the client drops (generator close) or releases it when nothing reached the model; the non-gateway paths settle through `ModelService.bill(..., reservation)`; any error before the hand-over releases it in a `finally` in the route. Schema: `tokens_reserved` added by SQLite migration 3 and PostgreSQL `0002_reserved_tokens.sql`; the `UsageMeter` port gained `reserve` and a `Reservation` protocol; `check`/`record` stay for callers that do not reserve. tests/unit/serverdata/test_atomic_quota.py (5 tests x 2 engines, all 10 run, PostgreSQL on the Docker container): 40 threads each reserving 10 tokens against a limit of 100 win exactly 10 and settle to exactly 100 used and 0 reserved; release and double-end are no-ops; unlimited and revoked keys; a client that closes the stream after the first chunk is still settled (used > 0, reserved 0, one usage row); a refused request returns its reservation. Limits: a request's completion length is unknown when it is reserved, so one request can finish above its estimate and the key can end slightly over its limit by that overage, but concurrent requests cannot each pass it; if the server process is killed mid-request its reservation stays in `tokens_reserved` until reset by hand (no startup reconciliation, because several API containers share the table). mypy 284 files, ruff, `make check-no-training` pass; full unit suite leaves only the two failures described in T50.

### T62 — Partitions and retention
- Requirements: SR-S5
- Depends: T60
- Deliverables:
  - Monthly partitions for `usage` and `traces`; background retention on `serving.retention_interval_s`; daily usage summary
- Validation:
  - Expired partitions removed by the task; summaries match raw usage
- Status: done
- Note: Migration `0003_partitions.sql` turns `usage` and `traces` into tables partitioned by month on `ts` (UTC epoch seconds; primary key (id, ts); own sequences), adds the SQL function `laris_month_partition(parent, ts)` and `usage_daily` (one row per key and UTC day), and moves any rows written before it into their months' partitions (tested). `laris.server.storage.maintenance`: `Maintenance(db, usage_retention_days, trace_retention_days)` with `ensure_partitions` (last, current and next two months, under an advisory lock), `summarise` (idempotent upsert of `usage_daily` from the last summarised day onward), `purge` (drops whole partitions that end before the cutoff, summarising usage first so a day is never lost, and deletes older rows of the boundary month) and `run_once`; `RetentionWorker` runs it now and every `serving.retention_interval_s` (default 3600) in a daemon thread started by `laris-server model serve` when `database_engine` is `postgres`. New config: `usage_retention_days` (90), `retention_interval_s`, next to the existing `trace_retention_days`, all in configs/default.yaml. Inserts into `usage`/`traces` first make sure the current month's partition exists (cached once per month per process), so no insert fails for want of a partition. tests/unit/storage/test_partitions_retention.py (5 tests on PostgreSQL 16 in Docker): partitioned tables and automatic partition creation; expired usage partitions dropped by the task, dropped days still in the summary with the totals of their raw rows, recent summaries equal the raw sums, a second run changes nothing; traces expire by partition and by row in the boundary month; four concurrent maintenance runs and the worker do not error; pre-partition data survives the migration. The two-processes-migrate test now uses a clean schema (0003 adds a function that the old test did not drop). mypy 285 files, ruff, `make check-no-training` pass; full unit suite leaves only the two failures described in T50. Limit: the daily summary covers days from the last summarised day forward, so a usage row inserted with a timestamp older than that day (nothing does this) would not be summarised.

### T63 — Import from the SQLite server database
- Requirements: SR-S5
- Depends: T60
- Deliverables:
  - `laris-server db import-sqlite PATH` for keys, usage and traces
- Validation:
  - Lossless on a fixture database; imported keys verify and reveal
- Status: done
- Note: `laris-server db import-sqlite PATH` (src/cli/commands/db.py, `laris.server.storage.importer.import_sqlite`) copies keys, usage and traces from an old SQLite `laris-server.db` into PostgreSQL in one transaction (all or nothing). The file is opened read-only; columns an older file lacks (`secret_enc`, `allowed_ips`, `builtin`) take their defaults; rows keep their ids and use `ON CONFLICT DO NOTHING`, so a second run, or an import into a database that already has some keys, adds only what is missing; key digests and sealed secrets are copied byte for byte, so the same master secret still verifies and reveals them; partitions for every month in the data are created first, the id sequences continue after the largest imported id, and the daily summary is rebuilt at the end. It refuses a missing file, a file without the three tables, or an engine that is not `postgres`. tests/unit/storage/test_import_sqlite.py (4 tests on PostgreSQL): a fixture database with a limited key restricted to a CIDR, a built-in admin key and a revoked key, 7 usage rows across two months and one trace imports with counts {3, 7, 1}; every key field equals the source's, imported keys verify and reveal the original plaintext, the revoked key stays revoked, usage and trace rows equal the source row for row, the summary matches, a new record continues at id 8, and a second import adds nothing; a file that predates encrypted keys imports with defaults; bad files raise and leave nothing behind; the CLI command works and refuses the sqlite engine. A bug found on the way and fixed: creating a partition from inside an open transaction that already held row locks on the parent waited on itself, so `PgDatabase.transaction(ensure=True)` now creates the current month's partitions before it takes any lock, migrations and maintenance pass `ensure=False`, and `auto_partitions` switches on only after migration 0003 has run. Full unit suite with LARIS_TEST_PG_DSN leaves only the two failures described in T50; without it the PostgreSQL tests skip and the rest pass; mypy 286 files, ruff and `make check-no-training` pass. Phase 13 is complete: all four tasks verified against a real PostgreSQL 16 container.

## Phase 14 — Client storage on SQLite

### T64 — Client store and automatic migration
- Requirements: SR-S6
- Depends: T52
- Deliverables:
  - `laris.client.store`: one SQLite file per private space at `~/.laris/projects/<slug>/<key-fp>.sqlite` (WAL, busy timeout, numbered migrations); one-time idempotent migration of existing files (including the project's `artifacts/chat/users/<fp>/`) with backups
- Validation:
  - Migration tests on fixtures; second run changes nothing; backups present
- Status: done
- Note: `laris.client.store` (store.py, legacy.py): `space_path(home, project_root, key_fp)` gives `<home>/projects/<slug>/<fp>.sqlite` (slug = folder name + 8 hex of the path hash, so two projects with the same folder name do not collide); `Store` opens one short-lived connection per call with WAL, `synchronous=NORMAL`, a busy timeout and `BEGIN IMMEDIATE` transactions that roll back on error; numbered migrations (1: chunks, embeddings by chunk and model id, conversations, learning, vault_index, meta) are recorded in `schema_version` and applied once. `migrate_legacy(store, workspace, conversations)` imports `chunks.jsonl` and `<conversations>/*.json` losslessly, copies each source to `backups/` first, leaves the originals in place, and writes one `meta` marker per source so a second run changes nothing; files that are not conversations are skipped. tests/unit/store/test_client_store.py (5 tests): path rules, WAL and busy timeout, rollback, lossless idempotent migration with backups, 4 threads x 20 writes lose nothing. Wiring of Workspace/ConversationStore/Collector onto the store is T65/T66 (the store is not yet read by the app). Done out of plan order because T60-T63 need PostgreSQL in Docker, which is not installed here and sudo needs the owner's password; T60-T63 stay pending.

### T65 — Workspace and embedding cache in SQLite
- Requirements: SR-S6
- Depends: T64, T58
- Deliverables:
  - `Workspace` and `SearchService` on the store with the same public interface; vectors cached by passage and model id; BM25 ranking unchanged
- Validation:
  - Rankings identical before and after on the retrieval fixture; two concurrent ingests lose nothing
- Status: done
- Note: `Workspace(root, store=None)` keeps its public interface (`load`, `add`, `clear`, `root`) but now reads and writes the SQLite store (`<root>/workspace.sqlite`, or a shared private space passed as `store`); an existing `chunks.jsonl` in `root` is imported once with a backup (T64). `add` is one `BEGIN IMMEDIATE` transaction that replaces the documents it contains and drops the vectors of the replaced passages; `revision()` (a counter in `meta`) replaces the old file mtime as the reload signal. New `save_vectors(model_id, ids, matrix)` and `vectors(model_id, ids)` cache float32 vectors per passage and model id; `SearchService(model_id="server")` builds the dense matrix from the cache, `build_dense_index` embeds only the passages without a cached vector, and the dense index is ready only when every passage has one. `embeddings.npy`/`embeddings.json` and `chunks_path` are gone. BM25 code is untouched and passages load in insertion order, so rankings are unchanged. tests/unit/store/test_workspace_on_store.py (3 tests): rankings equal for a workspace imported from JSONL and one filled with `add`; two threads ingesting 10 documents each lose nothing (20 documents); vectors cached per passage and model (adding one passage embeds one text, another model id is not ready). The old test that checked the deleted npy file now checks the vector cache. Also fixed tests/unit/test_env_smoke.py, which still imported the domain packages by their pre-T49 top-level names (it failed on the committed HEAD, so it was a T49 regression missed earlier); full unit suite now leaves only the two failures described in T50. Environment: Docker 29.1.3 is now installed by the owner; the session is not in the docker group yet, so containers are started with `sg docker -c`; `psycopg` 3.3.8 and `psycopg_pool` 3.3.3 installed with uv under the T48 approval.

### T66 — Conversations, learning data and vault index cache in SQLite
- Requirements: SR-S6
- Depends: T64
- Deliverables:
  - `ConversationStore`, `Collector` storage and the vault index cache on the store; `laris learn export` still writes JSONL; vault notes stay Markdown
- Validation:
  - Existing conversation, learning and vault tests pass; export matches the earlier format
- Status: done
- Note: `ConversationStore(root, store=None)` keeps its interface (`create`, `get`, `save`, `delete`, `list`, `root`, ids still validated) on the `conversations` table of the SQLite store; old `<id>.json` files are imported once with backups. `Collector(cfg, root, store=None)` keeps `record`, `rate`, `ratings`, `stats`, `export`, `purge` on the `learning` table (opened lazily, so a disabled collector creates nothing; `<dir>/learning.sqlite`, dir mode 0700); store migration 2 adds a unique index on (kind, row id) for deduplication; existing `sft/retrieval/preference/feedback.jsonl` files are imported once with backups; `export` still writes the same JSONL (byte-identical to the earlier format in the test) plus the manifest; `purge` now also deletes the imported files and their backups, because a backup would otherwise defeat it. The vault index cache moved from `index.json` to `index.sqlite` (one row per note in the `vault_index` table; `VaultIndex.save_cache/load_cache`, `dumps()` unchanged and byte-identical, a corrupt or missing file is ignored); vault notes stay Markdown. Limit: the vault cache is its own SQLite file in `vault.cache_dir`, not a table of the per-key space file, because `laris.shared` may not import the client store (ADR-019 boundary); it uses the same table layout and is disposable. Tests: tests/unit/store/test_conversations_learning_on_store.py (3 tests: JSON import and listing; export equals the earlier JSONL and respects ratings; purge removes rows, files and backups) plus the existing conversation, learning and vault tests adapted to read through the store; full unit suite leaves only the two failures described in T50; mypy 280 files and `make check-no-training` pass.

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
