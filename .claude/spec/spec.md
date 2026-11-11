# LARIS — System specification: Obsidian brain and scholarly harness

Version 0.1.0 · 2026-11-11 · Status: DRAFT for owner review · Replaces the retired `.agents/` ledger.

Companion files: [plan.md](plan.md) (phases and exit criteria) and [task.md](task.md) (task ledger).
Run `python scripts/validate_spec.py` after any change to the three files.

## 1. Purpose and scope

LARIS is a local-first RAG and agent system for scientific work. Release 1.3.1 delivers the harness:
chat and terminal front ends, tool loop, prompts, rules, workflows, skills, integrity lock, leak and
injection guards, autocompact, generated RAG skills and local fine-tune data collection.

This specification covers what comes next, in the owner's order: **finish the system harness first,
then return to the core reasoning model.** The model stays paused (section 9). Two goals drive the work:

1. An **Obsidian-compatible knowledge base is the brain of the whole system**: memory and a linked
   knowledge graph that every component uses for reasoning.
2. Six application directions are served by that harness:

| Direction | What it must do | Requirements |
|---|---|---|
| Literature mining | Analyse many papers: metadata, topics, trends, duplicates | SR-A1 |
| Research question answering | Answer from the user's documents with cited evidence | SR-A2 |
| Citation analysis | Extract citations, build the citation graph, rank and compare | SR-A3 |
| Scientific RAG | Retrieve and generate from papers with provenance | SR-A4 |
| Knowledge graph | Build and query a scholarly knowledge graph | SR-A5 |
| Scientific NLP | Extract scientific structure; measure it | SR-A6 |

Out of scope for this specification: training or fitting any model, changing weights, claiming model
qualification, cloud services, Obsidian Sync or Publish, and any dependency on the Obsidian desktop
application.

## 2. Findings from the Obsidian documentation

Read from the official help site on 2026-11-11 (data storage, internal links, properties, graph
view, vault creation, Obsidian CLI). These facts shape the design.

- A **vault is a plain folder** of Markdown files and subfolders; other editors and tools may edit it and
  Obsidian refreshes on external change. Nothing but the filesystem is needed to create one.
- `.obsidian/` in the vault root holds vault-specific settings (hotkeys, themes, plugins). The files
  `.obsidian/workspace.json` and `workspaces.json` change on every file open; when a vault is in Git
  they should be ignored.
- Do **not** create vaults inside vaults: internal links are local to one vault.
- **Links:** wikilinks `[[Note]]`, `[[Folder/Note]]`, `[[Note#Heading]]`, `[[Note#^block-id]]`,
  `[[Note|display]]`, and equivalent Markdown links (URL-encoded). Embeds use `![[...]]`. Characters
  `# | ^ : %% [[ ]]` in names may break links. Block ids contain only Latin letters, digits and dashes
  and are Obsidian-specific, not standard Markdown. A link to a missing note is allowed (unresolved).
- **Properties** are YAML at the top of the file. Names are unique per note and a property name has one
  type vault-wide: text, list, number, checkbox, date, date and time, tags. Nested properties and Markdown
  inside properties are not supported. Internal links in properties must be quoted
  (`link: "[[Note]]"`). Default properties are `tags`, `aliases`, `cssclasses`.
- **Graph view** draws notes as nodes and internal links as edges; node size grows with incoming links;
  filters cover tags, attachments, existing files only and orphans; a local graph shows neighbours to a
  chosen depth. Links, tags and properties are therefore the only inputs the graph needs.
- The **Obsidian CLI** needs a running desktop application, so the system must not depend on it. LARIS
  implements the file format itself and treats Obsidian as an optional viewer and editor.
- Not verified yet (tasks T02 and T11 verify before relying on them): behaviour of dot-prefixed folders
  in the file explorer, the exact `.obsidian/*.json` keys, JSON Canvas details, and licence terms for any
  redistribution. The licence page was not found; no Obsidian software is bundled.

## 3. Definitions

