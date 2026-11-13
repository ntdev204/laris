---
document_id: "DOC-ADR-021"
title: "ADR-021: Rust generation (system, server, client) and its decisions D27-D43"
document_type: "adr"
status: "PROPOSED"
version: "0.1.0"
created_at: "2026-11-13"
updated_at: "2026-11-13"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - ".claude/spec/spec.md"
  - ".claude/spec/plan/2-system.md"
  - ".claude/spec/task/2-system.md"
decision_references:
  - "ADR-002"
  - "ADR-004"
  - "ADR-008"
change_summary: "Draft for the owner's confirmation of D27-D43 (task T120)."
---

# ADR-021: Rust generation

## Metadata
- **Status:** PROPOSED. It becomes ACCEPTED when the owner approves it in writing (task T120).
- **Date drafted:** 2026-11-13 · **Decisions (ledger):** D27-D43 · **Requirements:** SR-G1, SR-G4
- **Qualification:** the foundation model and every specialist are NOT QUALIFIED. Scenarios run with a placeholder
  backend prove mechanics only (SR-S9).

## 1. Context
Generation 1 (Python, release 2.2.0, frozen on `laris-v1`) delivered a client, harness, brain, server and model
service. Generation 2 rebuilds the system, server and client in Rust and keeps the model block in Python. The owner
approved the toolchain and crate list in T119 (2026-11-13). This ADR records each decision of spec section 6 so that
later tasks cite one place.

## 2. Decisions
Rows marked *decided* were fixed by the owner on 2026-11-13 and are only restated. Rows marked *proposed* are the
recommendations the owner confirms or changes; the "Alternative" column is what was rejected.

| ID | Decision | Choice | Status here | Alternative rejected, reason |
|---|---|---|---|---|
| D27 | Languages | Rust everywhere except the model block (Python); no C++ | decided | C++ for the sandbox: memory-unsafe, second toolchain |
| D28 | Where the loop runs | On the user's machine; the server is a gateway and runs no agent loop. The ladder LLM → RAG → Agent → Agentic is reached by server and system together | decided; confirmed below | Loop on the server: tools would run away from the user's files and permissions |
| D29 | Mastery | In-house logic on vendored base crates, checked by `cargo-deny` | decided | Large frameworks: opaque behaviour, supply-chain surface |
| D30 | Sandbox | Forked from codex (Apache-2.0, `aa5f492`), OS mechanisms only; origin kept in `THIRD_PARTY.md` | decided | Writing from scratch: security-critical, error-prone |
| D31 | Layout | Cargo workspace at the root, Python model block under `src/laris/` | decided | A `/rust` folder: two roots |
| D32 | Ownership | One owner per requirement | decided | Shared ownership: duplicated implementations |
| D33 | Programme order | Model first; system and server in the owner's waiting time; client after the model; brain last | decided | Parallel full-speed: starves the model programme |
| D34 | Install | One static binary per platform, one-line install, npm as a thin wrapper | decided | Container or venv for the client |
| D35 | Wire compatibility | P1 and P2 keep the generation-1 wire format; additions are versioned by `X-Laris-Protocol` | proposed: **confirm** | New wire format: breaks the generation-1 server and clients during migration |
| D36 | Process model | Interface and core in one process; core events serialisable for headless mode and a later daemon | proposed: **confirm** | Separate engine process (generation 1): extra protocol, startup cost; the serialisable events keep that door open |
| D37 | Direct mode | None; the client always goes through the server | proposed: **confirm** | Direct provider calls: bypasses keys, quota, policy and the evidence check (already out of scope in spec section 1) |
| D38 | Core design | Event-sourced core with a decider seam, so programme 3 replaces the decider, not the core | proposed: **confirm** | State kept only in memory: no replay, no learning data |
| D39 | Evidence check | The server returns the system-brain evidence of a turn in `LarisMeta`; the client gate checks once before display | proposed: **confirm** | Check on the server only: the server cannot see local tool results; check twice: duplicate logic (ADR-004) |
| D40 | Learning data | Derived on the client from the event log; never sent; outside Git | proposed: **confirm** | Collect on the server: privacy and confidentiality |
| D41 | Scientific NLP | Python in the model block, reached as remote tools; the Rust client contains no NLP | proposed: **confirm** | NLP in Rust: re-implements the model block and breaks D27 |
| D42 | Branches | `laris-v2` integrates; one feature branch per task is cut from it; `main` receives release 3.0.0 | proposed: **confirm** | Git flow with `develop`: generation 1 uses it, but two integration lines would split the ledger |
| D43 | Generation-1 data | Readable without loss: vaults, `~/.laris`, project SQLite, JSONL, `integrity.lock`, server PostgreSQL | decided | Migration tool that rewrites data: risk of loss |

## 3. Confirmation of D28 against the ladder wording of 2026-11-13
The ladder (spec section 4): LLM (chat through the server) → RAG (answers grounded in retrieved evidence and the
brain) → Agent (tool use) → Agentic (plan, progress, reflection, completion check, memory, bounded autonomy).

The wording is consistent with D28 as long as each rung is read as a property of the deployed whole:
- LLM and RAG are served by the server: chat, retrieval over workspace and system brain.
- Agent and Agentic need the loop, which runs on the user's machine (system), calling local tools and remote tools
  (the server or model service executes remote tools, the loop calls them like local ones).
- Hence "the server climbs the ladder" means the server provides every capability a rung needs from its side, and
  SR-S9 proves each rung by a scenario through server and system together, not by a loop inside the server.

Draft verdict: D28 holds unchanged. The owner confirms or overturns this reading.

## 4. Release tools (named here as T119 requires)
T119 approved "a release signing tool and a cross-compilation tool" without naming them. The owner delegated the
choice on 2026-11-13 ("chọn phương pháp phù hợp nhất, giống Claude Code"): one native binary per platform, built on
that platform, installed by a one-line script (D34). Chosen:
- Build: native CI runners for macOS and Windows, because the sandbox crates (landlock, seccomp, Windows APIs) must be
  built and tested on their own platform; `cross` only for the static Linux (musl) targets.
- Signing: `minisign` detached signatures over a checksum manifest, verified by the install script; platform code
  signing (macOS notarisation, Windows Authenticode) is added at release 3.0.0 if the owner holds the certificates.
Neither tool is installed or used before T121 and neither becomes a dependency of the Rust code.

## 5. Consequences
- Plan 2 phases follow the ladder (phases 31-34) while the loop, harness and prompt layers (phases 28-30) are built
  first.
- D37 removes one code path and one test matrix; users without a server cannot use the client.
- D40 means learning data can only be improved by the owner copying it deliberately.
- If the owner changes a decision, the spec table, the affected requirements and this ADR change together in one task.

## 6. Owner decision (to fill)
For each of D28 and D35-D42, and (optionally) overturn the release tools in section 4: confirm / change to ___. Date: ___.
