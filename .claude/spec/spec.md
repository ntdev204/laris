# LARIS — System specification: Obsidian brain, scholarly harness, three-block system and terminal client

Version 0.2.1 · 2026-11-13 · Status: phases 0-6, 8 and 9-17 up to T84 IMPLEMENTED; owner gates open (T38 review, T39 decision); T85 (release 2.0.0) in progress · Replaces the retired `.agents/` ledger.

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

**Second programme (owner instruction, 2026-11-12).** An analysis of the running system found client,
server and model code mixed together (cyclic packages `agent`, `harness`, `vault`, `application`,
`learning`; the gateway importing the agent; the encoder loaded on both sides; `execution/` wired nowhere;
the client wheel cut by an exclusion list), a server on `http.server` with blocking TLS handshakes, an
unchecked negative `Content-Length` and broken error replies mid-stream, a non-atomic quota and
start-only trace retention, and client storage that rewrites whole JSON/JSONL files without locks. The
owner authorised a restructuring of the code and of the operating flow: three blocks (client, server,
model) with two versioned protocols, PostgreSQL on the server and SQLite on the client, Docker on one
server machine, and a terminal client that works like Claude Code. Sections 4b and 5b specify it; phases
9 to 17 of plan.md implement it. The core model stays paused and NOT QUALIFIED.

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

## 4b. Architecture decisions of the second programme (owner instruction, 2026-11-12; recorded in ADR-019 by T48)

