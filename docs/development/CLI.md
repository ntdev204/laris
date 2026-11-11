---
document_id: "DOC-DEV-CLI-001"
title: "LARIS Command-Line Interface Reference"
document_type: "specification"
status: "APPROVED"
version: "1.1.0"
created_at: "2026-10-29"
updated_at: "2026-11-10"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/specifications/LANGUAGE_ENCODER_TRAINING_SPECIFICATION.md"
  - "docs/specifications/DATASET_SPECIFICATION.md"
  - "docs/adr/ADR-013-functional-package-layout-and-cli.md"
decision_references:
  - "ADR-013"
change_summary: "Adds offline formal readiness, links the owner-only runbook and documents citation-ID verification versus source-backed extractive certification."
---

# LARIS Command-Line Interface Reference

The `laris` entry point (`src/cli/main.py`) exposes one module per command under `src/cli/commands/`. Each module defines `add_arguments(parser)` and `run(args)`. Scripts under `scripts/` are thin wrappers over the same functions. Run `laris <group> <command> --help` for the full option list.

## Commands

| Command | Purpose | Authorization |
| :--- | :--- | :--- |
| `laris data acquire [--only IDS] [--cc100-max-docs N]` | Download and verify datasets; `--only` merges into the existing manifest. Resumable. | none |
| `laris data check [--verify-sha256]` | Verify manifest files, per-task train/val/test coverage and `sentencepiece` before any training step. Exit 0 ready, 1 not ready. | none |
| `laris data partition [--datasets ...] [--num-workers N] [--include-unreviewed-licenses]` | Leakage-safe train/val/test partitioning. Datasets with `NEEDS_LICENSE_REVIEW` are skipped by default. A subset run merges into the existing manifest by `dataset_id`. | none |
| `laris train tokenizer [--extract-only] [--authorized]` | Extract train-only text and fit the SentencePiece 32k BPE tokenizer. | `--authorized` |
| `laris train language-encoder --model-size {compact,large} [--profile-only] --tokenizer-model FILE` | `--profile-only` measures real GPU memory on real tokenized train batches (forward only; with training authorized, backward plus a real optimizer step on a discarded model). Otherwise trains, validates, checkpoints and evaluates the encoder. | training needs `--authorized` and `LARIS_TRAINING_AUTHORIZED=1` |
| `laris evaluate language-encoder --checkpoint DIR --tokenizer-model FILE [--split val\|test]` | Score a checkpoint against baselines and thresholds. Exit codes: 0 passed, 1 below threshold, 2 usage or integrity error. | none |
| `laris evaluate readiness --reports REPORT...` | Offline formal foundation audit; requires matching test evidence and protocols. No model loaded. Exit 0 qualified, 1 not qualified, 2 invalid input. | none |
| `laris evaluate calibrate --reports VAL_REPORT...` | Ratchet `configs/evaluation/language_encoder.yaml` up from passing `val` reports; never lowers, refuses `test` reports. | none |
| `laris infer {nli,...} --checkpoint DIR --tokenizer-model FILE` | Run a single prediction from a checkpoint. | none |

## Owner training and evaluation

The [owner runbook](../training/OWNER_RUNBOOK.md) is the execution reference.
Agents must not execute training, tokenizer fitting, backward/optimizer steps or
optimizer-bearing profiling/tests under the current instruction. `--profile-only`
can run real optimizer steps when `LARIS_TRAINING_AUTHORIZED=1`; its name alone
is not a no-training guarantee.

Baseline-relative `evaluate language-encoder` results do not qualify model 01.
`evaluate readiness` reads existing report files against
`configs/evaluation/foundation.yaml` without running a model. Missing official
metrics, incompatible QA protocols, mixed artifact identities or validation-only
reports block qualification. Model 02 remains unimplemented and must follow the
foundation exit gate.

Training progress and checkpoints remain under
`artifacts/checkpoints/language_encoder/<run-id>/{best,last}`. Resuming requires
matching recorded settings and does not restore the exact streaming data position.

