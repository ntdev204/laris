---
document_id: "DOC-ADR-021"
title: "ADR-021: Rust generation (system, server, client) and its decisions D27-D43"
document_type: "adr"
status: "ACCEPTED"
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
change_summary: "Owner confirmed D27-D43 and the release tools (task T120)."
---

# ADR-021: Rust generation

## Metadata
- **Status:** ACCEPTED on 2026-11-13: the owner approved D28, D35-D42 as proposed and the `AGENTS.md` change ("Đồng ý").
- **Date drafted:** 2026-11-13 · **Decisions (ledger):** D27-D43 · **Requirements:** SR-G1, SR-G4
- **Qualification:** the foundation model and every specialist are NOT QUALIFIED. Scenarios run with a placeholder
  backend prove mechanics only (SR-S9).

## 1. Context
Generation 1 (Python, release 2.2.0, branch since removed) delivered a client, harness, brain, server and model
service. Generation 2 rebuilds the system, server and client in Rust and keeps the model block in Python. The owner
approved the toolchain and crate list in T119 (2026-11-13). This ADR records each decision of spec section 6 so that
later tasks cite one place.

## 2. Decisions
Rows marked *decided* were fixed by the owner on 2026-11-13 and are only restated. Rows marked *proposed* are the
recommendations the owner confirms or changes; the "Alternative" column is what was rejected.

| ID | Decision | Choice | Status here | Alternative rejected, reason |
|---|---|---|---|---|
| D27 | Languages | Rust everywhere except the model block (Python); no C++ | decided | C++ for the sandbox: memory-unsafe, second toolchain |
| D28 | Where the loop runs | On the user's machine; the server is a gateway and runs no agent loop. The ladder LLM → RAG → Agent → Agentic is reached by server and system together | decided; confirmed 2026-11-13 | Loop on the server: tools would run away from the user's files and permissions |
| D29 | Mastery | In-house logic on vendored base crates, checked by `cargo-deny` | decided | Large frameworks: opaque behaviour, supply-chain surface |
| D30 | Sandbox | Forked from codex (Apache-2.0, `aa5f492`), OS mechanisms only; origin kept in `THIRD_PARTY.md` | decided | Writing from scratch: security-critical, error-prone |
| D31 | Layout | Cargo workspace at the root, Python model block under `src/laris/` | decided | A `/rust` folder: two roots |
| D32 | Ownership | One owner per requirement | decided | Shared ownership: duplicated implementations |
| D33 | Programme order | Model first; system and server in the owner's waiting time; client after the model; brain last | decided | Parallel full-speed: starves the model programme |
| D34 | Install | One static binary per platform, one-line install, npm as a thin wrapper | decided | Container or venv for the client |
| D35 | Wire compatibility | P1 and P2 keep the generation-1 wire format; additions are versioned by `X-Laris-Protocol` | proposed, confirmed 2026-11-13 | New wire format: breaks the generation-1 server and clients during migration |
| D36 | Process model | Interface and core in one process; core events serialisable for headless mode and a later daemon | proposed, confirmed 2026-11-13 | Separate engine process (generation 1): extra protocol, startup cost; the serialisable events keep that door open |
| D37 | Direct mode | None; the client always goes through the server | proposed, confirmed 2026-11-13 | Direct provider calls: bypasses keys, quota, policy and the evidence check (already out of scope in spec section 1) |
| D38 | Core design | Event-sourced core with a decider seam, so programme 3 replaces the decider, not the core | proposed, confirmed 2026-11-13 | State kept only in memory: no replay, no learning data |
| D39 | Evidence check | The server returns the system-brain evidence of a turn in `LarisMeta`; the client gate checks once before display | proposed, confirmed 2026-11-13 | Check on the server only: the server cannot see local tool results; check twice: duplicate logic (ADR-004) |
| D40 | Learning data | Derived on the client from the event log; never sent; outside Git | proposed, confirmed 2026-11-13 | Collect on the server: privacy and confidentiality |
| D41 | Scientific NLP | Python in the model block, reached as remote tools; the Rust client contains no NLP | proposed, confirmed 2026-11-13 | NLP in Rust: re-implements the model block and breaks D27 |
| D42 | Branches | `laris-v2` integrates; one feature branch per task is cut from it; `main` receives release 1.0.0 | proposed, confirmed 2026-11-13 | Git flow with `develop` (used by generation 1) rejected: two integration lines would split the ledger |
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

