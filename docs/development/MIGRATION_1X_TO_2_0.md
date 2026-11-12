---
document_id: "DOC-DEV-MIGRATION-2-0-001"
title: "Migration Guide: LARIS 1.x to 2.0"
document_type: "architecture"
status: "DRAFT"
version: "0.1.0"
created_at: "2026-11-13"
updated_at: "2026-11-13"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/development/CLI.md"
  - "docs/development/SERVER_DEPLOYMENT_RUNBOOK.md"
  - "docs/architecture/SYSTEM_OVERVIEW.md"
  - "docs/adr/ADR-019-three-blocks-two-protocols-two-sql-engines.md"
decision_references:
  - "ADR-019"
change_summary: "What changes for users and operators between 1.x and 2.0 (client, server, protocols, storage, commands, settings), the automatic migrations and their backups, the manual steps, and how to roll back."
---

# Migration Guide: LARIS 1.x to 2.0

Release 2.0 restructures LARIS into three blocks (client, server, model) with two protocols
([ADR-019](../adr/ADR-019-three-blocks-two-protocols-two-sql-engines.md); overview in
[SYSTEM_OVERVIEW](../architecture/SYSTEM_OVERVIEW.md) section 1b). **Client and server must be upgraded together**:
a client and a server that disagree on the protocol version refuse each other (HTTP 426, "update the client").
This guide describes the change, not the quality of any model; the foundation model is **not qualified** in 1.x
and in 2.0.

Release 2.0.0 itself needs the owner's authorisation (T85); until it is published, this guide describes the
branch behaviour.

## 1. What changed

| Area | 1.x | 2.0 |
| :--- | :--- | :--- |
| Programs | `laris` (client), `laris-server` | `laris` (client), `laris-server` (API and operator), `laris-model` (model service) |
| Interface | Python line-input loop (a web UI was removed on 2026-11-11) | Ink and React front end (`laris`), `laris --plain`, headless `laris -p`; one engine behind all three (protocol E1) |
| Node | not needed | **Node 22 or newer** for the Ink front end (plain and headless need no Node) |
| Server process | one process, SQLite file, optional TLS | Docker Compose: Caddy, API, model service, PostgreSQL; only Caddy publishes ports |
| Server storage | SQLite (`laris-server.db`) | PostgreSQL (keys, usage, traces, monthly partitions, retention) |
| Client storage | JSON and JSONL files under `artifacts/` | one SQLite file per project and key under `~/.laris/projects/<slug>/` |
| Embeddings | computed locally from a checkpoint | computed by the model service and reached through the server (`POST /v1/laris/embed`); cached in SQLite |
| Offline mode | available | removed: the client needs a server |
| Settings | flat `settings.json`, `config.yaml`, project `.laris/config.yaml`, `.env` | one nested, schema-validated `~/.laris/settings.json`; project files are ignored |
| Credentials | `api_key` in `settings.json` or `credentials.json` | `~/.laris/.credentials.json` (mode 0600) |
| Permissions | one approval question | modes (`default`, `acceptEdits`, `plan`, `bypass`), `allow`/`ask`/`deny` rules, scopes (once, session, project, everywhere) |
| Hooks | none | five events, declared only in `~/.laris/settings.json` |
| Sandbox | per-version `runtime/` copy | `~/.laris/.venv`, built and repaired by `uv` |
| Training, data and evaluation commands | `laris data\|train\|evaluate` | `laris-server data\|train\|evaluate`; `infer` is `laris-model infer` |

## 2. For users (client)

1. Install the new client (`npm i -g @ntdev204/laris-cli`; Node 22 or newer for the Ink interface). Without Node,
   use `laris --plain` or `laris -p`.
2. Start `laris` once. The first start **migrates `~/.laris/` automatically** and prints one line per change:
   - the flat 1.x `settings.json` becomes the nested shape (mapping below);
   - `api_key` in it, or `credentials.json`, moves to `.credentials.json` (mode 0600);
   - `config.yaml` is folded into `settings.json` (the few values that have a place there);
   - the legacy `runtime/` folder is removed (it was a program copy, not data).
   Every file that is rewritten or removed is first copied to `~/.laris/backups/` (the removed `runtime/` folder
   is not copied). A second start finds nothing to migrate. Nothing is overwritten that already exists.
3. Old data is imported once and left in place: `chunks.jsonl`, conversation `*.json` and the learning `*.jsonl`
   files go into SQLite; each source is copied to a `backups/` folder beside the database first, and a second run
   changes nothing.
4. Set the server address if the migration did not carry it: `laris config set server.url https://HOST/v1`, then
   `laris login`. The server address is no longer a flag of every command (`laris login --server URL` is still
   accepted as a shortcut).
5. The sandbox (`~/.laris/.venv`) is built on first use without action; `/sandbox` shows its state and `/doctor` checks it.

**Settings mapping (flat 1.x to nested 2.0).**

| 1.x key | 2.0 path |
| :--- | :--- |
| `base_url` | `server.url` |
| `model` | `model` |
| `auto_compact`, `context_window`, `compact_threshold` | `context.autoCompact`, `context.windowTokens`, `context.compactThreshold` |
| `allow_write` | `permissions.defaultMode` (`true` becomes `acceptEdits`, `false` becomes `default`) |
| `learning_enabled` | `learning.collect` |
| `vault_record` | `vault.autoRecord` |
| `extra_instructions` | `extraInstructions` |
| `config.yaml`: `model_api.base_url`, `timeout_s`, `model` | `server.url`, `server.timeoutSeconds`, `model` |
| anything else in `config.yaml` | not carried; the original stays in `backups/` |

