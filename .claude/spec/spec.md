# LARIS — System specification (generation 2)

Version 2.0.0-draft · 2026-11-13 · Status: ledger established (task T92 done) · The single specification of the
whole system: model, system (harness), server, client and brain. It stands alone: the earlier Python system has no
branch any more, and this ledger does not depend on it.

Plans and tasks are split by programme (section 2):

| Programme | Plan | Tasks |
|---|---|---|
| 1. Model (ResearchLLM) | [plan/1-model.md](plan/1-model.md) | [task/1-model.md](task/1-model.md) |
| 2. System, server and client | [plan/2-system.md](plan/2-system.md) | [task/2-system.md](task/2-system.md) |
| 3. Brain | [plan/3-brain.md](plan/3-brain.md) | [task/3-brain.md](task/3-brain.md) |

Run `python scripts/validate_spec.py` after any change to these files (programme 2 ports it to `cargo xtask spec`).

## 1. Purpose and scope

LARIS is a system for scientific work in English and Vietnamese: terminal and browser clients, an agent harness, an
Obsidian-compatible brain, a policy gateway server and a model service. Its three goals, in the owner's order
(2026-11-13):

1. **Finish the model** (ResearchLLM): the self-built language foundation and its specialist stages up to a
   generative research advisor, each stage qualified on held-out gates. Highest priority.
2. **Rebuild the system, server and terminal client in Rust**, keeping the model block in Python: the system follows the
   layers loop → harness → prompt; the server climbs the ladder LLM → RAG → Agent → Agentic. A Next.js browser
   client uses the same P1 gateway.
3. **Build the main brain**: the Obsidian brain holds verified knowledge, a non-generative decision network decides,
   ResearchLLM advises and the system executes.

Out of scope: agents training, fitting or optimising any model (the owner runs training); adopting a pretrained
third-party language model as a dependency (ADR-002); claiming any capability that was not measured on its formal
held-out gate (ADR-008); a direct mode in which the client calls a model provider without the server; any dependency
on the Obsidian desktop application.

Task ids continue one global sequence and are unique across all task files.

## 2. Programmes and their order

| Programme | Content | Order rule |
|---|---|---|
| 1. Model | ResearchLLM stages 1-6 (section 6.8) | First and highest priority. Agents prepare code, data, configuration, evaluation and commands; the owner trains and returns measurements |
| 2. System, server, client | Rust rewrite (sections 6.2-6.7), browser chat over P1 (T258) | Its system and server phases run only when the next programme-1 task waits for the owner (a training run, a decision, labels). Its client phase starts after the model is finished (T118), with browser chat added on the owner's direction |
| 3. Brain | Cognitive architecture (section 6.9) | After programme 2 is accepted and the model is finished |

"The model is finished" means: every stage of section 6.8 passed its held-out gates and the owner recorded the
promotion. Until then the foundation model and every specialist are **NOT QUALIFIED**.

## 3. Owners

Every requirement has exactly one owner; the validator enforces one `Owner:` line per requirement with one of these
values. One requirement has one implementation (owner decision: no duplication).

| Owner | Runs where | Responsible for | Prefix |
|---|---|---|---|
| `governance` | repository | ledger, dependencies, CI, threat model, git flow, release | SR-G |
| `model` | Python model block, GPU | language foundation, specialists, ResearchLLM, data lineage, evaluation, model service | SR-M |
| `protocol` | crate `laris-protocol` | P1 (client-server), P2 (server-model), core event protocol | SR-P |
| `shared` | library crates used by server and client | configuration, vault format, retrieval | SR-L |
| `harness` | library crates (the system) | loop, harness and prompt layers | SR-H |
| `server` | binary `laris-server` | API, keys, storage, gateway, system brain, model proxy, traces, deployment, capability ladder | SR-S |
| `client` | binary `laris`, `apps/web` | terminal interface, commands, settings, login, headless mode, distribution, browser chat | SR-C |
| `brain` | across blocks | knowledge base, write gate, decision network, answer assembly | SR-K |

## 4. Definitions

- **ResearchLLM**: the self-built model stack of programme 1: the English foundation encoder (D46), the scientific,
  OCR and manuscript stages, and the stage-6 generative and verification specialists that act as the research advisor.
- **System** (harness): everything that turns model output into work: the loop (state machine, event log), the
  harness (tools, policy, sandbox, evidence, memory, storage) and the prompt layer (context assembly). The loop runs
  inside the harness and the harness composes the prompt; the prompt layer knows neither.
- **Capability ladder**: LLM (chat through the server) → RAG (answers grounded in retrieved evidence and the brain) →
  Agent (tool use) → Agentic (plan, progress, reflection, completion check, memory, bounded autonomy) (v1 ADR-017).
- **System brain**: the curated Obsidian-format knowledge base in `.laris/brain/`, held by the server, confidential.
- **Project vault**: the user's Obsidian-format vault in their project.
- **Main brain**: the target of programme 3: Obsidian knowledge with provenance plus the decision network.
- **Decider**: the component that chooses the next step of the loop (SR-H14); in programme 2 it follows the model's
  proposal under policy; in programme 3 the decision network replaces it.
- **Remote tool**: a tool the loop calls like a local tool but which the server or model service executes.
- **Owner run**: a training, fitting, profiling or held-out evaluation command prepared by an agent and executed by the owner.

## 5. Architecture

### 5.1 Repository