- **System brain**: LARIS's own curated Obsidian-format knowledge base (ontology, relation vocabulary,
  reasoning playbooks, concept maps). Internal and confidential. Read-only at runtime.
- **Project vault**: the user's Obsidian-format vault, created inside the user's own codebase on their
  machine and maintained by LARIS as they work. Visible and editable by the user.
- **Brain** (unqualified): the system brain and the project vault used together for reasoning.
- **Managed block**: a delimited region in a note that LARIS owns and may rewrite; text outside it is the
  user's and is never rewritten.

## 4. Architecture decisions (accepted by the owner's instruction on 2026-11-11, see ADR-014; each remains changeable)

| ID | Decision | Default | Reason |
|---|---|---|---|
| D1 | Project vault location | `vault/` at the project root (visible folder) | Obsidian opens any folder; hidden folder behaviour is unverified |
| D2 | Vault in Git | Tracked; ignore `.obsidian/workspace*.json`; notes with `private: true` are git-ignored | Matches the documentation advice and keeps reproducibility |
| D3 | Encryption at rest | Not in v1; documented threat model | Needs a new dependency (owner approval required) |
| D4 | Obsidian integration | File format only; no CLI, no plugin | CLI requires a running app |
| D5 | System brain distribution | Packaged data, integrity-locked, read through brain tools only | Keeps it confidential and tamper-evident |
| D6 | Auto-write policy | System-managed notes (sources, sessions, concepts) are written automatically inside managed blocks; free-form notes proposed by the model need approval | Derived metadata is safe; free text is not |
| D7 | Language | Note text follows the reply language; property names and types are English | Stable schema, Vietnamese content |
| D8 | Existing memory | `.laris/memory/*.md` migrates into `vault/Memory/`; `save_memory` keeps its API | One memory, no duplication |
| D9 | Runtime self-modification | Never changes the system brain; learnings go to the project vault and a proposals inbox for owner review | Prevents poisoning of the brain |

## 5. Requirements

Each requirement has acceptance criteria that tasks must verify. Task references live in task.md.

### SR-V1 — Obsidian-compatible vault format
The project vault and the system brain are plain Markdown folders that open in Obsidian without
conversion. Supported: wikilinks (note, folder path, heading, block, alias display), Markdown links,
embeds, YAML properties within the documented constraints, tags, attachments folder, minimal
`.obsidian/` configuration.
Acceptance: a golden fixture vault parses identically to the documented rules; generated notes contain no
nested properties, no unquoted links in properties and no forbidden filename characters; no code path
imports or launches Obsidian.

### SR-V2 — Vault parser and index
Parse every note into links (resolved, unresolved, ambiguous), backlinks, tags, properties, headings and
blocks; ignore links inside code; compute orphans; rebuild incrementally from file hashes into a
disposable cache; deterministic output.
Acceptance: same vault yields byte-identical index twice; changing one note updates only that note's
entries; cache deletion loses nothing; fixture cases for every link form pass.

### SR-V3 — Project vault bootstrap
The first time a user works in a project (first ingest, session or `laris vault init`), LARIS adds the
vault structure to that project: folders, templates, minimal `.obsidian/` config with graph colour
groups per note type, an index note and `.gitignore` entries. Idempotent; never overwrites user files;
refuses to nest a vault inside another vault.
Acceptance: running init twice changes nothing; an existing user vault is adopted without rewriting
notes; opening the result in Obsidian shows a connected graph.

### SR-V4 — Write-through memory and graph
Every unit of work adds linked notes with provenance: ingested sources, sessions (daily log), questions and
answers with citations, concepts and claims from extraction, decisions and analyses. LARIS writes only
inside managed blocks (or new files it owns), detects user edits by hash, preserves them, and writes
atomically with size and rate limits.
Acceptance: user edits outside managed blocks survive 100 consecutive rewrites in a property test; a
crash during write leaves the previous file intact; every Q&A note links to its source notes.