| ID | Decision | Choice | Reason |
|---|---|---|---|
| D10 | System blocks | Three blocks: **client** (user machine), **server** (API, policy, brain, keys), **model** (inference on the GPU); plus `protocol` and `shared` libraries and owner-only `research` tooling | Boundaries become structure instead of a build-time exclusion list |
| D11 | Package layout | Packages grouped by block under `src/laris/{protocol,shared,client,server,model,research}`; blocks import only `protocol` and `shared`; nothing imports `research` | Chosen by the owner over an ownership map; enforced by a contract test |
| D12 | Protocols | P1 client-server (public, HTTPS + SSE, versioned by `X-Laris-Protocol`); P2 server-model (internal Docker network, OpenAI-compatible chat completions and embeddings) | Client and model can change independently; an external inference runtime can replace the model block |
| D13 | Storage | PostgreSQL for the server (keys, usage, traces); SQLite for the client (conversations, workspace, embedding cache, learning data, vault index cache); vault notes stay Markdown files | Concurrency, atomic quota and retention on the server; locking and incremental writes on the user's disk |
| D14 | Deployment | One server machine; `docker compose` with Caddy (TLS, timeouts, body limit, rate limit), API, model (GPU) and PostgreSQL; the client is not containerised and still ships through npm | The owner has one server; the client must run where the user's files are |
| D15 | Dependencies approved | Server and model: `fastapi`, `uvicorn`, `psycopg`, `psycopg_pool`; Caddy and PostgreSQL as container images. Client (approved 2026-11-12): `ink` 8.0.0, `react` 19.3.1 (Node front end; pinned in ADR-019); `prompt_toolkit` and `rich` were approved and then dropped with the Python front end (D22). Sandbox provisioning (approved 2026-11-12): the `uv` 0.13.1 single binary, shipped in each per-platform npm package, fetches the standalone Python and builds the sandbox. **Confirmed in T48:** no further Ink component package is approved; the front end uses `ink` and `react` only at run time until the owner names another. **Approved in T81 (2026-11-12), dev only:** `typescript` 7.0.2, `@types/react` 19.3.0, `@types/node` 26.6.6, `ink-testing-library` 4.0.0. `ink` 8.0.0 needs Node 22, so the npm package requires Node >=22 (owner decision) | Rule: no dependency without recorded approval |
| D16 | Model placement | No offline mode in the client; `OfflinePlanner` moves to the model block as the placeholder backend and a test fixture; embeddings are computed only by the model block and reached through `POST /v1/laris/embed`; the client never holds weights | One place loads weights and manages VRAM; the thin client stays thin |
| D17 | Terminal client | `laris` works like Claude Code: full terminal interface, slash commands, one global settings file, permission modes and rules, coding tools with diffs and checkpoints, headless mode, hooks, status line, interrupt, automatic sandbox. One engine and the Ink front end (D22). Subagents, MCP and IDE integration are later work | Owner instruction |
| D18 | Global client home | `~/.laris/` holds **every** client configuration, setting, credential and per-project state (`settings.json`, `.credentials.json`, `projects/<slug>/`), plus personal `LARIS.md`, `skills/`, `commands/`, `memory/` | One place for system configuration; nothing configurable leaks into users' repositories |
| D19 | Program and sandbox kept apart | **Program**: the `laris` engine is the self-contained PyInstaller binary shipped in the per-platform npm package `@ntdev204/laris-cli-<platform>` (no Python needed on the machine; extras such as OCR are bundled at build time; nothing installs into it at run time); the Ink front end is JavaScript in the main npm package. **Sandbox** `~/.laris/.venv/`: where every command the agent runs on the user's behalf executes (`Bash`, `!command`, hooks, scripts it writes) and the only place packages are installed. Nothing is installed into the system or user Python. The legacy `~/.laris/runtime/<version>/` of 1.x is removed | Work in the sandbox can never break the program; the client machine stays unaffected |
| D20 | Project folder | `./.laris/` in a project holds only what the user adds: `LARIS.md`, `skills/`, `commands/`, `memory/`. It holds no `settings.json`, `settings.local.json` or `config.yaml`; such files are ignored with a warning | A cloned repository cannot change permissions, hooks, server or model |
| D21 | Server address and login | The server address lives in `~/.laris/settings.json` (`server.url`); `laris login` takes no `--server` flag, only asks for the key and checks it against `server.url`; the key goes to `~/.laris/.credentials.json` (0600), never into `settings.json` | Same model as Claude Code: settings declare, login authenticates |
| D22 | Engine and one front end | One engine (`laris engine --stdio`, Python, in the binary) owns the loop, tools, permissions, settings, commands, sandbox and storage; the front end only renders and collects input over the versioned engine protocol E1 (JSON lines both ways; the same stream as headless `stream-json`). The front end is **Ink + React**, started by the npm `laris` command. The prompt_toolkit + rich front end was dropped (owner, 2026-11-12): every install has Node, so a second interface is not worth its cost. Fallbacks need no dependency: headless `laris -p` for scripts and CI, and `laris --plain`, a minimal plain-text mode of the engine (`input`/`print` over E1) for debugging when the Ink front end fails | The prettiest interface without rewriting the core; one interface to build and test |
| D23 | Automatic sandbox | The user never creates or manages the sandbox. The engine prepares it in the background at start and checks it before every sandbox use; when it is missing or broken it builds or repairs it silently (standalone Python per `sandbox.python`, else a suitable system Python, both through the bundled `uv`), installs the packages the agent needs there without asking (default `allow`; installs elsewhere stay denied), and reports only a short status-line hint while doing so | Owner instruction: the user only enjoys the result |

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
ADR-016 amends this: the system policy (prompt, rules, workflows, brain) is held and applied by the server's
policy gateway and never reaches the client; the client keeps tools and user data. The gateway imports no
user-data code and writes no files (contract test).
Acceptance: the serving package cannot import tools, vault, learning or application code and writes no
files (contract test); wrong, missing or empty keys get 401; the server does not start with no keys; a
rejected key is never saved by `laris login` and stops a chat session with a clear message.

### SR-H9 — Managed keys, quotas and private reasoning
The server keeps a database of API keys (digest only) with roles, permissions, token quotas (or unlimited),
expiry and revocation, meters token use, and stores the model's reasoning for the operator only. No route
returns reasoning to a client or to an admin key unless `serving.reasoning_http` is enabled, and chat routes
never do. A new key is accepted by the running server at once.
Acceptance: tests/unit/serverdata (lifecycle, 401/403/429, unlimited, reasoning absent from every chat body,
digest-only storage).

### SR-H8 — Layers and the Agentic requirement
The runtime is layered loop -> harness -> prompt (the loop runs inside the harness; the harness composes the
prompt; the prompt layer knows neither) and the system climbs LLM -> RAG -> Agent -> Agentic (ADR-017). The
system must reach Agentic: visible plan, tracked and resumable progress, reflection with bounded replanning,
a completion check, memory in the vault, and bounded autonomy, all demonstrated on scripted scenarios that
need no trained model. The model stays NOT QUALIFIED; no capability claim exceeds what was measured.
Acceptance: the layer contract test passes (T42); the scripted Agentic scenario suite passes (T46).