```text
Cargo.toml                 Rust workspace at the root (no /rust folder)
crates/
  laris-protocol           P1, P2, core events; JSON Schema export                   (protocol)
  laris-config             settings, environment, packaged defaults, catalogue        (shared)
  laris-vault              Obsidian format: parse, index, write, schema, lint         (shared)
  laris-retrieval          BM25, TF-IDF, graph expansion, fusion (shared)
  laris-brain              main brain: write gate, verification, answer assembly      (brain)
  laris-model-client       P1 client                                                  (harness, loop)
  laris-store              client SQLite                                              (harness, loop)
  laris-core               state machine, event log, decider seam, context            (harness, loop + prompt)
  laris-tools              local tools, remote tool bridge                            (harness)
  laris-policy             permission modes, rules, hooks, folder trust               (harness)
  laris-sandbox            OS confinement forked from codex; Python environment       (harness)
  laris-evidence           evidence gate (ADR-004)                                    (harness)
  laris-server             binary laris-server                                        (server)
  laris-tui                terminal interface                                         (client)
  laris-cli                binary laris                                               (client)
apps/web/                  Next.js browser chat over P1                               (client)
xtask/                     validate-spec, release helpers                             (governance)
src/laris/                 Python model block: model service, language, research      (model)
configs/  docs/  experiments/  reports/  tests/  .laris/
```

Weights, datasets, checkpoints and collected learning data stay outside Git (`artifacts/`, `data/` local content).

### 5.2 Runtime

```text
 user machine                         owner's server (docker compose)
 ┌──────────────────────────┐  P1    ┌──────────┐   ┌─────────────────────┐  P2  ┌──────────────────────┐
 │ laris (TUI + system:     │──────► │  Caddy   │──►│ laris-server (Rust) │────► │ model service (Py)   │
 │ loop, harness, prompt)   │ HTTPS  │ TLS, SSE │   │ keys, gateway,      │      │ ResearchLLM, embed,  │
 └──────────────────────────┘  SSE   └──────────┘   │ brain, traces       │      │ scientific tools     │
                                                    └─────────┬───────────┘      └──────────────────────┘
                                                          PostgreSQL
```

### 5.3 Model stack (programme 1)

```text
stage 1  foundation encoder, English only (D46; English tokenizer to be fitted, 110M compact / 544M large with the 56k vocabulary (T182), MLM+NLI+paraphrase+STS+QA)
stage 2  scientific language adaptation (SciFact NLI, evidence selection)
stage 3  scientific OCR (text and layout)
stage 4  OCR-coupled manuscript learning (discourse roles)
stage 5  integration into the model service (all heads, VRAM budget)
stage 6  specialists: generation (ResearchLLM advisor), reasoning, verification
```

Each stage starts only after the previous stage passed its gates (training specification section 8).

### 5.4 Main brain (programme 3)

```text
ResearchLLM (advisor) ──proposals──►  Decision network (non-generative)  ──action──►  System (tools)
         ▲                              ▲              │                                │
         └──────── brain context ───────┴── Obsidian main brain ◄── write gate ◄── verified results
```

## 6. Decisions

`decided`: the owner said so (2026-11-13 discussion, `idea.md`). `proposed`: a recommendation the owner confirms or
changes in the ADR named in the task.