### SR-V5 — Schema and naming
A config-driven registry defines note types (Source, Concept, Claim, Method, Dataset, Metric, Question,
Answer, Session, Decision, Analysis, Memory, MOC), required properties, relation properties (links in
properties) and filename rules, with stable ids and aliases.
Acceptance: a note failing its schema is reported by `laris vault check`; filenames are sanitised
deterministically and collisions get stable suffixes; renames keep aliases.

### SR-V6 — Unified memory
Memory, compaction summaries and session logs are stored in the project vault. `save_memory` and the
prompt memory section read and write vault notes; old `.laris/memory` files migrate once, losslessly.
Acceptance: migration is reversible and idempotent; memory shows in Obsidian's graph; the prompt memory
section stays within its configured size.

### SR-B1 — Protected system brain
The system brain is a separate vault that file tools cannot read, list or write; only dedicated brain tools
reach it; it is covered by the integrity lock and is read-only at runtime; its location comes from
configuration or packaged data, never from model input.
Acceptance: attempts through `read_file`, `list_files`, `ingest_path`, `save_skill` and path tricks
(traversal, symlinks, encodings) are denied; a changed brain note stops the session like any protected file.

### SR-B2 — Brain content
The curated brain contains: ontology and relation vocabulary, glossary, concept maps for the six
directions, reasoning playbooks (how to decide, verify and stop), tool/skill/workflow map and
evaluation rubrics. Written by the owner, versioned, reviewed.
Acceptance: every note has type and version properties; links resolve; each direction has a playbook;
content passes `laris vault check` and a no-secrets scan.

### SR-B3 — Brain confidentiality
Brain text counts as confidential for leak detection; excerpts returned by brain tools are marked
`internal`, budgeted and redacted; outputs may use the knowledge but never reproduce it verbatim; audit
logs record note ids only; brain content never goes to a non-loopback endpoint (extends rule C-4).
Acceptance: adversarial extraction suite (direct request, paraphrase, translation, encoding, step-by-step
leak, injected document) produces no verbatim brain shingles above the configured limit.

### SR-B4 — Brain-assisted reasoning
Research tasks consult the brain (system brain plus project vault) before answering through graph-aware
retrieval: lexical search, link-neighbourhood expansion and corpus evidence, fused deterministically.
The consult step is configurable, audited and visible to the user as a short trace of note titles.
Acceptance: on the fixture corpus, graph-aware retrieval is measured against BM25 alone; every answer
cites sources; trace lists notes used without revealing internal text.

### SR-B5 — Learning without self-modification
Runtime learnings are written to the project vault and to a proposals inbox; changes to the protected core
brain happen only by owner-approved release. New knowledge (from ingested documents or taught by the user)
is added by domain under `vault/Knowledge/<domain hub>/` and shown beside the matching hub; skills are
created only on the user's request, never on ingestion. A review command shows, accepts or rejects proposals.
Acceptance: no code path writes to the system brain at runtime; proposals carry provenance and are
excluded from retrieval until accepted.

### SR-B6 — Progressive disclosure (hub-to-leaf navigation)
The brain is never loaded or scanned whole. Reasoning enters at one small root note (`Brain Index`, at most
`brain.root_budget_tokens`), follows typed links parent to child (root, domain hub, topic hub, leaf) and
opens only the notes the current task needs. Structure is designed, not discovered by search:
- Fixed levels: L0 root, L1 domain hubs (one per direction plus tools, policy, evaluation), L2 topic hubs,
  L3 leaf notes. Each hub lists its children with a one-line purpose and a `when` trigger, so choosing a
  child needs no search.
- Every note has `type`, `domain`, `level`, `parent`, `children`, `related` (typed relation from the
  relation vocabulary), `summary` (at most 2 sentences) and `requires` (prerequisite notes). A leaf is
  reachable from the root by at most `brain.max_depth` hops; every note has exactly one primary parent.
- Navigation tools return summaries and ids first; full text is opened only by id, per-turn and
  per-note budgets apply, and already-opened ids are not repeated in a turn.
- Entry routing is deterministic: task type or workflow name maps to a domain hub through the routing
  table kept in the root note; free-text search is a fallback, not the default path.