Verdict: D28 holds unchanged; the owner confirmed this reading on 2026-11-13.

## 4. Release tools (named here as T119 requires)
T119 approved "a release signing tool and a cross-compilation tool" without naming them. The owner delegated the
choice on 2026-11-13 ("chọn phương pháp phù hợp nhất, giống Claude Code"): one native binary per platform, built on
that platform, installed by a one-line script (D34). Chosen:
- Build: native CI runners for macOS and Windows, because the sandbox crates (landlock, seccomp, Windows APIs) must be
  built and tested on their own platform; `cross` only for the static Linux (musl) targets.
- Signing: `minisign` detached signatures over a checksum manifest, verified by the install script; platform code
  signing (macOS notarisation, Windows Authenticode) is added at release 1.0.0 if the owner holds the certificates.
Neither tool is installed or used before T121 and neither becomes a dependency of the Rust code.

## 5. Consequences
- Plan 2 phases follow the ladder (phases 31-34) while the loop, harness and prompt layers (phases 28-30) are built
  first.
- D37 removes one code path and one test matrix; users without a server cannot use the client.
- D40 means learning data can only be improved by the owner copying it deliberately.
- If the owner changes a decision, the spec table, the affected requirements and this ADR change together in one task.

## 6. Owner decision
2026-11-13: D28 and D35-D42 confirmed as proposed; release tools as chosen in section 4 (delegated).

## Addendum 2026-11-18: independence from generation 1

The owner decided that generation 2 is a complete upgrade and must not depend on generation 1: no shared wire
format, database schema, vault format, lock format or policy files. The ideas stay; nothing is reused. This
supersedes D35 (wire compatibility), D43 (generation-1 data stays readable) and every requirement that asks for
migration, adoption or parity with generation 1. `.laris/` is rewritten (Markdown for text, TOML for structure) and
the TOML format, with the `toml` crate and its transitive crates, was approved for it. Work already done under the
old rule (T142 migrations, T143 key digests, T145 parity fixtures, the P1/P2 fixtures) is listed in T215 for removal.
The `laris-v1` branch was removed on 2026-11-20.

## Addendum 2026-11-19: signing in T159

`minisign` (section 4) is not on the owner's machine and no new tool may be installed without approval. The owner chose
`openssl` instead: the checksum manifest `SHA256SUMS` is signed with ECDSA P-256 over SHA-256 (`openssl dgst -sha256
-sign`), and `install.sh` (openssl), `install.ps1` (.NET CNG) and the npm wrapper (Node crypto) check the same
signature against the public key written into them. ECDSA P-256 was preferred to Ed25519 because Windows PowerShell has
no Ed25519. Notarisation and Authenticode remain for release 1.0.0 if the owner holds the certificates.

## Addendum 2026-11-20: D28 and D39 amended by ADR-025

The owner accepted ADR-025. The agent loop, tool execution and the project vault stay on the client (D28's reason
stands); the per-request pipeline (Prefilter, retrieval, brain decider, model call, evidence gate, assembly) runs in
the server. The evidence check (D39) runs once per piece of evidence, by the side that holds it.

## Addendum 2026-11-23: the inference server image (T282)

The owner approved `vllm/vllm-openai:v0.34.0` (Apache-2.0) on 2026-11-23 so that chat and the STEM evaluation of
ADR-026 run on one engine and one precision (BF16). It is a container of the compose stack (`docker/compose.chat.yaml`,
service `vllm`), not a Python dependency: vLLM 0.34.0 pins `fastapi<0.137` and `torch==2.14.0`, which the project
environment cannot take. The model block reaches it over its OpenAI-compatible API with the standard library only
(`laris.model.inference.served_llm`). Constraints: weights mounted read-only and the hub offline, internal network
only (the loopback port for the benchmark runner is an opt-in overlay without masquerading), read-only root file
system, all capabilities dropped, usage statistics off. The `chat` extra (`torch`, `transformers`, `bitsandbytes`)
stays for the in-process `OpenWeightChat` and the transformers parity engine of T275; the packaged default no longer
builds it.