| ID | Decision | Choice | Status |
|---|---|---|---|
| D27 | Languages | Rust for everything except the model block, which stays Python; no C++ | decided |
| D28 | Where the loop runs | The system runs on the user's machine like codex and Claude Code; the server is a gateway and runs no agent loop. The server ladder is reached by server and system together | decided; confirmed by the owner 2026-11-13 against the ladder wording (ADR-021); amended 2026-11-20 (ADR-025): the loop, tools and project vault stay on the client, the per-request pipeline runs in the server (D49) |
| D29 | Technology mastery | All logic written in-house on proven base crates, vendored (`cargo vendor`) and checked by `cargo-deny` | decided |
| D30 | Sandbox | Forked from codex (Apache-2.0, `aa5f492`): OS mechanisms only, licence, notice and origin kept in `THIRD_PARTY.md` | decided |
| D31 | Layout | Cargo workspace at the root; Python model block under `src/laris/` | decided |
| D32 | Ownership | One owner per requirement (section 3) | decided |
| D33 | Programme order | Model first; system and server in the owner's waiting time; client after the model; brain last (section 2) | decided |
| D34 | Install | One static binary per platform, one-line install, npm as a thin wrapper | decided |
| D35 | Wire compatibility | P1 and P2 are versioned by `X-Laris-Protocol`; a change of the wire format changes the version | confirmed 2026-11-13 (ADR-021) |
| D36 | Process model | Interface and core in one process; core events serialisable for headless mode and a later daemon | confirmed 2026-11-13 (ADR-021) |
| D37 | Direct mode | None | confirmed 2026-11-13 (ADR-021) |
| D38 | Core design | Event-sourced core with a decider seam, so programme 3 replaces the decider, not the core | confirmed 2026-11-13 (ADR-021) |
| D39 | Evidence check | The server returns the evidence of a turn in the `laris` block; each piece is checked once, by the side that holds it (server-held entries carry `origin: server`; the client checks local tool and project-note evidence) | confirmed 2026-11-13 (ADR-021); amended 2026-11-20 (ADR-025) |
| D40 | Learning data | Derived on the client from the event log; never sent; outside Git | confirmed 2026-11-13 (ADR-021) |
| D41 | Scientific NLP | Python in the model block, reached as remote tools; the Rust client contains no NLP | confirmed 2026-11-13 (ADR-021) |
| D42 | Branches | `main` integrates; one feature branch per task cut from it; release 1.0.0 is tagged on `main` | confirmed 2026-11-13 (ADR-021); `laris-v2` merged into `main` and removed 2026-11-20 |
| D43 | Stands alone | No reading, migration or compatibility with the earlier Python system; its data, formats and fixtures are not carried over | owner decision 2026-11-18 (ADR-021 addendum) |
| D44 | What "LLM" means for ResearchLLM | The stage-6 generative advisor is self-built (ADR-002); its architecture, size, data and compute budget are fixed in ADR-020 before any work on stage 6 | accepted, owner-delegated 2026-11-13: Option C on A2 (T93) |
| D45 | Human gold | Gates that need human labels (G12, evidence, OCR, discourse, reasoning) follow the D05 protocol; skipping labels defers a gate, never waives it | decided (D05 protocol) |
| D46 | Foundation language | Stage-1 encoder is English only; Vietnamese through a translation layer (i18n plus a translation model, chosen later); VI data replaced by English documents; G02, G08, G09, G11 withdrawn by a gated amendment task, G12 becomes English | decided by the owner 2026-11-14 (ADR-022); gates amended in T173, data inventory T174, English data acquired and STS-B leakage check built in T175, document and config sweep in T176, partition and wiring in T177, retrieval-pair task in T178, then tokenizer fit and retraining (owner) |
| D47 | Gold sources | No new human annotation for stages 2-4: held-out sets come from public human-labelled sets where one exists (SciFact, PubMedQA labeled, SCIDOCS, TREC-COVID, NFCorpus, DocLayNet boxes), and from LLM labels with `label_source: llm` where none exists; gates are reported as measured on those sets, never as human-gold results, and none is waived | decided by the owner 2026-11-14 (amends the labelling part of D45; D05 guideline and sealing rules still apply) |
| D48 | ResearchLLM | The self-trained model is dropped: ResearchLLM is an open-weight third-party reasoning LLM (not code-focused) chosen by the owner from a sourced report (T228), with a Prefilter, TF-IDF/BM25 retrieval, a harness loop and the Obsidian brain; learning-data export stays; no distillation from Claude outputs | decided by the owner 2026-11-20 (T227); the superseded programme-1 tasks (T99-T118, T188-T189, T209, T220-T226) were removed from the ledger |
| D49 | Pipeline location | The per-request pipeline (Prefilter, retrieval, brain decider, model call, evidence gate, assembly) runs in the server for every chat turn; the loop stays on the client | accepted 2026-11-20 (ADR-025) |
| D50 | Main brain placement | One shared vault on the server, read with `brain.read`, written only by the write gate; no per-user server vaults | accepted 2026-11-20 (ADR-025) |
| D51 | Stage order | auth, policy, Prefilter, retrieval, decider, model, evidence gate, assembly | accepted 2026-11-20 (ADR-025) |
| D52 | Evidence check | Once per evidence, by the side that holds it | accepted 2026-11-20 (ADR-025) |
| D53 | Grounded answers | Buffered, gated, then streamed; free answers and tool-call proposals stream unbuffered and claim no evidence | accepted 2026-11-20 (ADR-025) |
| D54 | Server decider | Rule decider behind the ADR-024 seam; closed action set unchanged; `run_tool`, `acquire`, `verify` not decided by the server pipeline; network off | accepted 2026-11-20 (ADR-025) |
| D55 | P1 additions | Optional `laris.steps`, `decision`, `evidence`; dropped from requests; `X-Laris-Protocol` bumped | accepted 2026-11-20 (ADR-025) |
| D56 | Rollout | Every stage behind configuration, off by default until T243 passes | accepted 2026-11-20 (ADR-025) |
| D57 | STEM gate benchmarks | MATH-500, MMLU-Pro (STEM categories), GPQA Diamond | decided by the owner 2026-11-23 (ADR-026, T274) |
| D58 | STEM thresholds | B1 MATH-500 ≥ 95 %; B2 MMLU-Pro STEM ≥ 84.8 % and B4 median ≤ 60 s, p95 ≤ 180 s per item, peak VRAM ≤ 15.5 GB, fixed from the T275 baseline; B3 GPQA Diamond fixed after GPQA is measured with a thinking budget, before tuning on it | decided by the owner 2026-11-23 (ADR-026 0.2.0) |
| D59 | Measured unit | The whole pipeline in an evaluation profile, pass@1; abstention, unparseable answer or timeout scores 0 | accepted 2026-11-23 (ADR-026) |
| D60 | Closed book | No network or web tools in gate runs; frozen, hashed brain snapshot | accepted 2026-11-23 (ADR-026) |
| D61 | Benchmark splits | Development: MATH train sample, seeded 20 % of MMLU-Pro STEM, GPQA main minus Diamond; sealed test run once per frozen candidate, at most three | accepted 2026-11-23 (ADR-026) |
| D62 | Deterministic brain | SymPy solver as a remote tool and verified notes through the write gate; model-free answers gated on precision (B5: 0 wrong) | SymPy and the sources approved by the owner 2026-11-23; accepted 2026-11-23 (ADR-026) |
| D63 | Benchmark leakage | 13-gram scan of brain and few-shot material against every benchmark item, 0 hits (B6); GPQA text never in Git, reports or the brain | accepted 2026-11-23 (ADR-026) |
| D64 | Model size | Light model Qwen3.5-4B, the only model measured (owner 2026-11-24); served at FP8 (online, vLLM `--quantization fp8`) as the one precision for chat and evaluation (owner 2026-11-24, T279) | decided by the owner 2026-11-23 (light model); measured in T279 (`reports/benchmarks/T279-cost.md`) |
| D65 | B3 gate | GPQA Diamond leaves the gate; measured and reported, never claimed as qualified | owner 2026-11-24 (ADR-026 amendment A1) |
| D66 | Model family | One light model; Phase 49 (Optimus / Megatron, T245-T248) cancelled | owner 2026-11-24 (ADR-026 amendment A1) |
| D67 | B4 time limits | Median and p95 time limits lifted; peak VRAM ≤ 15.5 GB kept; thinking budget may rise to the VRAM ceiling | owner 2026-11-24 (ADR-026 amendment A2) |
| D68 | Sealed run | T281 is optional: closing and handover do not wait for it; without it the model and the system stay NOT QUALIFIED | owner 2026-11-27 (ADR-026 amendment A3) |
| D69 | STEM profile in the server | The T278-T290 harness is a pipeline stage after the Prefilter and the research tools; a runner item always enters, a chat turn enters automatically when it is the first question of its conversation, has no attached documents and passes the prompt filter with a STEM signal; web and terminal client are answered under the configuration the benchmark runs (thinking budget 56,000 on computable questions); network tools off | owner 2026-11-27 (T284: "Cấu hình 56k và web + cli cùng đồng nhất", entry "Automatic"; ADR-025 amendment A1) |
| D70 | Math in answers | Answers are Markdown with LaTeX math: the web client typesets `$…$`, `$$…$$`, `\(…\)`, `\[…\]` and a bare `\boxed{…}` with KaTeX (`remark-math`, `rehype-katex`, `katex`, one patched `katex` for all through `overrides`; no `trust`); the terminal client keeps math exactly as written in its own style; the STEM answer line puts a LaTeX answer in `$…$` | owner 2026-11-27 (T291: "response mặc định dạng md để có thể nhận cả các ký hiệu toán học hay công thức dạng latex") |