- Lint enforces the structure: no orphan, no note beyond max depth, no hub with more than
  `brain.max_children` children, no child without a parent link, summaries present, links resolve.
Acceptance: on the fixture, a representative task for each direction reaches its playbook in at most
`brain.max_depth` navigation steps without search; tokens consumed per consult stay under the configured
budget and are reported; structural lint fails on a seeded orphan, over-wide hub and missing summary.

### SR-A1 — Literature mining
Extract bibliographic metadata (title, authors, year, DOI, arXiv id), find duplicates and near-duplicates,
report term frequencies and trends over time, group similar documents, and expose a corpus overview tool
and a Source note per document.
Acceptance: metrics reproduce on a fixture corpus; duplicate detection reports precision and recall on
labelled pairs; every statistic names its corpus scope.

### SR-A2 — Research question answering
Answer questions only from retrieved evidence with `[source #rank]` citations, stated assumptions and
uncertainties, and the absence-of-evidence rule; store the answer as a linked note.
Acceptance: existing `grounded-qa` checks still pass; answer notes link every cited source; unsupported
statements are marked.

### SR-A3 — Citation analysis
Extract in-text citations and reference lists (numeric, author-year, DOI, arXiv), resolve them to documents
in the corpus, build the citation graph, and report in-degree, out-degree, co-citation, bibliographic
coupling and centrality, with unresolved references listed.
Acceptance: fixture papers with known reference lists reproduce expected edges; ambiguous matches are
flagged, never guessed.

### SR-A4 — Scientific RAG
Hybrid retrieval (BM25 now, dense when a model is qualified) plus graph expansion and fusion, passages
with character-span provenance, and generation limited to retrieved evidence.
Acceptance: retrieval metrics (recall@k, MRR, nDCG) are computed by the harness on a frozen fixture;
dense channel stays labelled not qualified.

### SR-A5 — Knowledge graph
Build a scholarly graph from the vault and extraction (documents, authors, concepts, methods, datasets,
metrics, claims, limitations; edges cites, uses, evaluated-on, reports, supports, limits) with provenance;
query neighbours, paths and subgraphs; export JSON, GraphML and an Obsidian canvas.
Acceptance: exports validate against their formats; every edge has provenance; queries are deterministic.

### SR-A6 — Scientific NLP
Keep rule-based extraction of claims, methods, datasets, metrics, limitations and formulas, link outputs to
spans, and measure them on labelled fixtures. No claim of model capability.
Acceptance: precision, recall and F1 per type are reported by the harness; regressions fail tests.

### SR-H1 — Security of vault and brain inputs
Defend against path traversal, symlink and junction escape, embed or link resolution outside the vault,
oversized or hostile YAML, prompt injection through notes and documents, secrets in notes, and filename
tricks. Notes derived from documents are untrusted data (rule U-1).
Acceptance: dedicated security suite passes in CI; threat model document lists each threat with its
control and test.

### SR-H2 — Model-free evaluation harness
Measure retrieval, citation checks, extraction, leak and injection resistance and vault round-trips with
fixtures and no model.
Acceptance: one command runs the suite; results are reproducible and stored as reports outside the
specifications.

### SR-H3 — User experience
Terminal and web front ends expose the vault: init, check, open note, search, graph export, proposals;
`/how-to-use` documents it; messages follow the string catalogue; nothing is hardcoded.
Acceptance: every new command appears in the guide and passes the guide-coverage test.

### SR-H4 — Performance and scale
Targets (to be measured and then fixed as budgets): full index of 10,000 notes in 30 s or less, incremental
update of one note in 1 s or less, resident memory under 500 MB, BM25 search P95 under 300 ms at 10,000
notes, on the development workstation.
Acceptance: benchmark script records results; a regression over 20 percent fails the check.

### SR-H5 — Process and release
The three ledger files stay consistent (`scripts/validate_spec.py`); changes go through pull requests,
CI and the documented release flow; policy files stay under the integrity lock.
Acceptance: validator and CI pass; release 1.4.0 follows the git flow.

