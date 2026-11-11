---
document_id: "DOC-ADR-016"
title: "ADR-016: Policy Server and Thin Client (system .laris stays on the server)"
document_type: "adr"
status: "ACCEPTED"
version: "1.0.0"
created_at: "2026-11-11"
updated_at: "2026-11-11"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/adr/ADR-015-local-data-plane-and-authenticated-server.md"
  - "docs/architecture/AGENT_HARNESS.md"
  - "docs/architecture/BRAIN_THREAT_MODEL.md"
decision_references:
  - "ADR-015"
change_summary: "The system prompt, rules, workflows and brain move to the server; the downloadable client (npm i -g @ntdev204/laris-cli) never contains them. Client state lives in a global and a project .laris/."
---

# ADR-016: Policy Server and Thin Client

## Metadata
- **ADR ID:** ADR-016
- **Status:** ACCEPTED (owner instruction, 2026-11-11: "work like Claude Code, install with npm, do not reveal the system .laris, client .laris exists in two places: global and project")
- **Supersedes:** ADR-015 section 1.5 (what crosses the wire) and the "server only infers" part of item 3.

## 1. Decision

1. **System policy is server-only.** `.laris/prompts`, `rules`, `workflows`, `brain`, `help`, `LARIS.md`
   and `integrity.lock` exist only in the server's policy root (`laris-server model serve --policy-root`).
   The server verifies integrity at start, composes the system prompt for every request, runs the
   brain consult and brain tools itself, applies the leak/secret guard (canary derived per session
   from a process secret) and returns only text and the client's own tool calls.
2. **Wire protocol.** `POST /v1/laris/chat` (stream) carries the conversation, the client's tool schemas
   and `laris` metadata: session id, task, optional workflow (name and request), and the user's own
   layers (instruction files, skills index, memory, preferences). `GET /v1/laris/workflows` returns
   workflow *limits* (tools, steps, approval, required sections), never phases; `GET /v1/laris/help`
   returns the user guide. The bare `/v1/chat/completions` endpoint is closed when the gateway runs, a
   client-sent `system` message is dropped, and summarisation uses the server's own instruction.
3. **The client is thin.** Tools, path policy, approval prompts, ingestion, vault, skills, memory,
   conversations and OCR run on the user's machine (ADR-015 stands). With no `.laris/prompts` in the
   project (`app.policy_source: auto`) the client uses the server policy; there is no offline mode.
4. **Two client folders.** Global `~/.laris/` (`credentials.json` mode 0600, `config.yaml` with the server
   address, `LARIS.md` personal instructions, `skills/`, `memory/`) and project `./.laris/` (`config.yaml`,
   `LARIS.md`, `skills/`, `memory/`). Project layers win over global ones; `laris init` creates the
   project folder, `laris login --server URL` writes the global address.
5. **Server.** `laris-server model serve` runs in the codebase (policy root = current folder or
   `--policy-root`): it starts the model and the brain and reads the whole system `.laris/`. The operator
   does not log in; only clients present API keys.
6. **Distribution.** The npm package `@ntdev204/laris-cli` is a launcher plus a client-only wheel built by
   `packaging/build_client.py` from the modules `cli.client` can reach (no gateway, serving, server or
   operator commands, no `.laris/` policy). It creates a private virtualenv under
   `~/.laris/runtime/<version>` on first run, and the client creates `~/.laris/` (`settings.json`,
   `config.yaml`, `LARIS.md`, `skills/`, `memory/`) on first start without overwriting anything.

## 2. Consequences

- The client holds nothing confidential: a user can read the client code, not the prompt, rules, workflows
  or brain. Prompt extraction now needs a model-level attack that passes the server-side leak guard.
- The server sees the user's tool results (documents they read) as before; it still stores nothing.
- The model-callable brain tools no longer see the project's own `Knowledge/` notes (they are on the
  client); `save_knowledge` stays a client tool and files by the domain the model names, else `General`.
- Workflow `max_steps`, approval and citations are enforced by the client loop; the allowed-tool list is
  enforced on both sides.
- The wheel is compiled (Cython, owner-approved build-time tool): no Python source, C source or docstrings
  ship. Native code is not a secret store - determined reverse engineering remains possible - so
  confidential content stays on the server regardless. Wheels are per Python version and platform; a
  release needs a build matrix (CI) before publishing.
- TLS: the server serves HTTPS when given a certificate and key and refuses plain HTTP off loopback.
- Preferences are global (`~/.laris/settings.json`) and shared by every key on the machine;
  conversations stay per key.
- Not done: key rotation, quotas, the build matrix, publishing to npm.

## 3. Validation

`tests/unit/gateway/test_policy_server.py`: an empty folder works against the server; policy text never
appears in the stream even when the model leaks it; client `system` messages are ignored; the bare
endpoint is closed; the gateway imports no user-data code and writes no files.