## 7. Requirements

### 7.1 Governance

### SR-G1 — Ledger with one owner per requirement
Owner: governance
One specification file and one plan file and one task file per programme stay consistent; every requirement names
exactly one known owner; every task cites known requirements and earlier tasks; task ids are unique across files.
Acceptance: the validator passes and fails on seeded errors (missing, double or unknown owner, duplicate task id across
files, plan and task phases that disagree).

### SR-G2 — Dependency governance
Owner: governance
No dependency, toolchain or tool is added without the owner's recorded approval. Crates are vendored and checked by
`cargo-deny`; forked code is listed in `THIRD_PARTY.md`; Python dependencies of the model block change only with approval.
Acceptance: `cargo deny check` passes; an unapproved crate fails CI; offline build from the vendor folder.

### SR-G3 — Continuous integration and the no-training guard
Owner: governance
CI runs the Rust gates (fmt, clippy with warnings as errors, test, deny), the spec validator, the Python model-block
checks that perform no training, and a guard that fails if any job trains, fits, profiles with an optimiser or sets the
training authorisation.
Acceptance: a failing gate blocks merge; a seeded training call fails CI.

### SR-G4 — Git flow and releases
Owner: governance
One task, one branch, one session; pull requests only; push, merge, tag and release only with the owner's explicit
authorisation. Release 1.0.0 (tag `v1.0.0`) was cut on `main` after programme 2 passed its acceptance checklist.
Acceptance: release checklist recorded in the task note.

### SR-G5 — Threat model and security suite
Owner: governance
The threat model lists assets, attackers, threats, controls and test ids (section 9); a security suite in CI
covers every row.
Acceptance: every threat maps to a control and a test.

### 7.2 Protocol

### SR-P1 — P1, client to server
Owner: protocol
`POST /v1/laris/chat` (SSE), `/embed`, `/workflows`, `/help`, `/account`, `/tools/{name}` and admin routes, defined once
as Rust types with JSON Schema export and versioned by `X-Laris-Protocol`; `LarisMeta` carries usage and the brain evidence
list; an error after a stream started is an `error` event then `[DONE]`.
Acceptance: the committed SSE and JSON fixtures validate; version mismatch gives a clear error; export is deterministic.

### SR-P2 — P2, server to model
Owner: protocol
OpenAI-compatible `/v1/chat/completions` (stream, tools, reasoning), `/v1/embeddings`, and the model service's tool routes,
internal network only.
Acceptance: Rust types round-trip real chunks of the Python model service.

### SR-P3 — Core event protocol
Owner: protocol
Interface commands and core events as Rust types, a channel in one process and JSON lines for
headless `stream-json` and a later daemon.
Acceptance: round-trip test per message; the eleven scenarios of `tests/golden/ink_scenarios/` translated and replayed.

### 7.3 Shared libraries

### SR-L1 — Configuration and string catalogue
Owner: shared
Every tunable, limit, path, endpoint and message comes from configuration or the catalogue; precedence `LARIS_*`
environment, settings file, packaged build-time defaults; schema errors name the JSON path.
Acceptance: precedence and schema tests; a scan finds no hardcoded endpoint or secret.

### SR-L2 — Obsidian vault format
Owner: shared
One implementation of `docs/specifications/OBSIDIAN_VAULT_FORMAT.md`: parser, deterministic incremental index, atomic
writer with managed blocks and user-edit detection, schema registry, hub-tree lint.
Acceptance: the fixture vault yields the recorded index; byte-identical rerun; user edits survive 100 rewrites;
crash mid-write keeps the old file; lint fails on seeded faults.

### SR-L3 — Retrieval
Owner: shared
BM25, TF-IDF passage retrieval with note path and character span, link-neighbourhood expansion and deterministic fusion with span provenance; a dense channel fed by the model block,
labelled not qualified until stage 1 passes G12.
Acceptance: rankings on `tests/fixtures/retrieval/` equal the recorded expectations; recall@k, MRR, nDCG computed; P95 under 300 ms at
10,000 notes measured.

### 7.4 System: loop, harness, prompt

### SR-H1 — Agent loop
Owner: harness
`laris-core` runs multi-turn work as a state machine: plan, tool calls, reflection with bounded replanning, completion
check, turn, token and time budgets, interrupt; it reaches the model only through the `ModelClient` trait.
Acceptance: the Agentic scenarios pass with a scripted model; an interrupt leaves a consistent session.