### SR-H6 — Model boundary
The harness depends on the model only through `ChatProvider`, the embedder callable and configuration; the
core model remains paused; resumption criteria and the owner gate are written down. No agent run trains,
fits or optimises anything.
Acceptance: contract tests use a scripted provider; resume criteria document exists; the training
prohibition stays in `AGENTS.md`.

## 5b. Requirements of the second programme

These requirements amend SR-H7 and SR-H9 where they conflict: the server keeps keys, usage and reasoning
traces in PostgreSQL (never user documents, vault, skills, memory or conversations), and document text sent
for embedding is processed in memory and never stored.

### SR-S1 — Three blocks with structural boundaries
Code is grouped by block under `src/laris/`: `protocol` (wire types and schemas), `shared` (core types,
configuration loading, redaction and guard primitives, string catalogue, vault note parser and index),
`client`, `server`, `model`, and `research` (corpus, training, benchmarks, evaluation; owner-only, shipped in
no image or wheel). `client`, `server` and `model` import only `protocol` and `shared`; no block imports
`research`; the cycles between `agent`, `harness`, `vault`, `application` and `learning` are removed
(`Chunk` and the provider types move to `protocol`). Each block has its own entry point (`laris`,
`laris-server`, `laris-model`); the client wheel is built from `client`, `protocol` and `shared` only.
Acceptance: a block-boundary contract test passes next to the layer test (T42); the client wheel contains no
server, model or research module and no `.laris/` policy; behaviour is unchanged (the no-training suite passes
before and after the move).

### SR-S2 — Versioned protocols P1 and P2
P1 (client to server, public): `POST /v1/laris/chat` (SSE), `POST /v1/laris/embed`, `GET /v1/laris/workflows`,
`/help`, `/account` and the `admin` routes, described by pydantic schemas in `protocol` and versioned by the
header `X-Laris-Protocol`; a server answers an unsupported version with a clear error. P2 (server to model,
internal network only): OpenAI-compatible `/v1/chat/completions` (stream, tools, reasoning) and
`/v1/embeddings`. A failure after a stream has started is sent as an `error` event followed by `[DONE]`,
never as a second response.
Acceptance: contract tests validate real SSE chunks of P1 and P2 against the schemas; version mismatch, error
mid-stream and closed bare endpoints are tested.

### SR-S3 — Model service
The model block runs as its own process (`laris-model serve`, FastAPI and uvicorn) and is the only place that
loads weights: the chat backend (`package.module:ClassName`, default the `OfflinePlanner` placeholder) and the
language encoder. A GPU queue built on `execution` (task router, weight staging, headroom governor) loads and
releases models within the VRAM budget of one machine. It stores nothing and knows nothing about keys, users or
policy. The server calls it through `HttpChatProvider` with a bounded concurrency.
Acceptance: model boundary tests (SR-H6) pass against the service over HTTP; a scripted backend shows the queue
never exceeds the configured VRAM budget; the server works unchanged when the model URL points to another
OpenAI-compatible runtime.

### SR-S4 — Hardened server API
The server API runs on FastAPI and uvicorn behind a reverse proxy. Request bodies are validated (size, a
negative or missing `Content-Length`, JSON shape) before any work; permissions, quota and the policy gateway
behave as in SR-H9; the brain lock covers only the brain's per-turn budget, never a model call; the real client
address is taken from `X-Forwarded-For` only when the request comes from `serving.trusted_proxies`, so key
address rules (`@server`, CIDR) still hold behind the proxy; the default key is never printed to standard output
or logs.
Acceptance: tests for 400/401/403/411/413/429, error mid-stream, a slow client not blocking others, address
rules behind a trusted and an untrusted proxy, and the policy-confidentiality tests of
`tests/unit/gateway/test_policy_server.py`.

### SR-S5 — Server storage on PostgreSQL
Keys, usage and traces live in PostgreSQL through the ports of `serving/ports.py`, with numbered SQL migrations
and a connection pool. Quota is reserved atomically before a model call and settled in one transaction after it
(also on disconnect), so parallel requests cannot exceed a limit by more than one request's reservation error.
`usage` and `traces` are partitioned by month; retention runs in a background task on a configured interval;
a daily usage summary exists. `laris-server db migrate` applies migrations and `laris-server db import-sqlite`
moves an existing `laris-server.db`. The DSN and secrets come from the environment or Docker secrets; the key
master secret stays outside the database.
Acceptance: storage tests run when `LARIS_TEST_PG_DSN` is set (CI uses a PostgreSQL service); a concurrency test
shows N parallel requests never pass the limit; retention removes expired partitions; the import is lossless on a
fixture database.

