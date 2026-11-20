---
document_id: "DOC-DEPLOY-RUNBOOK-001"
title: "Deployment runbook"
document_type: "architecture"
status: "DRAFT"
version: "0.1.0"
created_at: "2026-11-19"
updated_at: "2026-11-20"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/adr/ADR-021-rust-generation.md"
decision_references:
  - "ADR-021"
change_summary: "Front matter added; the self-trained model is removed, the model service serves an open-weight chat model (T233)."
---

# Deployment runbook (SR-S8)

One machine runs four containers from `docker/compose.yaml`: **Caddy** (the only one that publishes ports),
**laris-server** (static, non-root Rust API), the **model service** (Python, P2) and **PostgreSQL**. The server,
model and database sit on an internal network with no route out.

The placeholder backend answers chat until a chat model is configured (`model_service.backend`). A green smoke test
proves the mechanics of the stack, not a capability: no model is qualified.

## What is where

| Thing | Where | How it reaches the container |
|---|---|---|
| Policy (`.laris/`) | the repository | bind mount, read-only; the server refuses to start if it differs from `integrity.toml` |
| Weights | `LARIS_MODELS_DIR` (default `artifacts/weights`) | bind mount, read-only |
| Master secret, database URL, database password | `docker/secrets/*` (git-ignored) | Docker secrets (files, never environment) |
| First admin key | volume `server_state`, file `first_admin_key` | written once at the first start |
| TLS authority and certificates | volume `caddy_data` | **never remove it** |
| Database | volume `pgdata` | PostgreSQL 16 |

Images hold code only: `docker/verify-images.sh` fails if one holds policy, weights or secrets.

## First start

```sh
docker/init-secrets.sh                    # once; never overwrites
export LARIS_DOMAIN=host.example.org      # or localhost / an IP address (Caddy's own authority)
export LARIS_MODELS_DIR=/path/to/models   # optional: chat model weights, read-only
docker compose -f docker/compose.yaml up -d --build --wait
docker/verify-images.sh
docker compose -f docker/compose.yaml cp server:/state/first_admin_key -   # the first admin key, shown once
```

Ports default to 80 and 443; set `LARIS_HTTP_PORT` and `LARIS_HTTPS_PORT` to move them (the trial server uses 18080
and 18443). To serve an open-weight chat model set `LARIS_MODEL_BACKEND` to
`laris.model.inference.open_llm:OpenWeightChat` and `LARIS_MODEL_SERVICE__CHAT_MODEL_ID` to a path under `/weights`
(the image installs only the `model` extra, so the `chat` extra would have to be added first; see T231). A GPU needs
a compose override that reserves the device; none is shipped because the placeholder runs on CPU.

## Smoke test

```sh
docker/smoke_test.sh
```

It builds and starts a separate project (`laris-smoke`, ports 28080/28443, its own volumes), checks that only Caddy
publishes ports, health through Caddy, the first admin key, a user key, one chat answer, the account, a trace
without message text, and the policy lock; then removes the smoke project. A running server of the project `laris`
is not touched.

## Upgrading the trial server

The compose file keeps the trial server's volumes: `laris_caddy_data`, `laris_caddy_config` and `laris_pgdata`
(project name `laris`, volumes `caddy_data`, `caddy_config`, `pgdata`). Clients that pinned Caddy's authority keep
working because `caddy_data` survives.

1. Back up first: `docker/backup.sh --with-secrets /safe/place`.
2. Stop the old stack **without** `-v`: `docker compose -f docker/compose.yaml stop` (never `down -v`, never remove
   `caddy_data`). Generation 1 ran the same project name; its `api` container is removed by `up --remove-orphans`.
3. Start the new stack with the same `LARIS_DOMAIN`, `LARIS_HTTP_PORT` and `LARIS_HTTPS_PORT` as before.
4. Generation 2 stands alone: it uses the PostgreSQL schema `laris2` in the same database and leaves generation 1's
   tables as they are. It does not read generation 1's keys; create new ones.
5. Check: `curl -k https://<domain>:<port>/.well-known/laris/ca.crt | openssl x509 -noout -fingerprint -sha256`
   is the fingerprint clients pinned, and `docker volume inspect laris_caddy_data` still exists.

The owner runs this on the trial machine (AGENTS.md: push, tag and release stay with the owner).

## Keys

```sh
docker compose -f docker/compose.yaml cp server:/state/first_admin_key -     # admin key, first start only
curl -sk -X POST https://<domain>/v1/admin/keys -H "Authorization: Bearer $ADMIN" \
     -H 'Content-Type: application/json' -d '{"label":"alice","role":"user","token_limit":1000000}'
```

The key text is shown once. Revoke with `POST /v1/admin/keys/{id}/revoke`.

## Policy changes

Change `.laris/` only with the owner's approval, then refresh the lock with `laris-server policy lock` (run against
the repository checkout) and restart the server: `docker compose -f docker/compose.yaml restart server`.

## Backup and restore

`docker/backup.sh [--with-secrets] [DIR]` writes a `pg_dump` (custom format); `docker/restore.sh DUMP` restores it.
The dump alone cannot reveal stored keys: keep `docker/secrets/master.secret` in a different place.

## Logs and health

`docker compose -f docker/compose.yaml ps` shows health; `logs -f server`. Caddy removes `Authorization` from its
logs; the server's traces hold no message text.