### SR-H2 — Event log
Owner: harness
Every step of a session is an append-only event; sessions resume and replay from the log; traces, learning data and
debugging read the same log.
Acceptance: replay is byte-identical with a scripted model; resume after a killed process continues from the last event.

### SR-H3 — Prompt layer: context assembly and autocompact
Owner: harness
The prompt layer assembles each request from `LARIS.md` layers, memory, plan, pinned items and conversation within the
model budget; autocompact never drops pinned goals, constraints and decisions; it knows neither the loop nor the harness.
Acceptance: budget tests; pinned items survive compaction (property test); a layer contract test (loop → harness → prompt).

### SR-H4 — Tools and remote tools
Owner: harness
One registry for local tools (`Read`, `Write`, `Edit`, `Glob`, `Grep`, `Bash`, ingestion, vault tools, `save_memory`,
skills) and remote tools; structured errors; output limits; untrusted marking; checkpoints and `/rewind`.
Acceptance: tests per tool; local and remote tools identical to the loop (contract test).

### SR-H5 — Permissions, hooks and folder trust
Owner: harness
Modes `auto` (the default: changes run without asking except those fitting `permissions.autoAsk`), `default`,
`acceptEdits`, `plan`, `bypass` (policy permitting); rules `allow`, `ask`, `deny` with patterns, deny
wins; hooks declared only in global settings; project commands and skills only in trusted folders.
Acceptance: mode and precedence tests; denied path never written; hook allow, block, timeout, malformed; planted project
settings ignored.

### SR-H6 — Sandbox
Owner: harness
Agent commands run under OS confinement forked from codex on Linux, macOS and Windows, with the automatic Python
environment `~/.laris/.venv/`.
Acceptance: per platform, writes outside allowed roots fail; the environment builds on first use, is repaired after
deletion and is built once by two parallel sessions.

### SR-H7 — Evidence gate
Owner: harness
Research answers cite evidence; every cited span must exist in retrieved or returned evidence; absence-of-evidence rule;
unsupported statements marked; checked once before display (ADR-004, D39).
Acceptance: fabricated citation, missing span and unsupported claim are caught; valid answers pass unchanged.

### SR-H8 — Project vault lifecycle and memory
Owner: harness
Vault init (idempotent, never overwrites, no nesting), write-through notes with provenance, memory in the vault, domain
hubs, proposals inbox excluded from retrieval.
Acceptance: init twice changes nothing; an existing vault is adopted unchanged; proposals invisible to retrieval.

### SR-H9 — Client storage
Owner: harness
SQLite per project and key fingerprint in `~/.laris/projects/<slug>/` (WAL, numbered migrations): sessions,
event log, passages, embedding cache, learning examples, vault index cache.
Acceptance: a fresh database gets every migration once and a newer one is refused; two writers lose nothing.

### SR-H10 — Redaction and injection defence
Owner: harness
Secrets redacted before anything reaches the model or server; tool output and documents are untrusted data; injected
requests to run commands or leave the sandbox are refused by policy.
Acceptance: security tests for secrets in output, injected document, hostile hook output.

### SR-H11 — Learning data
Owner: harness
Examples derived from the event log when `learning.collect` is on; `laris learn export` writes JSONL; nothing leaves the
machine; nothing trains.
Acceptance: export matches its fixture; collected data absent from P1 requests and the repository.

### SR-H16 — MCP tools
Owner: harness
The client starts the MCP servers named in the user's own settings (`mcp.servers`; none by default) as child processes inside the OS sandbox with a network and a single
writable folder, speaks MCP over standard input and output, and offers their tools to the loop as
`mcp__<server>__<tool>` through the remote-tool path: output untrusted and shielded, permission rules and hooks apply
(`allow` rules may end in `*` after the tool name). A server that cannot start, lacks its environment variable or has
no sandbox is skipped with a reason shown by `/mcp`; a call has a time limit, and a server that timed out or died is
started again. A project cannot add a server.
Acceptance: handshake, list, call, tool error, timeout, crash and restart, skipped and failed servers against a scripted
server through the sandbox; planted project settings add no server; rule `mcp__x__*` fits only that server's tools.

### SR-H17 — Web tools and clock
Owner: harness
The model can know the date and reach the public web without set-up: `Now` (UTC date and time, time zone setting, OS),
`WebFetch` (a public page as text) and `WebSearch` (titles, addresses and snippets from the configured HTML search page,
keyless). They run in the client with its own address and no proxy. Only public addresses are read: literal inside
addresses, names that resolve inside and redirects that lead inside are refused, as are addresses with credentials;
a request whose address or query changes under redaction is not sent. Results are untrusted. Limits (time, bytes,
redirects, results) are settings; `web.searchUrl` is a setting, and an empty one turns search off.
Acceptance: page-to-text, search parsing, typed errors, secret refusal and settings switches against a scripted
transport; inside addresses refused; the clock answers a plausible date.

### SR-H12 — Model client
Owner: harness
P1 client: SSE with backpressure, version check, key, certificate pinning, timeouts, bounded retries before a stream
starts, interrupt.
Acceptance: tests on recorded fixtures, version and pin mismatch, interrupted stream.

### SR-H13 — Document ingestion
Owner: harness
Text, Markdown and PDF into passages with spans and Source notes. A PDF the built-in reader cannot use (a scan, fonts it cannot
decode) is read by external programs named in `vault.ocr` (`pdftotext`, then `pdftoppm` and `tesseract`), also when `WebFetch` meets a PDF (T261);
`read_by` says how. When they are missing the error names each reason.
Acceptance: passages of text and Markdown point to the exact source characters; PDF fixtures produce spans; a scanned fixture is read by OCR; missing programs give a clear message.

