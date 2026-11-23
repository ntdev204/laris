---
document_id: "DOC-DEPLOY-RUNBOOK-001"
title: "Deployment runbook"
document_type: "architecture"
status: "DRAFT"
version: "0.1.0"
created_at: "2026-11-19"
updated_at: "2026-11-23"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/adr/ADR-021-rust-generation.md"
decision_references:
  - "ADR-021"
change_summary: "T282: the chat model is served by one vLLM server (BF16) that chat and the STEM benchmark runner share. Earlier: front matter added; the self-trained model is removed, the model service serves an open-weight chat model (T233)."
---

# Deployment runbook (SR-S8)

One machine runs four containers from `docker/compose.yaml`: **Caddy** (the only one that publishes ports),
**laris-server** (static, non-root Rust API), the **model service** (Python, P2) and **PostgreSQL**; with
`docker/compose.chat.yaml` a fifth, **vllm**, serves the chat model. The server, model, vllm and database sit on an
internal network with no route out.

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
and 18443). To serve an open-weight chat model add `docker/compose.chat.yaml` (T282). It adds a fifth container,
**vllm** (`vllm/vllm-openai:v0.34.0`), which holds the weights in BF16 on the NVIDIA GPU, offline, with the hub cache
mounted read-only at `/weights` and on the internal network only. The model service stays the light image and forwards
chat to it (`ServedChat`: the server renders the chat template, the model service fits the prompt to the input budget
and splits reasoning and tool calls). `docker/laris.sh up` sets everything; by hand, with a separate project name so it
keeps its own volumes and certificate authority:

```sh
export LARIS_MODELS_DIR=$HOME/.cache/huggingface/hub LARIS_CHAT_SNAPSHOT=<snapshot folder of models--Qwen--Qwen3.5-4B>
export LARIS_GPU_MEMORY_BYTES=$(( $(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits -i 0) * 1048576 ))
export LARIS_HTTP_PORT=38080 LARIS_HTTPS_PORT=38443 LARIS_DOMAIN=localhost
export LARIS_EDGE_SUBNET=172.31.61.0/24 LARIS_EDGE_GATEWAY=172.31.61.1 LARIS_SUBNET=172.31.60.0/24
docker compose -p laris-qwen -f docker/compose.yaml -f docker/compose.chat.yaml up -d --build --wait --wait-timeout 900
```

The whole hub cache is mounted because a model's blobs can live in a store shared with other models; the snapshot pins
the revision. The vllm container takes two to four minutes to load and compile before it is healthy; the model service
and the server wait for it. Its settings are environment variables with defaults in `docker/compose.chat.yaml`:

| Variable | Default | Meaning |
|---|---|---|
| `LARIS_ENGINE_GPU_SHARE` | 0.85 | share of GPU memory vLLM reserves; the model service's GPU queue counts the same share of `LARIS_GPU_MEMORY_BYTES` and refuses to start if it exceeds `vram_budget_bytes` |
| `LARIS_ENGINE_MAX_MODEL_LEN` | 20480 | context of one request; the prompt budget is capped at this minus `LARIS_CHAT_MAX_NEW_TOKENS` |
| `LARIS_ENGINE_MAX_SEQS` | 64 | requests vLLM batches at once (the default 256 exceeds the state blocks of the linear-attention layers) |
| `LARIS_CHAT_CONCURRENCY` | 8 | chats the model service sends to vLLM at the same time |

The GPU is the server's for as long as vllm runs: another GPU program (for example CARLA) must be closed first, and
`docker/laris.sh down` frees it. The model is NOT QUALIFIED.

**STEM evaluation on the same server.** `LARIS_ENGINE_PORT=38100 docker/laris.sh up` (or `-f
docker/compose.engine-port.yaml` by hand) also binds vLLM to `127.0.0.1:38100` through a network that does not
masquerade, so the server still has no route out. `scripts/stem_benchmarks.py baseline` then sends its requests there
(`configs/stem-benchmarks.json`, `engine.base_url`) and records in its summary what the server serves. Chat and
evaluation use one engine and one precision; a benchmark run shares the GPU with chat, so cost and latency figures
are only comparable under the same load.

## Smoke test

```sh
docker/smoke_test.sh
```

It builds and starts a separate project (`laris-smoke`, ports 28080/28443, its own volumes), checks that only Caddy
publishes ports, health through Caddy, the first admin key, a user key, one chat answer, the account, a trace
without message text, and the policy lock; then removes the smoke project. Since T243 it also checks the pipeline: a
refusal is answered by the Prefilter without the model, the main brain is seeded through the write gate, a covered
question is answered from the brain with a server evidence entry and no model stage, a free question reaches the model,
and with grounding `required` (the script restarts the server with it) an uncovered question abstains. The placeholder
backend shows mechanics only. The cognitive evaluation through the server is `scripts/server_eval.py` (it seeds the
brain with `configs/cognitive-eval.json`, asks its questions through `/v1/laris/chat` and writes a report under
`reports/server/`). A running server of the project `laris` is not touched.

## Upgrading the trial server

