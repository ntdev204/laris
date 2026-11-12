---
document_id: "DOC-DEV-SERVER-DEPLOYMENT-001"
title: "Server Deployment Runbook: Docker Compose, Secrets, Backup and Smoke Test"
document_type: "architecture"
status: "DRAFT"
version: "0.1.0"
created_at: "2026-11-12"
updated_at: "2026-11-12"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/development/OWNER_RUNBOOK.md"
  - "docs/adr/ADR-019-three-blocks-two-protocols-two-sql-engines.md"
decision_references:
  - "ADR-019"
change_summary: "Operator steps for the Docker Compose stack: first start, secrets, keys, policy changes, PostgreSQL backup and restore, retention, and the end-to-end smoke test."
---

# Server Deployment Runbook

The server side runs as four containers on one machine (ADR-019): **caddy** (TLS, the only published
ports), **api** (protocol P1, `laris-server`), **model** (protocol P2, `laris-model`, GPU) and
**postgres**. `api`, `model` and `postgres` sit on an internal Docker network with no route out. The
foundation model is **not qualified**; the stack serves whatever checkpoint you mount and says so in
its notices. This runbook covers operating the stack, not the quality of the model.

## 1. Prerequisites

- Docker Engine with the Compose plugin; for the GPU, the NVIDIA Container Toolkit
  (`docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi` must work).
- A checkout of this repository on the server (the stack mounts `.laris/` and `LARIS.md` from it).
- Ports 80 and 443 free (or set `LARIS_HTTP_PORT` and `LARIS_HTTPS_PORT`).

## 2. First start

```sh
docker/init-secrets.sh          # creates docker/secrets/{master.secret,postgres_password,database_url}
export LARIS_DOMAIN=laris.example.com      # a real name gets a public certificate; default: localhost
export LARIS_MODELS_DIR=/srv/laris/models  # read-only volume with the checkpoint and tokenizer
export LARIS_MODEL_CHECKPOINT=/models/laris.pt LARIS_MODEL_TOKENIZER=/models/tokenizer.model
docker compose -f docker/compose.yaml up -d --build
docker compose -f docker/compose.yaml ps       # everything "healthy"
```

Without a GPU add `-f docker/compose.cpu.yaml` (the model service then runs on CPU with the
placeholder backend; useful for CI and for trying the stack).

The API creates its built-in admin key on the first start and writes it to `/data/first-admin.key`
inside the `api_data` volume (mode 0600); it is never printed. Print it once with:

```sh
docker compose -f docker/compose.yaml exec api laris-server keys reveal default
```

That key works only from the server itself. Create keys for people with
`docker compose -f docker/compose.yaml exec api laris-server keys create --label NAME --role user --tokens N`
(a key is shown once; `keys reveal ID` can decrypt it again because the master secret is kept).

## 3. Secrets

Every secret is a Docker secret (a file mounted at `/run/secrets/…`), never an environment value:

| Secret | File | Used by |
| :--- | :--- | :--- |
| Master secret (encrypts stored API keys) | `docker/secrets/master.secret` | api |
| PostgreSQL password | `docker/secrets/postgres_password` | postgres |
| Database URL (contains that password) | `docker/secrets/database_url` | api |

`docker/secrets/` is git-ignored and created with mode 0700. **Back up `master.secret` apart from
the database dump**: the dump alone cannot decrypt stored keys, and a lost master secret makes
`keys reveal` impossible (keys still verify). Rotating the PostgreSQL password means changing the
file, the database user's password and `database_url` together.

## 4. Policy changes

Policy (`.laris/`, `LARIS.md`) is mounted read-only and covered by `integrity.lock`; the API refuses
to start when a protected file does not match (`prompts.integrity: enforce`). To change policy, with
the owner's approval:

```sh
laris-server harness verify && laris-server harness lock   # on the checkout
docker compose -f docker/compose.yaml restart api
```

A failing start (`docker compose logs api` shows "protected policy files do not match the integrity
lock") means someone edited policy without locking it: restore the files or re-lock after review.

## 5. Backup and restore

```sh
docker/backup.sh [DIR]                  # pg_dump -Fc of keys, usage and traces -> DIR/laris-<time>.dump
docker/backup.sh --with-secrets [DIR]   # also DIR/laris-secrets-<time>.tgz — store it elsewhere
docker/restore.sh DIR/laris-<time>.dump --yes   # stops api, replaces the data, starts api
```

Run the backup from cron or a systemd timer. Test a restore on a spare machine now and then: a backup
that has never been restored is not a backup.

## 6. Retention

`usage` and `traces` are partitioned by month. A background task (every
`serving.retention_interval_s`, default one hour) creates the coming months' partitions, writes the
daily usage summary (`usage_daily`) and drops partitions older than `serving.usage_retention_days`
(90) and `serving.trace_retention_days` (30). Days are summarised before their raw rows go.
Reasoning traces are for the operator only: `laris-server reasoning list|show|purge`.

## 7. Moving from the SQLite server

```sh
docker compose -f docker/compose.yaml cp old/laris-server.db api:/tmp/old.db
docker compose -f docker/compose.yaml exec api laris-server db import-sqlite /tmp/old.db
```

Keys, usage and traces are copied in one transaction; running it again adds nothing. Copy the old
master secret into `docker/secrets/master.secret` first, or the imported keys will not reveal.

## 8. Smoke test

```sh
docker/smoke_test.sh --cpu      # or without --cpu on a GPU machine
```

It brings the stack up on ports 18080/18443, creates a key, pins Caddy's certificate by fingerprint,
then from an empty folder with a fresh home runs `laris login`, a chat with the placeholder model, a
dense index and a dense search through the server, and checks that a wrong key gets 401. It removes
the stack afterwards (`--keep` leaves it running).

## 9. Image checks

```sh
docker build -f docker/api.Dockerfile -t laris-api .
docker build -f docker/model.Dockerfile -t laris-model .
python scripts/scan_image.py laris-api laris-model   # fails on policy, weights, data, .env, keys
```

`.dockerignore` keeps `.laris/`, `LARIS.md`, weights, datasets, databases and secrets out of the
build context, and the scan verifies the built images.

## 10. Troubleshooting

| Symptom | Look at |
| :--- | :--- |
| `api` restarts at once | `docker compose logs api`: integrity lock, missing secret, or PostgreSQL not ready |
| 429 for a key | its token quota is used up: `laris-server keys limit ID --add N` |
| Clients see 426 | the client is older than the server's protocol; update the client |
| Wrong client address in key rules | check `serving.trusted_proxies` matches the Caddy subnet (172.31.0.0/24) |
| Model service unhealthy | GPU not visible to Docker, or `LARIS_MODEL_CHECKPOINT` wrong |