### SR-S6 — Client storage on SQLite (in the global home, D18)
Each private space (per project and key fingerprint) has one SQLite file in the global home,
`~/.laris/projects/<project-slug>/<key-fingerprint>.sqlite` (WAL, busy timeout, numbered migrations), holding
conversations with their plan, workspace passages, the embedding cache (vectors keyed by passage and model id),
collected learning examples and the vault index cache. Vault notes stay Markdown files and remain the source of
truth. Ranking keeps the measured BM25 channel; only storage changes. Existing JSON, JSONL and NumPy files
migrate automatically once, idempotently, with the originals kept in a backup folder. `laris learn export`
still writes JSONL; collected data stays outside Git.
Acceptance: migration from fixtures is idempotent and keeps backups; BM25 rankings are identical before and after;
two processes writing at once lose no update.

### SR-S7 — Deployment on one machine with Docker
`docker/` holds an API image (slim Python, non-root), a model image (CUDA base, inference only), a Caddyfile and
`compose.yaml` with `caddy`, `api`, `model` (GPU reservation) and `postgres`. Only Caddy publishes ports; `api`,
`model` and `postgres` share an internal network. The system `.laris/` policy is mounted read-only into `api`
and its integrity lock is checked at start; weights are mounted read-only into `model`; PostgreSQL has its own
volume; secrets come from Docker secrets. Caddy terminates TLS, flushes SSE immediately and enforces body size
and timeouts. A backup script and an operator runbook exist. Nothing confidential is baked into an image.
Acceptance: `docker compose config` validates; a smoke test (empty folder, fresh home) logs in, chats with the
placeholder and runs a dense search through the stack; images contain no `.laris/` policy and no weights.

### SR-C1 — Interactive terminal (Ink front end)
The Ink front end (D22) offers: multi-line input, history and history search, streamed Markdown rendering with code
highlighting, a spinner while working, approval dialogs with diffs, a status line (model, permission mode, context
use, tokens left from `/v1/laris/account`, git branch, sandbox state), Esc to interrupt a running turn (the engine
closes the stream; the server still bills in `finally`), Ctrl+C twice to exit, and typing the next message while the
agent works. `laris --plain` starts the dependency-free plain-text mode of the engine instead (D22).
Acceptance: the scripted scenarios (input, interrupt, approval, status line, slash commands) pass through the Ink
front end against a recorded engine, and the same scenarios pass in plain mode and headless where they apply; an interrupted turn leaves a consistent saved conversation.

### SR-C2 — Commands, settings and input
A slash-command registry provides the built-in commands (`/help /clear /compact /resume /continue /model
/status /cost /context /config /permissions /memory /init /login /logout /doctor /vault /skills /workflows
/hooks /sandbox /exit`) and custom commands from `~/.laris/commands/*.md` and `./.laris/commands/*.md` with
`$ARGUMENTS`. Settings come from one file, `~/.laris/settings.json` (SR-C6), overridden for one run by
environment variables and command-line flags; no project file contributes settings. `laris config get|set` and
`/config` edit it. Input supports `@path` mentions with completion, `!command` (shell, approved), `#
note` (quick memory) and pasted long text or images (local OCR).
Acceptance: unit tests for the registry, custom commands, settings precedence and each input form.

### SR-C3 — Permission modes, rules and coding tools
Permission modes `default` (ask), `acceptEdits` and `plan` (read-only); `bypass` only when the policy allows it.
Rules `allow`, `ask`, `deny` match a tool and a pattern (`Edit(src/**)`, `Bash(git status:*)`); deny wins; an
"always allow" answer is written to the project's state `~/.laris/projects/<slug>/state.json` (or, when the user
chooses "everywhere", to `permissions.allow` in `~/.laris/settings.json`); Shift+Tab cycles modes. Coding tools: `Read` (line
range), `Write`, `Edit` (exact unique replacement), `Glob`, `Grep`, `Bash` (approval, timeout, working directory
confined to the project). Edits show a diff in the approval dialog; every edit is checkpointed and `/rewind`
restores files. Existing guards (path policy, secret redaction, leak guard, untrusted tool output) apply to every
new tool.
Acceptance: tests for each mode and rule precedence, a denied path never written, `Edit` uniqueness, `Bash`
timeout and confinement, checkpoint and rewind.