The compose file keeps the trial server's volumes: `laris_caddy_data`, `laris_caddy_config` and `laris_pgdata`
(project name `laris`, volumes `caddy_data`, `caddy_config`, `pgdata`). Clients that pinned Caddy's authority keep
working because `caddy_data` survives.

1. Back up first: `docker/backup.sh --with-secrets /safe/place`.
2. Stop the old stack **without** `-v`: `docker compose -f docker/compose.yaml stop` (never `down -v`, never remove
   `caddy_data`).
3. Start the new stack with the same `LARIS_DOMAIN`, `LARIS_HTTP_PORT` and `LARIS_HTTPS_PORT` as before.
4. The server uses the PostgreSQL schema `laris2`; create keys with the admin key (section Keys).
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

## Request pipeline (ADR-025)

Since T243 the compose stack runs the whole pipeline: Prefilter on, grounding `optional`, the rule decider on, the
composer answering without the model when the brain covers the question, and the main brain in `/state/brain` (the
state volume). Each setting below is a `LARIS_SERVER__*` variable of the `server` service, and compose fills it from a
`LARIS_*` variable (for example `LARIS_PIPELINE_GROUNDING`, `LARIS_DECIDER_MIN_COVERAGE`, `LARIS_BRAIN_MIN_SUPPORT`)
that you can set in `docker/laris.env`. The gate and decider thresholds are starting values that nothing has tuned.
`LARIS_PIPELINE_PREFILTER=false`, `LARIS_PIPELINE_GROUNDING=off` and `LARIS_DECIDER_ENABLED=false` give the plain
policy gateway again (the rollback). With `optional`, a question the brain does not cover goes to the model as a free
answer; with `required` it abstains (`R6-abstain`).

| Variable | Meaning |
| :--- | :--- |
| `LARIS_SERVER__PIPELINE_PREFILTER` | `true` runs the Prefilter rules (`.laris/prefilter.toml`) on the latest user message; a hit is the answer and the model is not called |
| `LARIS_SERVER__PIPELINE_GROUNDING` | `off`, `optional` (answer from passages when there are some, else a free answer) or `required` (no passages, no answer) |
| `LARIS_SERVER__PIPELINE_MAX_EVIDENCE_CHARS` | most characters of main-brain passages one answer may carry (6144) |
| `LARIS_SERVER__PIPELINE_MAX_DRAFT_CHARS` | largest buffered draft (65536); a longer one is an error, not a truncation |
| `LARIS_SERVER__PIPELINE_STAGE_TIMEOUT_MS` | longest one model call inside the pipeline (120000) |

Grounding reads the **main brain**, one shared vault on the server: `LARIS_SERVER__MAIN_BRAIN_DIR` plus the five gate
thresholds `LARIS_SERVER__MAIN_BRAIN_MIN_SUPPORT`, `_MIN_EQUIVALENCE`, `_SUBJECT_OVERLAP` (0 to 1), `_SEARCH_DEPTH` and
`_MAX_BYTES`, which have no defaults. Only the write gate writes it, through admin routes that need `brain.manage`:
`POST /v1/admin/brain/sources` (title, kind, identifier, text, metadata), `POST /v1/admin/brain/claims` (statement,
source, quote, requested level, evidence) and `POST /v1/admin/brain/retract` (title, reason). A caller needs `brain.read`
(default on for `user`) to have an answer grounded in it. No route returns a note.

The **decider** (stage 5, the rule decider of `laris-brain`) is off unless `LARIS_SERVER__DECIDER_ENABLED=true`; then every
value is required, none has a default: `_REQUIRED_LEVEL` and `_ANSWER_MIN_LEVEL` (`sourced`, `corroborated`, `verified`,
`reviewed`), `_MIN_COVERAGE` and `_ANSWER_MIN_COVER` (0 to 1), `_MAX_RETRIEVALS`, `_MAX_ADVISOR_ASKS`, `_MAX_REPEATS`,
`_ANSWER_MAX_NOTES`, `_MAX_STEPS` and `_MAX_SECONDS` (the caps the client's loop counters are clamped to).
`LARIS_SERVER__PIPELINE_COMPOSE_WITHOUT_MODEL=true` lets the composer answer from accepted Claims without calling the model
when the decider chooses `answer`. The decision network cannot be enabled (it is not promoted); setting
`LARIS_SERVER__DECIDER_NETWORK` stops the server. Each decision is a step with the code `action:rule`. A stop and a question to the user end the turn with `decider_stop` and `decider_ask_user` of `.laris/harness.toml`.

Attempts, passages and the abstention texts are the owner's policy in `.laris/harness.toml`. Each stage and its time
are in the trace row (`stages`, `GET /v1/admin/traces`), never the message. The database needs migration 0003, which
the server applies at start.

## Backup and restore

`docker/backup.sh [--with-secrets] [DIR]` writes a `pg_dump` (custom format); `docker/restore.sh DUMP` restores it.
The dump alone cannot reveal stored keys: keep `docker/secrets/master.secret` in a different place.

## Logs and health

`docker compose -f docker/compose.yaml ps` shows health; `logs -f server`. Caddy removes `Authorization` from its
logs; the server's traces hold no message text.