**Behaviour that differs and may surprise you.**

- A project folder no longer configures `laris`. A `.laris/config.yaml`, `settings.json`, `settings.local.json` or a
  `.env` that sets `LARIS_*` is ignored, with a warning that names it. Move what you need into
  `~/.laris/settings.json` (`laris config set`).
- A project's own commands and skills load only after `/trust` in that folder.
- An `allow` rule such as `Bash(git status:*)` allows exactly that command; a chained line
  (`git status && rm -rf ~`) is no longer covered by it. Rewrite rules that relied on the old behaviour.
- Installing packages outside the sandbox is refused in every mode.
- Hooks are new and live only in `~/.laris/settings.json`.
- Headless `laris -p` cannot ask for permission: an action without an allow rule is refused and listed in
  `permission_denials`. Pass `--allowed-tools` for what a script needs. Exit codes: 0, 1, 2, 3 and 130
  ([CLI reference](CLI.md) section 1.1).
- The training, data and evaluation commands are not in the client any more; see section 4.
- Dense search needs a server. Without one only BM25 search works.

## 3. For operators (server)

1. Read the [deployment runbook](SERVER_DEPLOYMENT_RUNBOOK.md). Install Docker with the Compose plugin (and the NVIDIA
   container toolkit for a GPU).
2. **Before importing, copy the old master secret** into `docker/secrets/master.secret` (the file or value of
   `LARIS_SERVER_MASTER` of the 1.x server). Imported keys cannot be revealed without it, although they still verify.
3. `docker/init-secrets.sh`, set `LARIS_DOMAIN`, `LARIS_MODELS_DIR`, `LARIS_MODEL_CHECKPOINT` and
   `LARIS_MODEL_TOKENIZER`, then `docker compose -f docker/compose.yaml up -d --build`.
4. Import the old database in one transaction (running it again adds nothing):
   `docker compose -f docker/compose.yaml cp old/laris-server.db api:/tmp/old.db` and
   `docker compose -f docker/compose.yaml exec api laris-server db import-sqlite /tmp/old.db`.
5. Point DNS at the machine. Caddy obtains a certificate for a real domain; for a private name, give clients the
   fingerprint to pin (`laris login` shows it).
6. Policy (`.laris/`, `LARIS.md`) is mounted read-only; the API refuses to start when a protected file differs from
   `integrity.lock`. Change policy only with the owner's approval, then `laris-server harness verify` and `lock`.
7. Run `docker/smoke_test.sh` (and `--cpu` where there is no GPU) before telling users to upgrade.
8. Back up with `docker/backup.sh --with-secrets` and test a restore on a spare machine.

What is different to operate: only Caddy publishes ports; the API trusts forwarded addresses only from the Caddy
subnet (`serving.trusted_proxies`); Caddy sets header, body and idle timeouts and a 32 MB body limit; usage rows are
dropped after 90 days and traces after 30; the model's reasoning stays on the server for the operator.
A 1.x client that connects to a 2.0 server gets 426.

## 4. For the owner (research tooling)

| 1.x | 2.0 |
| :--- | :--- |
| `laris data acquire\|partition\|check` | `laris-server data acquire\|partition\|check` |
| `laris train tokenizer\|language-encoder` | `laris-server train tokenizer\|language-encoder` |
| `laris evaluate readiness\|language-encoder\|calibrate\|suite` | `laris-server evaluate ...` |
| `laris infer ...` | `laris-model infer ...` |
| `laris-server app index\|ask` | `laris app index` (through the server); `ask` is removed (extractive answers need a QA model on the server, not available yet), use `laris app search` |
| `laris model serve` | `laris-server model serve` (single process) or the `api` and `model` containers |

Authorisation rules did not change: nothing trains or fits without `--authorized` and `LARIS_TRAINING_AUTHORIZED=1`,
and `src/laris/research` (data, training, evaluation) is imported by no other block.

## 5. For developers

- Source paths moved into blocks: `src/laris/{protocol,shared,client,server,model,research}` (map in ADR-019 section
  2b). The `cli` package stays at `src/cli`. Imports from the old flat `laris.*` modules must be updated; a contract
  test enforces that blocks import only `protocol` and `shared`.
- New test suites: `tests/acceptance` (`make test-client`), `tests/security` (`make test-security`) and the Node
  tests in `packaging/npm` (`npm test`). PostgreSQL tests run when `LARIS_TEST_PG_DSN` is set.
- Run tests with a temporary `HOME`; a command or test that uses the real `~/.laris` migrates it.

## 6. Rolling back

- **Client:** install the 1.x package again. The migrated `settings.json` has a different shape and a 1.x client
  expects the flat shape; restore the old files from `~/.laris/backups/` (`settings.json.*.bak`, `config.yaml.*.bak`,
  `credentials.json.*.bak`) and put the API key back. Data imported into SQLite is left untouched; the old JSON files
  were never deleted. The removed `runtime/` folder is rebuilt by the old client.
- **Server:** keep the old SQLite file and the old process until the new stack has served real traffic. The importer
  only reads the old database. To go back, stop the stack and start the 1.x server with its own database and master
  secret; usage recorded in PostgreSQL after the move is not copied back.

## 7. Check that the migration worked

```bash
laris config get              # server.url and model are what you expect
laris whoami                  # role and tokens left, which proves the key and the protocol match
laris -p "hello" --output-format json   # one turn through the engine
```

On the server: `docker compose -f docker/compose.yaml ps` shows every service healthy, `laris-server keys list`
shows the imported keys, and the smoke test passes.
