---
document_id: "DOC-ADR-019"
title: "ADR-019: Three Blocks, Two Protocols, Two SQL Engines, Docker, Terminal Client"
document_type: "adr"
status: "ACCEPTED"
version: "1.0.0"
created_at: "2026-11-12"
updated_at: "2026-11-12"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/adr/ADR-015-local-data-plane-and-authenticated-server.md"
  - "docs/adr/ADR-016-policy-server-and-thin-client.md"
  - "docs/adr/ADR-018-server-database-keys-and-reasoning.md"
decision_references:
  - "ADR-013"
  - "ADR-015"
  - "ADR-016"
  - "ADR-018"
change_summary: "Restructures the system into client, server and model blocks with two protocols (P1 client-server, P2 server-model), PostgreSQL on the server, SQLite on the client, Docker deployment and a Claude-Code-style Ink terminal client. Records decisions D10 to D23 and the dependency approvals."
---

# ADR-019: Three Blocks, Two Protocols, Two SQL Engines, Docker, Terminal Client

## Metadata
- **ADR ID:** ADR-019
- **Status:** ACCEPTED (owner instruction, 2026-11-12)
- **Amends:** ADR-015 (embedding path, server storage, client data in the global home), ADR-016 (no
  offline mode, protocol version, global home and isolated runtime, project `.laris/` without
  configuration, login without `--server`), ADR-018 (PostgreSQL instead of SQLite, trusted proxy).
- **Ledger:** `.claude/spec/spec.md` section 4b holds the decision table; task T48 records this ADR.

## 1. Decision

The decisions D10 to D23 of the ledger are adopted as written in `spec.md` section 4b. Summary:

1. **D10, D11 Blocks.** `client` (user machine), `server` (API, policy, brain, keys) and `model`
   (inference on the GPU), plus the libraries `protocol` and `shared` and the owner-only `research`
   tooling, under `src/laris/{protocol,shared,client,server,model,research}`. Blocks import only
   `protocol` and `shared`; nothing imports `research`; a contract test enforces it.
2. **D12 Protocols.** P1 client-server (public, HTTPS and SSE, versioned by `X-Laris-Protocol`); P2
   server-model (internal Docker network, OpenAI-compatible chat completions and embeddings).
3. **D13 Storage.** PostgreSQL on the server (keys, usage, traces); SQLite on the client
   (conversations, workspace, embedding cache, learning data, vault index cache). Vault notes stay
   Markdown files.
4. **D14 Deployment.** One server machine; `docker compose` runs Caddy (TLS, timeouts, body limit, rate
   limit), the API, the model (GPU) and PostgreSQL. The client is not containerised and ships through npm.
5. **D15 Dependencies.** See section 2.
6. **D16 Model placement.** No offline mode in the client; `OfflinePlanner` becomes the placeholder model
   backend and a test fixture; embeddings are computed only by the model block and reached through
   `POST /v1/laris/embed`; the client never holds weights.
7. **D17 to D23 Terminal client.** `laris` works like Claude Code (slash commands, one global settings
   file, permission modes and rules, coding tools with diffs and checkpoints, headless mode, hooks,
   status line, interrupt, automatic sandbox). `~/.laris/` holds every client configuration and
   credential (D18); the program (PyInstaller binary) and the sandbox `~/.laris/.venv/` are kept apart
   (D19, D23); a project `./.laris/` carries no configuration (D20); the server address is
   `server.url` in `settings.json` and `laris login` takes no `--server` flag (D21); one engine
   (`laris engine --stdio`, protocol E1) and one Ink front end, with headless `laris -p` and `laris
   --plain` as dependency-free fallbacks (D22).

## 2. Dependency approvals (rule: no dependency without recorded approval)

Approved by the owner on 2026-11-12. Versions are the latest stable releases checked on 2026-11-12;
a bump needs a ledger entry.

| Where | Dependency | Pin | Notes |
|---|---|---|---|
| Python extra `server` | `fastapi`, `uvicorn`, `psycopg[binary]`, `psycopg_pool`, `cryptography` | `fastapi>=0.162,<1`, `uvicorn>=0.54,<1`, `psycopg[binary]>=3.3,<4`, `psycopg_pool>=3.3,<4`, `cryptography>=42,<51` | `cryptography` was approved in ADR-018 |
| Python extra `model` | `fastapi`, `uvicorn` | same ranges | the model block needs no database driver |
| Container images | Caddy, PostgreSQL | tags pinned in T68 | not Python dependencies |
| npm (client front end) | `ink`, `react` | `ink` 8.0.0, `react` 19.3.1 (Ink 8 requires react >= 19.3.0) | exact versions, no ranges |
| Sandbox provisioning | `uv` single binary, one per platform in the npm platform package | 0.13.1 | fetches standalone Python and builds `~/.laris/.venv/` |
| Dropped | `prompt_toolkit`, `rich` | n/a | approved, then dropped with the Python front end (D22) |

Further Ink component packages (spinners, text input and similar) are **not** approved by this ADR; the
front end uses `ink` and `react` only until the owner approves another by name.

## 2b. Block map (owner confirmed the proposal, 2026-11-12; applied by T50, adjusted by T51)

| Block | Contents |
|---|---|
| `laris.protocol` | wire types, SSE, P1 and P2 schemas, protocol version, key check (T49) |
| `laris.shared` | `core`, `config`, `retrieval`, `graph`, `scientific`, `scholarly`, `skills`; `vault` (parser, index, writer, schema, lint, search, repair, project vault, entities, memory); `harness` (audit, guard, integrity, prefs, strings, trust, runtime, remote, credentials); `policy` (prompts, policy, workflows, verifier); `brain`; `plan`; `offline` (placeholder planner); `corpus` (schemas, normalizer); `language` (encoder, tokenization, schemas, loading) |
| `laris.client` | `agent`, `application`, `learning`, `vault` (hooks, knowledge, proposals), `harness` (package marker) |
| `laris.server` | `gateway`, `serving`, `serverdata` |
| `laris.model` | `execution`, `inference` |
| `laris.research` | `corpus`, `evaluation`, `orchestration`, `reasoning`, `reporting`, `language` (training, evaluation, benchmarks) |

`cli` stays at the top level until T52 splits the entry points. T51 enforces the boundaries. To make
the test pass without changing behaviour, the policy composer, brain loader and harness runtime sit in
`shared` because the client still composes policy locally (no `policy_source: server` yet) and the
server gateway uses the same runtime; the confidential policy and brain *data* remain server-only. They
move to `server` when the client's local policy path is removed. One edge is still listed in the test:
the client embeds locally through `laris.model.inference` until T58.

## 3. Consequences

- Package paths change in Phase 10 (T50) without behaviour change; the full no-training suite must give
  the same result before and after.
- Client and server must be released together as 2.0.0 (protocol and server storage change); a mismatch
  is refused through `X-Laris-Protocol`.
- The client no longer holds any configuration in the repository folder, so a cloned repository cannot
  change permissions, hooks, server address or model.
- The model block is the only holder of weights and VRAM; chat and embeddings share one GPU queue.
- Release 2.0.0 needs the owner's authorisation (AGENTS.md).
- The foundation model remains NOT QUALIFIED; this ADR restructures the harness and says nothing about
  model capability.

## 4. Validation

`validate_docs` and `validate_spec` pass; `pyproject.toml` extras `server` and `model` match section 2;
the block contract test (T51) enforces consequence 1 once the move is done.
