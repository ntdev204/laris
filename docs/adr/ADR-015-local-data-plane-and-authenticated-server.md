---
document_id: "DOC-ADR-015"
title: "ADR-015: Local Data Plane (User Disk = Database, User Machine = Sandbox) and Authenticated Server"
document_type: "adr"
status: "ACCEPTED"
version: "1.0.0"
created_at: "2026-11-11"
updated_at: "2026-11-12"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/adr/ADR-014-obsidian-compatible-brain.md"
  - "docs/architecture/AGENT_HARNESS.md"
  - "docs/architecture/BRAIN_THREAT_MODEL.md"
decision_references:
  - "ADR-019"
  - "ADR-014"
change_summary: "Fixes where data lives and where code runs: everything on the user's machine except model inference, which is served by an authenticated, stateless server."
---

# ADR-015: Local Data Plane and Authenticated Server

## Metadata
- **ADR ID:** ADR-015
- **Status:** ACCEPTED
- **Date Decided:** 2026-11-11
- **Decision Owner:** project owner

## 1. Decision

1. **The user's disk is the system's database.** Documents, workspace index, vault, skills, memory,
   conversations, uploads and collected data are files on the user's machine. The project folder carries
   vault, skills and memory; conversations and settings are kept per API key under
   `artifacts/chat/users/<fingerprint>/`.
2. **The user's machine is the sandbox.** The harness, every tool (reading, OCR, ingestion, extraction,
   writes) and all file access run in the `laris` client, confined by its path policy and approval rules.
3. **The server only authenticates and infers.** `laris model serve` accepts a request only with an
   accepted API key, runs the model on the messages in the request and returns the result. It stores no
   user data, writes no files and logs no content. It refuses to start without keys.
4. **Keys.** Accepted keys are provided by the operator through an environment variable or a key file
   (fixed keys are acceptable for testing). The server keeps SHA-256 digests only; the client checks its
   key at `laris login` and when a session starts, and never saves a rejected key.
5. **What crosses the wire.** The system prompt, the brain brief and tool results are sent to the server
   with each request. That is acceptable only because the server is the owner's own; remote use must be
   enabled explicitly with `model_api.allow_remote` (rule C-4), and transport security (TLS) comes from
   a reverse proxy in front of the server.

## 1b. Amendment by ADR-019 (2026-11-12)

- **Embedding path.** The client never holds weights. Embeddings are computed only by the model block and
  reached through `POST /v1/laris/embed` on the server (D16).
- **Server storage.** Item 3 ("stores nothing") stays amended by ADR-018 and now by ADR-019: the server
  keeps keys, usage and traces in PostgreSQL (D13). User documents, vault, skills and memory still never
  reach the server's disk.
- **Client data.** Conversations, workspace, embedding cache, learning data and the vault index cache are
  kept in SQLite under the global home `~/.laris/projects/<slug>/` instead of `artifacts/chat/users/` (D13, D18).

## 2. Consequences

- No central user database to protect or migrate; backups are the user's own.
- The server scales by adding model capacity only; there is nothing to synchronise between users.
- Because inference sees prompts, the server operator can read them in memory; the server must not
  persist or log them (enforced by a contract test over the `serving` package).
- Not done: rate limiting of failed attempts, key rotation without restart, per-key quotas.

## 3. Validation

`tests/unit/cli/test_server_auth.py` (keys, 401, refusal to start, stateless contract),
`tests/unit/cli/test_account.py` (private spaces).