### SR-H7 — Local data plane and authenticated server
The user's disk is the system's database and the user's machine is its sandbox. Documents, vault,
skills, memory, conversations, uploads, collected data and every tool run (file access, OCR, ingestion,
extraction, writes) stay on the user's machine. The server only authenticates the API key and runs the
model on the messages of a request; it keeps no user data, writes no files and logs no content. The
server refuses to start without accepted keys, rejects any other key with HTTP 401, and the client checks
its key at login and at start. Everything sent to the server (system prompt, brain brief, tool results)
is internal data sent to the owner's own server, so remote use is an explicit configuration
(`model_api.allow_remote`).
Acceptance: the serving package cannot import tools, vault, learning or application code and writes no
files (contract test); wrong, missing or empty keys get 401; the server does not start with no keys; a
rejected key is never saved by `laris login` and stops a chat session with a clear message.

### SR-H6 — Model boundary
The harness depends on the model only through `ChatProvider`, the embedder callable and configuration; the
core model remains paused; resumption criteria and the owner gate are written down. No agent run trains,
fits or optimises anything.
Acceptance: contract tests use a scripted provider; resume criteria document exists; the training
prohibition stays in `AGENTS.md`.

## 6. Cross-cutting rules

- Policy precedence and confidentiality rules in `LARIS.md` and `.laris/rules/` apply to every new
  component; a new component may add stricter rules, never weaker ones.
- Every limit, path, pattern and message is configuration or string catalogue (rule G-2).
- No new dependency without the owner's approval recorded in the task.
- Measured results go to reports, not into specifications.
- The foundation model is NOT QUALIFIED; answers say so where it matters (rule L-1).

## 7. Notes layout of the project vault (informative)

```text
vault/
  00 Index.md                 map of content
  Sources/                    one note per ingested document
  Concepts/                   entities: methods, datasets, metrics, terms
  Claims/                     claims and limitations with provenance
  Questions/  Answers/        research Q&A with citations
  Sessions/                   daily log of work
  Decisions/  Analyses/       decisions and analysis results (citation, trends, graphs)
  Memory/                     migrated memory notes
  _inbox/                     proposals awaiting owner review (excluded from retrieval)
  _templates/                 note templates
  .obsidian/                  minimal configuration (graph colour groups, wikilinks on)
```

## 7b. Layout of the system brain (informative, hub tree)

```text
Brain Index (L0)            routing table: task type / workflow -> domain hub; <= root budget
  Literature Mining (L1) -> Topic hubs (L2) -> leaf notes (L3: playbook, rubric, relation, glossary term)
  Research QA (L1)
  Citation Analysis (L1)
  Scientific RAG (L1)
  Knowledge Graph (L1)
  Scientific NLP (L1)
  Tools and Workflows (L1)  Policy Boundaries (L1)  Evaluation (L1)
```

Reasoning enters at L0, follows `children` to the one L1 hub that matches, then to the needed leaf; `requires`
and typed `related` links add prerequisites and neighbours. Nothing else is read (SR-B6).

## 8. Threat model summary (details in T03)

Assets: system brain, project vault contents, credentials, policy files. Attackers: hostile documents,
hostile notes, a manipulated model, a curious tool call. Local administrator access is out of scope.
Controls: deny-lists and brain-only access, integrity lock, path confinement, leak and injection guards,
redaction, read-only system brain, proposals inbox, loopback-only egress.

## 9. Core model (paused)

The model work resumes only after the exit criteria of phases 1 to 6 hold and the owner opens the gate
(task T39). Until then the offline planner and scripted providers are used in tests. Resumption does not
relax any gate in `docs/specifications/` or any rule in `AGENTS.md`.

## 10. Task progress index

The authoritative status of every task is in task.md. Phase 0: T01-T40. Phase 1: T05-T10. Phase 2:
T11-T17. Phase 3: T18-T23. Phase 4: T24-T26. Phase 5: T27-T32. Phase 6: T33-T37. Phase 7: T38-T39.