### SR-H14 — Decider seam
Owner: harness
The next loop step is chosen by a `Decider` from a closed action set given the state (goal, plan, evidence, proposals,
checks, budgets); in programme 2 the only implementation follows the model's proposal under policy.
Acceptance: the loop runs with a scripted decider; no model call outside an action chosen by the decider.

### SR-H15 — Model-free evaluation suite
Owner: harness
One command runs golden replay, Agentic scenarios, retrieval metrics, evidence checks, leak and injection tests, vault
round trips and benchmarks without a trained model; results go to reports.
Acceptance: reproducible; a seeded 20 percent regression fails.

### 7.5 Server

### SR-S1 — Hardened HTTP API
Owner: server
axum behind Caddy; bodies validated before work; 400, 401, 403, 411, 413, 429 explicit; mid-stream errors per SR-P1; client
address from `X-Forwarded-For` only via trusted proxies; no key printed; no content in logs.
Acceptance: tests per status code, mid-stream error, slow client, trusted and untrusted proxy.

### SR-S2 — Keys, roles and quotas
Owner: server
Digest-only keys with a master secret outside the database, roles, permissions, quotas reserved atomically and settled in
one transaction, expiry, revocation, admin routes.
Acceptance: lifecycle tests; parallel requests never exceed a limit by more than one reservation.

### SR-S3 — Server storage on PostgreSQL
Owner: server
Numbered migrations, pool, monthly partitions, retention, daily usage summary.
Acceptance: tests under `LARIS_TEST_PG_DSN`; a fresh database gets every migration once; a newer one is refused.

### SR-S4 — Policy gateway
Owner: server
System prompt, rules and workflows from `.laris/` (Markdown and TOML) composed on the server only; one system skill
chosen by context for each turn, never a list; integrity lock (`integrity.toml`) checked at start; outbound leak guard;
reasoning kept for the operator only.
Acceptance: confidentiality suite leaks nothing above the limit; a changed policy file stops the server; no reasoning in
chat bodies.

### SR-S5 — System brain service
Owner: server
Progressive disclosure from `Brain Index` with budgets; ids only in audit; evidence list in `LarisMeta`; no runtime writes.
The model gets a brief (the hub a workflow routes to, summaries only) in the prompt and one tool, `use_system_brain`
(`index`, `open`, `read`); a note deeper than `brain.max_depth` steps from the root is refused; the notes are
confidential and covered by the leak guard.
Acceptance: each direction reaches its playbook within `brain.max_depth` steps without search; budgets reported; the
brain folder is unchanged after every operation.

### SR-S6 — Model proxy and remote tools
Owner: server
P2 calls with bounded concurrency, unbuffered streaming, `/embed`, and `/tools/{name}` forwarded to the model service.
Acceptance: first-chunk latency measured; concurrency limit holds; a model failure becomes an `error` event.

### SR-S7 — Traces and audit
Owner: server
Per-request trace (key id, route, timings, tokens, brain note ids, tool names, outcome) without content; retention.
Acceptance: trace on success, error and disconnect; no message text in any row.

### SR-S8 — Deployment on one machine
Owner: server
Compose with Caddy, a static non-root Rust API image, the Python model image and PostgreSQL; only Caddy publishes ports;
`caddy_data` kept; policy and weights mounted read-only; Docker secrets; backup script and runbook.
Acceptance: `docker compose config` validates; smoke test through the stack; images hold no policy and no weights; the
trial server's volumes survive the upgrade.

### SR-S9 — Capability ladder
Owner: server
The deployed system climbs LLM → RAG → Agent → Agentic; each level is demonstrated by a scripted end-to-end scenario
through server and system before the next level's phase closes. With the placeholder backend the scenarios prove the
mechanics only; a level counts as a capability only when measured with a qualified model.
Acceptance: one scenario suite per level passes against the compose stack; reports say which backend was used.

### 7.6 Client

### SR-C1 — Terminal interface like Claude Code
Owner: client
Banner, bordered multi-line input, streamed Markdown with highlighting, tool and diff blocks, approvals, status line, footer
hints; Esc interrupts; Ctrl+C twice exits; typing while the agent works; history search; no tool, permission or storage logic.
LaTeX math in an answer is shown exactly as written, in its own style (D70).
Acceptance: translated golden scenarios pass through the interface; render tests at 60 and 100 columns; owner screenshot review.

### SR-C2 — Commands and input
Owner: client
Built-in and custom slash commands (including `/rewind`), `@path` completion, `!command`, `# note`, pasted text.
Acceptance: registry and input tests; every command in the guide.

### SR-C3 — Global home and settings
Owner: client
`~/.laris/` layout and Claude-Code-style `settings.json`; a project `./.laris/` holds only
`LARIS.md`, `skills/`, `commands/`, `memory/`.
Acceptance: schema tests; empty home creates the layout.

### SR-C4 — Start with nothing to configure
Owner: client
Packaged default server at build time; login form inside the interface; key saved (0600) only after the server accepts it.
Acceptance: fresh home reaches a chat turn after the key is entered; a wrong key shows the form again.

### SR-C5 — Headless mode
Owner: client
`laris -p` with stdin, `--output-format text|json|stream-json`, resume, continue, max turns, permission and tool flags,
documented exit codes.
Acceptance: tests with a scripted model per format and exit code.

### SR-C6 — Distribution
Owner: client
Static binaries (Linux musl x86_64 and aarch64, macOS, Windows MSVC) with LTO and strip; `install.sh` and `install.ps1`
with checksum and signature checks; npm thin wrapper; size reported.
Automatic update (T251): the interface checks the release address in the background (at start, then every
`update.intervalMinutes`), always on. A newer version is installed only when the signature of `SHA256SUMS` (which lists
the archives and the file `VERSION`) is valid for the release key built into the client and the archive matches its signed
checksum; the running session is not touched and a notice above the input box at the right says `/restart` applies it.
Acceptance: one-command install and start on a clean machine per platform; a tampered binary is refused; a tampered list or
archive is never installed by an update.