### SR-C4 — Headless mode and hooks
`laris -p` runs one task without the interface, reads standard input, and supports `--output-format
text|json|stream-json`, `--continue`, `--resume ID`, `--max-turns`, `--permission-mode`, `--allowed-tools`,
`--disallowed-tools`, with documented exit codes. Hooks (`SessionStart`, `UserPromptSubmit`, `PreToolUse`,
`PostToolUse`, `Stop`) are declared only in `~/.laris/settings.json`, run local commands inside the isolated
runtime, receive JSON on standard input, may block with a reason, and have timeouts; `/hooks` lists them.
Acceptance: headless tests with a scripted provider for every output format and exit code; hook tests for allow,
block, timeout and malformed output.

### SR-C5 — Safety of local execution
Running commands on the user's machine (`Bash`, `!command`, hooks, custom commands) never happens silently: a
project's custom commands and skills are used only after the user trusts that folder (trust kept in
`~/.laris/projects/<slug>/state.json`); shell tools respect permission rules and the path policy and run inside the
sandbox `~/.laris/.venv` (its `bin/` first on `PATH`, `VIRTUAL_ENV` set, `PIP_REQUIRE_VIRTUALENV=1`); installing a
package anywhere but the sandbox (system Python, `pip --user`, the program's files, another interpreter) is denied by
a built-in rule that settings cannot widen; output is treated as untrusted and redacted
before it reaches the model or the server.
Acceptance: security tests for an untrusted folder, a planted `./.laris/settings.json` or `config.yaml` (ignored),
hostile hook output, a prompt-injected request to run a command or install outside the sandbox or into the program's files, and secrets in
command output.

### SR-C6 — Global home and Claude-Code-style settings
The client keeps everything configurable in the global home:

```text
~/.laris/
  settings.json          all client settings (schema below); no secrets
  .credentials.json      API key, mode 0600
  .venv/                 sandbox (SR-C8): agent commands, hooks and their packages run and install here only
  python/                standalone interpreters downloaded for the sandbox (cache)
  LARIS.md  skills/  commands/  memory/        personal layers
  projects/<slug>/       per project: state.json (trust, approvals, last session), <key-fp>.sqlite (SR-S6), checkpoints/
  logs/                  local audit
./.laris/                (project, optional, may be committed) LARIS.md  skills/  commands/  memory/  - nothing else
```

The program itself is not in the home: the engine binary lives in the per-platform npm package and the Ink front
end in the main npm package (D19); updates come through npm. `settings.json` follows the shape of Claude Code's
settings and is validated by a JSON Schema shipped with the client:

```json
{
  "server": { "url": "https://host:8443", "caFingerprint": "sha256:...", "timeoutSeconds": 120 },
  "model": "",
  "permissions": { "defaultMode": "default", "allow": [], "ask": [], "deny": [], "additionalDirectories": [] },
  "env": {},
  "hooks": { "PreToolUse": [ { "matcher": "Bash", "hooks": [ { "type": "command", "command": "...", "timeout": 30 } ] } ] },
  "statusLine": { "type": "command", "command": "..." },
  "sandbox": { "python": "3.12", "packages": [], "inheritEnv": false, "indexUrl": "", "pythonSource": "" },
  "vault": { "autoRecord": true },
  "learning": { "collect": true },
  "cleanupPeriodDays": 30,
  "autoUpdates": true
}
```

On first start the client creates the layout without overwriting anything and migrates a 1.x home once, keeping
backups: `config.yaml` into `settings.json`, the `api_key` field into `.credentials.json`, and the legacy
`runtime/<version>/` removed. `laris login` reads `server.url` (set with `laris config set server.url ...` or
`/config`), asks for the key with hidden input, checks it, pins a private certificate on first use into
`server.caFingerprint`, and saves the key only when accepted; without `server.url` it explains how to set it.
`laris init` creates only the project folder layout above. The server's system policy root (`.laris/` in the
server codebase, mounted read-only into the `api` container) is a different folder and never exists on a client.
Acceptance: schema validation tests (unknown key, wrong type reported with the JSON path); first start in an empty
home creates the layout; migration from a 1.x home is idempotent and keeps backups; `laris login` works without flags
and refuses without `server.url`; project folders with configuration files are ignored with a warning.

