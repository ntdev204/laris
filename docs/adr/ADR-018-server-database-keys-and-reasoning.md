---
document_id: "DOC-ADR-018"
title: "ADR-018: Server Database, Managed API Keys and Private Reasoning"
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
  - "docs/adr/ADR-016-policy-server-and-thin-client.md"
decision_references:
  - "ADR-015"
  - "ADR-016"
change_summary: "The server gains a database (keys with roles, permissions and token quotas; usage; reasoning traces) and a cache. The model's reasoning is stored for the operator and never sent to a client."
---

# ADR-018: Server Database, Managed API Keys and Private Reasoning

## Metadata
- **ADR ID:** ADR-018
- **Status:** ACCEPTED (owner instruction, 2026-11-11)
- **Amends:** ADR-015 items 3 and 4 and its consequence "the server stores nothing". User documents, vault,
  skills, memory and conversations still never reach the server's disk.

## 1. Decision

1. **Database.** `src/serverdata/` keeps one SQLite file (`serving.data_dir`, default `artifacts/server`,
   directory 0700, file 0600, WAL, versioned migrations; standard library only). Tables: `keys`, `usage`,
   `traces`.
2. **Keys.** `laris-server keys create --label NAME --role ROLE --tokens N|unlimited
   [--expires-days D] [--permission P]` makes `lk_<id>_<secret>`, shown once; only its SHA-256 digest is
   stored. The running server reads the database, so a new key works at once (no restart); `revoke`
   applies within `serving.cache_ttl_s`. Other commands: `list`, `show`, `limit` (set, add, unlimited),
   `roles`. Fixed test keys (`LARIS_SERVER_KEYS`) still work as role `user`, unlimited.
3. **Roles and permissions.** Roles map to permissions in configuration (`serving.roles`): `user` (chat,
   embed, models, workflows, help, account), `readonly`, `auditor` (usage and reasoning), `admin`. A key may
   carry extra permissions; `usage.read`, `reasoning.read` and `keys.manage` can only go to privileged
   roles. Every route checks its permission: 401 unknown key, 403 missing permission, 429 no tokens left.
4. **Token quota.** Every request is metered (prompt plus completion, estimated at
   `serving.chars_per_token` unless the backend reports tokens; reasoning tokens count). The check runs
   before the call, the count after, in `finally`, so a disconnect is still billed. A reply ends with a
   `usage` chunk; `GET /v1/laris/account` and `laris whoami` show role and tokens left (`null` =
   unlimited). One request may overshoot the quota slightly.
5. **Cache.** `TTLCache` (LRU, thread-safe) holds key lookups for `serving.cache_ttl_s`.
6. **Private reasoning.** The model's reasoning (a `reasoning` event or `<think>...</think>` inline,
   `serving.reasoning_tags`) is diverted by the gateway, secret-redacted and stored in `traces` with the
   task, tool calls and brain notes. No chat route ever returns it, to any key, admin included. The client
   loop also drops `reasoning` events it might receive from another backend. The operator reads it on the
   server machine: `laris-server reasoning list|show|purge`. An HTTP view (`/v1/admin/reasoning`) exists
   only for `reasoning.read` keys and only when `serving.reasoning_http` is true (default false).
   `trace_retention_days` bounds how long traces live (purged at server start and by `purge`).
7. **Ports.** `serving` stays free of storage: it defines `Principal`, `Authenticator`, `UsageMeter`,
   `TraceSink` (`serving/ports.py`); `serverdata` implements them and `laris model serve` wires them.

8. **Encrypted key storage (amendment, same day).** Each key is also stored encrypted
   (`serverdata/crypto.py`: AES-256-GCM from `cryptography` (owner-approved 2026-11-11, `server`
   extra), random nonce per message, HKDF sub-keys; blobs of the earlier stdlib encrypt-then-MAC
   version stay readable and are resealed with AES-GCM at the key's next use) and its lookup digest is a
   keyed HMAC. The master secret comes from `LARIS_SERVER_MASTER` or a 0600 file
   (`serving.master_file`, default `~/.laris-server/master.secret`, created on first start and kept
   outside the database folder); a database file alone decrypts nothing. `laris-server keys reveal
   ID|default` prints a key. Keys made before this change are upgraded the first time they are used.
9. **Built-in key and address rules.** On first start the server creates one key: role `admin`, every
   permission, no token limit, restricted to `@server`, meaning loopback plus the addresses the machine
   owns (host name, default-route source, `serving.server_ips`, a specific bind address), found
   automatically and refreshed each minute. Any key may carry address rules (`--allow-ip CIDR|@server`,
   `keys ip`). The check uses the TCP peer address on every request; a key used from a forbidden address
   looks like an unknown key (401). The server no longer refuses to start for lack of keys, because the
   built-in key always exists.

## 2. Consequences

- The server now holds personal data: task text and tool calls inside reasoning traces. Users must be told
  that reasoning traces are stored on the server; the user guide (a locked policy file) needs the owner's
  approval to say so.
- A client cannot harvest the model's reasoning from replies. It still sees answers and tool-call
  arguments, which it needs to work; nothing prevents a user from distilling answers.
- The prompt, brain brief and tool schemas count as prompt tokens, so a request costs several thousand
  tokens before the user's text.
- The cipher is built from standard-library primitives, not a vetted AEAD library. Adding `cryptography`
  (AES-GCM) needs the owner's approval and touches one file.
- Behind a reverse proxy on the same machine every request arrives from loopback, so `@server` no longer
  tells callers apart; use TLS directly on the server, or add network rules at the proxy.
- Anyone who can read both the database and the master secret can read every key; protect both.
- A revoked key may work for up to `cache_ttl_s` seconds (default 5).
- Not done: key rotation helper, per-role rate limits, backup of the database, an admin web interface.

## 3. Validation

`tests/unit/serverdata/test_keys_quota_reasoning.py`: key lifecycle and immediate acceptance, digest-only
storage, quota 429 and unlimited keys, roles and 403, reasoning absent from every chat body and present in the
database, admin view off by default, redaction, tag splitting across chunks, cache, CLI.