### SR-C7 — Browser chat
Owner: client
A responsive Next.js interface composed from shadcn/ui sends messages to the configured P1 gateway and renders streamed
replies. Users can start, find, rename and delete conversations, stop a reply and retry a failed turn. The browser stores
chat history and attachments locally and keeps the API key in tab memory. UTF-8 files are sent as text with the user's
message and share the gateway request limit.
Replies, finished and streaming, are Markdown with LaTeX math typeset by KaTeX (D70).
Acceptance: a desktop and mobile viewport can send a chat and manage its history. An attached UTF-8 file reaches P1 as
message text, and a streamed error preserves the partial answer for the user. LaTeX in an answer keeps its backslashes
and is typeset; code is left as written.

### 7.7 Model service

### SR-M1 — Model service and P2
Owner: model
The Python model service is the only place that loads weights and serves P2 unchanged behind the Rust server; a
placeholder backend serves tests.
Acceptance: the Rust server's P2 contract tests pass against the running service.

### SR-M2 — Scientific tools as remote tools
Owner: model
Scientific extraction and scholarly parsing served as tool routes so the client has no NLP; the call sites of the
Python code are inventoried first. The deterministic STEM solver (`solve_stem`, T276, ADR-026 section 5) is one of these
tools: model-free, each answer `verified` by an independent route or marked a proposal.
Acceptance: route schemas in `laris-protocol`; fixture tests reproduce the extraction results.

### SR-M3 — Model boundary and owner runs
Owner: model
Agents never train, fit, take backward or optimiser steps, run optimiser-bearing profiling or set the training
authorisation; every such step is a prepared owner run with exact command, budget, timeout and expected outputs; returned
logs and manifests are checked before results are used.
Acceptance: the no-training guard (SR-G3) covers the model block; every owner-run task lists its command and budget.

### 7.8 Model programme: ResearchLLM

**D48 (2026-11-20):** SR-M4 to SR-M6 describe the dropped self-trained encoder and are kept only as the record of the tasks that implemented them; SR-M7 to SR-M9 (stages 2-4) were removed; SR-M10 and SR-M11 are rewritten for the open-weight LLM. Phase 44 holds the work. Superseded tasks were removed from the ledger and remain in git history.

### SR-M4 — Data lineage and splits
Owner: model
Every dataset, source licence, preprocessing step, split and fix has a provenance record with checksums
(`docs/specifications/DATASET_SPECIFICATION.md`, ADR-002); held-out test splits are sealed; corrections (STS-B overlaps; the English extra-similarity sets are deduplicated against STS-B val and test by `scripts/check_sts_leakage.py`)
are frozen as new versions with lineage; the owner's corpus work on `wip/corpus-acquisition-changes` is
reviewed before use.
Acceptance: `data check --verify-sha256` passes; partition isolation verified; no test data used for tuning.

### SR-M5 — Tokenizer meeting the fertility gates
Owner: model
A tokenizer that meets G10 (≤ 1.35 tokens per word on unseen English text; G11, Vietnamese, withdrawn by D46) under the frozen protocol, with the
special-token contract of the encoder, chosen through the F06-R1 remediation (`docs/training/FOUNDATION_TOKENIZER_REMEDIATION.md`).
Acceptance: fertility measured on sealed unseen text; checkpoint lineage reviewed when the vocabulary changes.

### SR-M6 — Stage 1: foundation qualification
Owner: model
The English foundation encoder passes every active gate of the training specification section 5 (G01, G03-G07, G10, G12; G02, G08,
G09, G11 are withdrawn by D46 and recorded, never counted as passed) on held-out test data with matching protocols and artifact
identity; G12 needs STEM relevance labels (D45).
Acceptance: the offline readiness check exits 0 on the held-out reports; the owner records the promotion.

### SR-M10 — Model service
Owner: model
The model service serves the chosen open-weight LLM through P2 and the tool routes (`/v1/chat/completions`, with tool calls) within the VRAM budget of the target GPU; no model is trained.
Acceptance: P2 contract tests pass; the owner-measured memory use is recorded.

### SR-M11 — ResearchLLM on an open-weight LLM (D48)
Owner: model
ResearchLLM is an open-weight third-party reasoning LLM (not code-focused) chosen by the owner from the sourced report T228, combined with a Prefilter, TF-IDF/BM25 retrieval, the harness loop and the Obsidian brain. Capability is claimed only where measured on a held-out set (ADR-008); until then the model is NOT QUALIFIED.
Acceptance: the owner records the choice; the chat backend answers a prompt through the model service (T231).

### SR-M12 — Evaluation and readiness
Owner: model
Per-stage evaluators and the offline readiness check reject missing measurements, incompatible protocols, mixed
checkpoints, non-finite values and validation-only evidence; held-out evaluation runs once per candidate; reports follow
`docs/specifications/REPORT_SPECIFICATION.md`.
Acceptance: readiness tests with seeded faulty reports; no gate threshold changed without an ADR.

### SR-M13 — STEM benchmark qualification of the system (ADR-026)
Owner: model
The whole pipeline (Prefilter, STEM router, deterministic solver, retrieval over the main brain, light model in the
harness loop, answer check) is measured closed-book on MATH-500, MMLU-Pro STEM and GPQA Diamond under the frozen
protocol of ADR-026, with cost and latency per item; development splits guide changes, each sealed test runs once per
frozen candidate. The system is qualified on STEM only when B1-B6 pass; until then it is NOT QUALIFIED.
Acceptance: the owner accepts ADR-026; a sealed-run report per candidate with Wilson intervals, cost, latency,
leakage scan and model-free precision.

