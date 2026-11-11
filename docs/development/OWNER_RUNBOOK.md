---
document_id: "DOC-DEV-OWNER-RUNBOOK-001"
title: "Owner Runbook: Running the LARIS Server, Keys, Policy and Releases"
document_type: "architecture"
status: "DRAFT"
version: "0.1.0"
created_at: "2026-11-11"
updated_at: "2026-11-11"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/development/CLI.md"
  - "docs/development/GIT_FLOW.md"
  - "docs/architecture/BRAIN_AND_VAULT.md"
decision_references:
  - "ADR-015"
  - "ADR-016"
  - "ADR-018"
change_summary: "Step-by-step operations for the system owner: server start, TLS, keys, reasoning traces, policy changes, client build and release."
---

# Owner Runbook

Commands run from the codebase that holds the system `.laris/` on the server, with `laris-server`.

## 1. Start the server

1. `pip install -e ".[server]"` (adds `cryptography` for key encryption).
2. `laris-server tls init --host your.domain --host 203.0.113.5` writes a self-signed certificate and a
   0600 key to `~/.laris-server/tls`. With a real certificate authority, copy its `cert.pem` and `key.pem`
   there instead; clients then need nothing. `tls init` and `model serve` print the certificate
fingerprint: publish it through another channel (chat, the website), and users run `laris login --server
https://HOST:PORT/v1 --trust-fingerprint SHA256:...` once. The client pins that certificate for that server only.
3. `laris-server model serve --host 0.0.0.0 --port 8443` serves HTTPS. Without a certificate it refuses to
   bind outside loopback. The first start creates the built-in admin key and prints it once.
4. Keep `~/.laris-server/master.secret` (or the variable `LARIS_SERVER_MASTER`) safe and backed up
   *separately from the database*: without it the stored keys cannot be decrypted.

If you change the certificate, users must run `laris login --server ...` again and confirm the new
fingerprint; a different certificate is never accepted silently.

## 2. Keys and quotas

`laris-server keys create --label NAME --role user --tokens 200000` (`--tokens unlimited`, `--allow-ip CIDR`,
`--expires-days N`), `keys list`, `keys show ID`, `keys limit ID --tokens N --add`, `keys revoke ID`,
`keys reveal ID|default`, `keys ip ID --allow CIDR|@server` (`--clear` removes the rule), `usage summary`. Roles are in `serving.roles`. A revocation takes effect within
`serving.cache_ttl_s` (default 5 s).

## 3. Model reasoning

The model's private reasoning is never sent to a client. It is stored (redacted) for you:
`laris-server reasoning list|show ID|purge --days N`. It contains users' task text, so treat the database
as confidential; the user guide tells users it is stored. Retention: `serving.trace_retention_days`.

## 4. Changing policy

Policy files (`LARIS.md`, `.laris/{prompts,rules,workflows,help,brain,vault}`) are under
`.laris/integrity.lock`. After an approved change: `laris-server harness verify`, then `harness lock`,
commit the lock with the change. A session refuses to start on a mismatch.

## 5. Backups

Back up the database folder (`serving.data_dir`) and the master secret to different places. The database is
SQLite in WAL mode: copy with `sqlite3 laris-server.db ".backup backup.db"` while the server runs.

## 6. Build and release

1. `python scripts/validate_spec.py`, `make check-no-training`, and on the workstation `make bench-vault`.
2. Push the release branch: the **Client package (all platforms)** workflow
   (`.github/workflows/client-package.yml`) freezes the client into a self-contained program on Linux
   x64/arm64, macOS Apple Silicon/Intel and Windows x64 (`packaging/build_client.py` compiles the wheel,
   `packaging/build_binary.py` freezes it, `packaging/assemble_npm.py` builds six npm packages) and
   smoke-tests each program. No Python is needed on the user's machine.
3. Follow `docs/development/GIT_FLOW.md`: feature branch, pull request to `develop`, release branch, tag.
4. Pushing the `v*` tag makes the same workflow **publish to npm**: the five platform packages first, then
   the launcher; versions already on the registry are skipped, so a re-run is safe. One-off setup: create a
   granular npm access token (read and write, `@ntdev204` packages, no 2FA prompt for publishing) and store
   it as the repository secret `NPM_TOKEN`. Without it the publish job stops with a clear error.
   Users install only `@ntdev204/laris-cli`; npm fetches the matching platform package.
5. Never publish without the owner's explicit authorisation for that release.

## 7. What is not covered

Training and fine-tuning are not run by any agent (`AGENTS.md`); the core model is NOT QUALIFIED. Rate
limits per role, key rotation helpers and automatic backups are not implemented.