## Report verification scope

`EvidenceGate` checks registered assertion citation IDs only. Its `verification_scope`
metadata is `citation_ids_only`; a passing coverage ratio is not evidence of source
integrity or entailment.

For source-backed extractive reports, use `SourceEvidenceGate(source_documents)`
with `StructuredReportGenerator(evidence_gate=gate)`. Supply canonical UTF-8 source
texts keyed by document ID, and corpus hashes computed from those texts. Every
assertion must equal its cited excerpt; each section's Markdown must equal its
assertion statements joined by blank lines. Empty sections are allowed, but reports
without assertions are rejected. Sources, hashes, coordinate IDs and character spans
are checked. Synthesis and paraphrases remain uncertified: this gate does not infer
semantic support or establish research-gap novelty.

## Local application (`laris app`)

An end-to-end local workflow that needs no extra dependency and never trains or fits.

```bash
laris app ingest path/to/docs data/raw/scifact/corpus__corpus-00000-of-00001.parquet
laris app search --query "..."            # BM25, works without a model
laris app index  --checkpoint <run>/best --tokenizer-model <model>   # dense embeddings
laris app ask    --checkpoint <run>/best --tokenizer-model <model> --query "..."
```

Accepted inputs are txt, md, pdf (needs `pypdf`), and BEIR corpus `.jsonl` or `.parquet`. The
workspace (`artifacts/app/workspace` by default) holds `chunks.jsonl` and, after `index`,
`embeddings.npy`; adding a document invalidates the dense index. Until the foundation model is
qualified, BM25 is the reliable channel and extractive answers are quoted from passages without
entailment checks.

### Chat, agent and model API

Two executables: `laris` is the user client (agent, account, vault, skills, learn, and `app ingest|search|status`)
and `laris-server` holds the operator side (`model serve`, `harness`, `brain`, `workflows`, data, training,
evaluation, `app index|ask`); the client does not contain server commands.

The web interface was removed (owner decision, 2026-11-11); LARIS is a terminal client. Two parts:

```bash
LARIS_SERVER_KEYS="key1,key2" laris model serve --port 8000   # operator: authenticated model API
laris login                       # user: enter the API key once (hidden input, saved with mode 0600)
laris                             # terminal chat; also -p "prompt", --resume, --resume <id>
```

Run `laris-server model serve` in the codebase that holds the system `.laris/` (or pass `--policy-root`);
the operator does not log in. HTTPS: `laris-server tls init --host name-or-ip` writes a self-signed
certificate and a 0600 key to `serving.tls_dir` (`~/.laris-server/tls`); `model serve` then uses them
automatically. Or give a certificate and its private key
(`--tls-cert cert.pem --tls-identity identity.pem`, or `serving.tls_cert_file` and
`serving.tls_identity_file`; TLS 1.2 or newer). The server refuses plain HTTP on any address except
loopback unless `serving.allow_plain_http` is set (for example behind a reverse proxy that terminates TLS).
Certificates are always verified. For a private or self-signed certificate `laris login --server URL`
shows its SHA-256 fingerprint and, once the user confirms it (or passes `--trust-fingerprint`), pins it in
`~/.laris/trusted/` and `settings.json` (`ca_file`) for that server only; `SSL_CERT_FILE` still works. The server address is the `base_url` field of the global `~/.laris/settings.json`, as in
`{"base_url": "https://host:8000/v1", "model": "laris-core", "api_key": "lk_..."}` (as Claude Code does);
`laris login --server URL` and `laris login` write `base_url` and `api_key` there (file mode 0600; `api_key`
can also come from `LARIS_API_KEY`; `credentials.json` of older installs is still read).

Keys are made on the server machine and stored in its database (`serving.data_dir`):

```bash
laris-server keys create --label "Alice" --role user --tokens 2000000     # a quota
laris-server keys create --label "Owner" --role admin --tokens unlimited  # no quota
laris-server keys list | show ID | revoke ID | limit ID --tokens N [--add] | roles
laris-server usage summary                                                # token use per key
laris-server reasoning list | show ID | purge                             # the model's reasoning
```