### 7.9 Brain programme

### SR-K1 — Design gate
Owner: brain
An ADR fixes the main brain before implementation: note types and certainty ladder, the single write gate, the decision
network's closed action set, inputs and abstention, answer assembly from accepted claims, the cold-start rule decider,
held-out gates and the owner's training runs.
Acceptance: ADR accepted by the owner; no brain code before it.

### SR-K2 — Knowledge notes and certainty ladder
Owner: brain
Note types Source (verbatim text, immutable, hash), Claim (atomic, linked to a source span by position and hash), Theory
(attributed position, not a fact), Conflict (both sides kept), Open question; each Claim carries a certainty level:
candidate, sourced (exact quote verified), corroborated (two independent sources), verified (tool or computation),
reviewed (human).
Acceptance: schema and lint for every type; a Claim without a resolvable span fails lint.

### SR-K3 — Single write gate and consolidation
Owner: brain
Only the write gate writes the main brain; it accepts Claims at level sourced or higher, searches for contradicting
evidence before accepting, records Conflicts, and downgrades every dependent Claim when a Source is retracted or replaced.
Model-generated text never becomes a Claim without a Source.
Acceptance: tests for a model-only claim (refused), a retracted source (dependants downgraded), a contradiction (Conflict
note written).

### SR-K4 — Answer assembly from accepted claims
Owner: brain
Final answers are composed from accepted Claims with note ids; the advisor may only rephrase; a check rejects text that
asserts anything outside the accepted set; the check's own miss rate is measured.
Acceptance: fixtures with an inserted unsupported sentence are rejected; miss rate reported.

### SR-K5 — Decision network
Owner: brain
A non-generative network scores (state, candidate) pairs from the closed action set using measured signals (evidence
coverage, advisor agreement, NLI and conflict results, advisor track record, cost, risk, budget) and returns an action, a
candidate and a calibrated confidence, abstaining below threshold. The rule decider stays in charge until the network
passes its held-out gates. Inference runs in the Rust system.
Acceptance: rule decider passes the scenario suite; the network is promoted only after held-out gates and owner approval.

### SR-K6 — Decision data and training boundary
Owner: brain
Decision examples (state, candidates, choice, outcome) come from event logs; ResearchLLM training data drawn from the
brain uses only Sources and verified Claims, never model-generated text; the owner trains.
Acceptance: dataset manifests with provenance; a seeded model-generated example is excluded.

### SR-K7 — Cognitive evaluation
Owner: brain
Measured with more than one advisor: unsupported-claim pass-through rate, faithfulness to sources, abstention calibration,
constraint recall after N turns, false completion rate.
Acceptance: one command produces the report; results stated as system measurements, not model qualification.

## 8. Cross-cutting rules

- `AGENTS.md` applies: no agent training; the foundation model is NOT QUALIFIED until promoted; functional names
  (ADR-013); measured results in reports, not specifications; weights, datasets and collected data outside Git; no
  dependency without approval.
- Policy in `.laris/` and `LARIS.md` changes only with the owner's approval and stays under the integrity lock.
- Every limit, path, endpoint and message is configuration or catalogue (SR-L1).
- This system does not depend on the Python generation; its branch `laris-v1` was removed on 2026-11-20 (owner decision, ADR-021 addendum).
- No gate threshold is relaxed; a missing metric is NOT VERIFIED, never a pass (ADR-008).

## 9. Threat model summary

Assets: system brain and policy, main brain, credentials and keys database, user files and vaults, datasets and
checkpoints, collected learning data. Attackers: hostile documents and notes, a manipulated model, a hostile project
folder, a hostile network client, a compromised container, poisoned training or brain data. Controls: server-only policy
and brain with leak guard and integrity lock, digest-only keys and atomic quota, proxy limits and trusted proxies,
internal network for model and database, folder trust, permission rules, OS sandbox, redaction, checkpoints, evidence
gate, brain write gate with provenance, sealed test splits and data checksums. Local administrator access is out of scope.

## 10. Task progress index

The authoritative status of every task is in the task files. Programme 1: Phase 19: T92-T94. Phase 20: T95-T98.
Programme 2: Phase 26: T119-T122. Phase 27: T123-T127. Phase 28: T128-T131. Phase 29: T132-T138, T214. Phase 30: T139-T140.
Phase 31: T141-T144. Phase 32: T145-T148, T215, T217. Phase 33: T149-T151. Phase 34: T152-T154. Phase 35: T155-T159.
Phase 36: T160-T161. Programme 3: Phase 37: T162-T162. Phase 38: T163-T166. Phase 39: T167-T171. Phase 40: T172-T172. Phase 41: T173-T191 (stage-1 re-scope, D46; programme 1). Phase 42: T185-T187 (TF-IDF, word vectors, NER head; programme 1). Phase 43: T192-T219 (pair-task remediation; programme 1). Phase 44: T227-T235. Phase 45: T236-T236. Phase 46: T237-T237. Phase 47: T238-T243. Phase 48: T244-T244. Phase 49: T245-T248 (open-weight LLM, D48; programme 1). Phase 50: T249-T249. Phase 51: T250-T250. Phase 52: T251-T251. Phase 53: T252-T252. Phase 54: T253-T257. Phase 55: T258-T260. Phase 56: T261-T273. Phase 57: T274-T281, T288-T290 (STEM benchmark qualification, ADR-026; programme 1). Phase 58: T283-T283 (precision of the gate's checks; programme 3). Phase 59: T284-T284 (STEM evaluation profile in the server; programme 2). Phase 60: T291-T291 (math in answers; programme 2).