### SR-C7 — Engine and engine protocol E1
The engine (`laris engine --stdio`) is the only owner of client behaviour: agent loop, tools, permissions,
settings, slash commands, sandbox, storage, server connection. It reads commands and writes events as JSON lines.
Events out: `ready`, `text`, `tool_call`, `tool_result`, `plan`, `permission_request`, `status`, `usage`,
`compact`, `goal`, `completion` (the reply to `complete`), `error`, `done`. Commands in: `user_message`, `permission_response`, `interrupt`, `command`
(slash command with arguments), `set_mode`, `complete` (completion request for `/` and `@`), `shutdown`. E1 is
described by JSON Schema in `laris.protocol` with a version exchanged in `ready`; the Node front end checks the
version and refuses a mismatch with a clear message. Headless `--output-format stream-json` writes the same events.
The Node front end holds no tool, permission or storage logic.
Acceptance: E1 contract tests validate every event and command against the schema; a scripted engine session
replays identically through the Ink front end, plain mode and headless `stream-json`; a version mismatch is reported; killing a front end leaves the engine
state consistent.

### SR-C8 — Automatic sandbox
The sandbox `~/.laris/.venv/` needs no action from the user. The engine starts a background check at start-up and
checks again before every sandbox use (marker with engine version and settings digest, interpreter probe, `pip`
present). When the sandbox is missing, broken or out of date it is built or repaired silently by the bundled `uv`
binary: a standalone Python for `sandbox.python` is fetched into `~/.laris/python/` (source from configuration,
checksums verified), else a suitable system Python is used; the environment is created and `sandbox.packages` are
installed. A file lock prevents two sessions from
building at once. While it works the status line shows a short hint; a tool call waiting for it is delayed, not
failed. If it cannot be built (offline and no suitable Python) the tool result and the status line say why and the
rest of `laris` keeps working. Commands the agent runs see the sandbox first on `PATH`, `VIRTUAL_ENV` set and
`PIP_REQUIRE_VIRTUALENV=1`; installing packages into the sandbox is allowed by default without a prompt (built-in
`allow` rule for `pip` and `uv pip` installs whose target is the sandbox; a user `ask` or `deny` rule can tighten it),
while any install outside the sandbox stays denied. The sandbox isolates packages, not privileges: commands still run as the user, so the
permission rules, the path policy and folder trust remain the security boundary. `/sandbox` shows its state and
`/sandbox reset` rebuilds it; neither is ever required.
Acceptance: with a temporary home, the first sandbox use builds it without user action; a deleted or corrupted
sandbox is repaired before the next use; two parallel sessions build it once; offline without Python gives a clear
message and the program keeps working; nothing is written to the system or user site-packages.

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

Second programme additions (T83 tests them): attackers also include a hostile network client (slow TLS
handshakes, oversized or malformed bodies, forged `X-Forwarded-For`), a compromised container, a hostile project
folder (hooks, custom commands) and a manipulated model asking to run shell commands. Controls: proxy limits and
timeouts, trusted-proxy list, internal-only network for model and database, read-only mounts, Docker secrets,
folder trust, permission rules and modes, checkpoints.

## 9. Core model (paused)

The model work resumes only after the exit criteria of phases 1 to 6 hold and the owner opens the gate
(task T39). Until then the offline planner and scripted providers are used in tests. Resumption does not
relax any gate in `docs/specifications/` or any rule in `AGENTS.md`.

## 10. Task progress index

The authoritative status of every task is in task.md. Phase 0: T01-T47 (T01-T04, T40, T41, T47). Phase 8 (Agentic): T42-T46. Phase 1: T05-T10. Phase 2:
T11-T17. Phase 3: T18-T23. Phase 4: T24-T26. Phase 5: T27-T32. Phase 6: T33-T37. Phase 7: T38-T39.
Second programme (done so far: T48 to T84): Phase 9 (decisions): T48-T48. Phase 10 (blocks): T49-T52. Phase 11 (model service): T53-T55.
Phase 12 (server API): T56-T59. Phase 13 (PostgreSQL): T60-T63. Phase 14 (client SQLite): T64-T66. Phase 15
(Docker): T67-T69. Phase 16 (terminal client): T70-T82. Phase 17 (hardening and release 2.0.0): T83-T85.