The new key is printed once and the running server accepts it at once. Keys are stored encrypted
(master secret: `LARIS_SERVER_MASTER`, or the file `serving.master_file`, kept apart from the database);
`laris-server keys reveal ID` prints one again. The first start creates a built-in key with every
permission and no limit that works only from the server machine itself (`laris-server keys reveal
default`); restrict any key to addresses with `--allow-ip CIDR` or `keys ip ID --allow CIDR`. Roles (`serving.roles`): `user`,
`readonly`, `auditor`, `admin`; a request without the route's permission gets 403 and a key without tokens
left gets 429. The model's reasoning is stored for the operator only and is never sent to any client
(ADR-018); `laris whoami` shows a user's role and tokens left. Fixed keys in `LARIS_SERVER_KEYS` still work
for testing (role `user`, unlimited).

The server refuses to start without keys (`serving.api_key_env`, `serving.allowed_file`; digests only in
memory), answers 401 to any other key, and stores nothing about users (ADR-015: the user's disk is the
database and the user's machine is the sandbox). `laris login` and each session check the key against
the server (`model_api.base_url`; remote hosts need `model_api.allow_remote: true`).

Preferences (`settings.json`) are global and shared by every key on the machine, in `~/.laris/`
(`app.settings_file`); `~/.laris/` also holds `config.yaml`, `LARIS.md`, `skills/` and `memory/`, created
on first start. The project's `./.laris/` (`laris init`) holds the same kinds of files for one project.

Each API key opens its own private space: conversations, uploads, archive, audit and
collected sessions live under `artifacts/chat/users/<fingerprint>/` (`app.users_dir`), where the
fingerprint is a one-way hash of the key. The key itself is read from `LARIS_API_KEY`
(`app.key_env`), else the credentials file (`app.account_file`), else a hidden prompt, and is sent to the
model API as the bearer token; keys typed into a message are masked before storage. The terminal
streams text, prints each tool call with a one-line result, asks before write tools
(`y`/`a`lways/`N`) and has `/new /sessions /resume /tools /status /model /write`. `laris --resume`
lists the saved sessions of the signed-in key.

Nothing here is hardcoded: ports, workspace, model API, limits, approval policy, prompts and
security patterns come from `configs/default.yaml`, `~/.laris/config.yaml`,
`<project>/.laris/config.yaml`, saved preferences, `LARIS_*` environment variables (nesting with
`__`, JSON for lists; see `.env.example`) and finally the flags, in that order. Credentials are
referenced by environment-variable name only. The prompt, loop, guards and leak policy are described
in `docs/architecture/AGENT_HARNESS.md`; `LARIS.md` is internal policy and is never shown to users.

Tools (JSON-schema arguments, 30 s default timeout, typed errors): `list_files`, `read_file` (txt, md,
pdf, images; scans use tesseract `eng+vie`), `write_file` and `ingest_path` (need approval; writes land
only in `artifacts/chat/output`), `search_corpus`, `answer_question`, `extract_discourse`,
`corpus_status`. Reads are limited to the working folder and uploads. A message stops after 10 steps,
on an identical repeated call, or after the time budget; every session is logged as JSONL.

The client runs the tools and the **model server decides**: it receives `messages` and `tools` at
`POST /v1/chat/completions` (JSON or `stream: true` SSE) and answers with text or `tool_calls`;
`GET /v1/models`, `GET /health` and `POST /v1/embeddings` are also served. Today the backend is a
scripted placeholder that quotes passages (`laris-placeholder`). The trained core model plugs in as a
`ChatProvider` subclass: `laris model serve --backend package.module:ClassName --model-name laris-core`,
with no client change. Set the server's key variable with `--api-key-env`; clients send their own
key as the bearer token. Keys never appear in configuration files.

#### User guide (`/how-to-use`)

`/how-to-use` prints `.laris/help/how-to-use.md` exactly as written (`prompts.help_file`,
`prompts.help_commands`), with no model call. It works in the terminal chat and as `laris agent guide`. Edit the file, then run `laris harness lock` after the
owner approves the change.

#### Policy folder, workflows and integrity

`.laris/` holds the protected prompts, rules and workflows (see `.laris/README.md`).
`laris workflows list|show|check` inspects workflows, run one in chat with `/workflow <name> <request>`;
`laris harness verify` checks the integrity lock, prompts and workflows and `laris harness lock`
refreshes the lock after an owner-approved change. A tampered policy stops every session.

#### Learning: knowledge by domain, skills on request and fine-tune data

Ingesting documents adds knowledge notes by domain under `vault/Knowledge/<domain hub>/`, shown next to
the matching brain hub (`save_knowledge` adds taught knowledge). Skills are made only on request:
`laris skills lint|add` checks and installs a hand-written one, the agent saves one with `save_skill`
after approval, and `laris skills sync` (or `learning.skill_on_ingest: true`) builds optional corpus skills. Good answers are kept locally under `artifacts/finetune`
(`laris learn stats|export|purge`, `/rate up|down`, `/learn on|off`); the system never trains.

#### The project vault and scholarly analytics

`laris vault init|status|check|search|show|graph|sync|repair|migrate-memory|propose|review|accept|reject`
(see `docs/architecture/BRAIN_AND_VAULT.md`). `check` runs format, schema (`.laris/vault/schema.yaml`),
secret, oversize and alias lint; `graph --format json|graphml|canvas [--out FILE]` exports the link graph
or the knowledge graph; `sync [--accept]` lists or adopts hand edits inside managed blocks; `repair
[--restore NOTE]` fixes damage or restores a backup. In chat: `/vault [words]`. Agent tools:
`search_vault`, `corpus_overview`, `term_trends`, `find_duplicates`, `group_documents`, `save_analysis`,
`citation_graph`, `kg_query`; workflows `literature-map`, `citation-analysis`, `kg-explore`.

Operator side: `laris-server evaluate suite [--fast] [--only ...] [--out reports/...]` runs the model-free
suites (retrieval, citation, extraction, leak, injection, vault round-trip); `make eval-fast`,
`make test-model-free` and `make bench-vault` are the matching targets. See
`docs/development/OWNER_RUNBOOK.md`.

#### Instructions, skills and automatic context compaction

- **`LARIS.md`** (project root) is the internal policy: read at the start of every turn and put in the
  system prompt as confidential, after the optional user-level `~/.laris/LARIS.md` and before
  `.laris/LARIS.md` and the git-ignored `LARIS.local.md` (`prompts.instruction_files`). Edits apply on
  the next message; the files cannot be read through the agent's tools.
- **Skills** live in `.laris/skills/<name>/SKILL.md` (YAML `name` and `description`, Markdown body,
  optional `references/`). Only name and description are in the prompt; the model loads a skill with the
  `use_skill` tool, or the user runs `/<skill-name> request` (terminal and web `/` menu). `laris skills
  list|show|check` inspects and validates them. Project skills override `~/.laris/skills`.
- **Memory** lives in the project vault, `vault/Memory/` (`save_memory` writes it after approval); files in
  the older `.laris/memory/` are still read until `laris vault migrate-memory` copies them (`--undo` removes
  the copies).
- **Autocompact is on by default** (`auto_compact`, `context_window` 32768 tokens, `compact_threshold`
  0.8, all in settings). Before each model call the session estimates its size; above the threshold it
  trims old tool outputs, then replaces older turns with a summary (model-written when a model API is
  connected, otherwise extracted) while keeping recent turns and every tool-call/result pair intact. A
  context-length error from the model triggers one forced compaction and a retry. The original messages
  are archived in `artifacts/chat/archive/`. `/compact [note]` compacts now; `/context` shows usage.
