---
document_id: "DOC-DEV-CLI-001"
title: "LARIS Command-Line Interface Reference"
document_type: "specification"
status: "APPROVED"
version: "2.0.0"
created_at: "2026-10-29"
updated_at: "2026-11-13"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/specifications/LANGUAGE_ENCODER_TRAINING_SPECIFICATION.md"
  - "docs/specifications/DATASET_SPECIFICATION.md"
  - "docs/adr/ADR-013-functional-package-layout-and-cli.md"
  - "docs/adr/ADR-019-three-blocks-two-protocols-two-sql-engines.md"
  - "docs/development/SERVER_DEPLOYMENT_RUNBOOK.md"
  - "docs/development/MIGRATION_1X_TO_2_0.md"
  - "docs/architecture/AGENT_HARNESS.md"
decision_references:
  - "ADR-013"
  - "ADR-019"
change_summary: "Release 2.0: three executables (laris, laris-server, laris-model); the terminal client in its three modes (Ink, plain, headless), the engine protocol E1, the settings schema, slash commands, permissions, hooks and the sandbox; the owner-side data, training and evaluation commands move to laris-server."
---

# LARIS Command-Line Interface Reference

Release 2.0 ships three executables ([ADR-019](../adr/ADR-019-three-blocks-two-protocols-two-sql-engines.md)).
The foundation model is **not qualified**: nothing in this reference says an answer is correct, only how the
tools behave. Run `laris <group> <command> --help` for the full option list of any command.

| Executable | For | Entry point | Contains |
| :--- | :--- | :--- | :--- |
| `laris` | the user | `src/cli/client.py` | chat (three modes), `login`, `config`, `skills`, `learn`, `vault`, `app ingest\|index\|search\|status`, `agent`, `engine`; no server, policy or training command |
| `laris-server` | the operator and owner | `src/cli/server.py` | `model serve`, `keys`, `usage`, `reasoning`, `tls`, `db`, `harness`, `workflows`, `brain`, `data`, `train`, `evaluate` |
| `laris-model` | the model container | `src/cli/model.py` | `serve` (protocol P2), `infer` (one prediction from a checkpoint) |

Each command is a module under `src/cli/commands/` with `add_arguments(parser)` and `run(args)`. Scripts under
`scripts/` are thin wrappers over the same functions.

## 1. The terminal client (`laris`)

### 1.1 Three ways to run

| Mode | Command | Use it for |
| :--- | :--- | :--- |
| Interactive (Ink and React front end) | `laris` | daily work; needs Node 22 or newer |
| Plain text | `laris --plain` | simple terminals, screen recordings, no Node |
| Headless | `laris -p "prompt"` | scripts: one task, then exit |

All three drive **one engine** (`laris engine --stdio`), so the same session gives the same tool calls,
tool results and answer in each. The Ink front end is started by the npm launcher (`bin/laris.js`), which
hands the arguments straight to the engine program when there is no terminal, `--plain`, `-p`, `--help`,
`--version`, a subcommand, `LARIS_UI=plain`, or an option only plain mode has. If the interface cannot load, the launcher says so and starts `--plain`. The
launcher finds the engine through `LARIS_ENGINE_BIN`, then the per-platform npm package, then `dist/`.

Session options (all modes unless noted):

| Option | Meaning |
| :--- | :--- |
| `-p`, `--print [TEXT]` | headless; the text may come from standard input |
| `--output-format text\|json\|stream-json` | with `-p`; `stream-json` writes E1 events, one JSON object per line |
| `--plain` | plain-text mode |
| `-c`, `--continue [ID]` | continue the newest session, or the one named by id or unique prefix |
| `--resume [ID]` | open the session `ID`; without an id, choose from a list |
| `--max-turns N` | with `-p`: agent steps, 1 to 10 |
| `--permission-mode default\|acceptEdits\|plan\|bypass` | for this run (`bypass` only when the policy allows it) |
| `--allowed-tools RULES`, `--disallowed-tools RULES` | permission rules for this run, e.g. `'Read,Bash(git status:*)'` |
| `--workspace`, `--chat-dir`, `--model-api-url`, `--model-name`, `--api-key-env`, `--allow-write` | overrides of configuration |
| `--version`, `-V` | print the version |

Sessions are per project, in SQLite files under `~/.laris/projects/<slug>/`; an id is looked up in the
current project only.

**Headless exit codes:** `0` completed; `1` not completed (model or tool error); `2` bad usage or
configuration (flag, unknown session, mode not allowed); `3` stopped because a required action was not
allowed; `130` interrupted (the session is saved). With no one to answer, an action that needs approval and
has no allow rule is refused and listed in `permission_denials`; the turn still completes (exit 0). `json`
prints one result object; `text` prints only the answer.

**Interactive keys (Ink).** Enter sends. Backslash then Enter, Shift+Enter or Meta+Enter starts a new line
(backslash then Enter works everywhere). Up and Down browse history (inside a multi-line text they move the
cursor first); Ctrl+R searches history; Tab takes the completion the engine sent for `/command` or `@path`.
Esc interrupts the running turn (it first closes a menu or search). Ctrl+C clears typed text, otherwise
interrupts, and a second Ctrl+C within 2 seconds exits; Ctrl+D on an empty line exits. Shift+Tab cycles the
permission mode. Typing while a turn runs queues the message (`⧗ queued:`); it starts after the turn. A paste
over 6 lines or 1000 characters shows as `[Pasted text #n +L lines]` and is sent in full. At an approval
dialog (it shows the diff of a `Write` or `Edit`): `y` once, `a` for this session, `p` for this project, `e`
everywhere, `n` or Esc refuses; the number keys or arrows and Enter also work. Prompt history lives only in
memory for the session. Plain mode offers the same slash commands and the question `y / a / p / e / N`.

### 1.2 Account, server and settings

```bash
laris                             # opens the interface; the first run asks for the API key there
```

Nothing has to be configured first (ADR-019 D24, D25). The **server address** comes from, in order: the
`LARIS_MODEL_API__BASE_URL` environment variable, `server.url` in `~/.laris/settings.json`, and the default
written into the package at build time (`defaults.json` beside the program; see the deployment runbook). When
something is missing the engine says so before the session starts (E1 event `login_required`) and the interface
asks: the API key (hidden; checked against the server before it is saved to `~/.laris/.credentials.json`,
mode 0600; a refused key is asked again), a server address when the build has no default (a bare host name
becomes `https://HOST/v1`), or a confirmation of a private certificate's SHA-256 fingerprint. A fingerprint
packaged with the program needs no question, and a server that does not match it cannot be accepted.

For a server with a private certificate authority the client pins the **authority** the server publishes at
`/.well-known/laris/ca.crt`, not the server certificate (a reverse proxy renews that one every few hours); it
falls back to the server's own certificate only when no authority is published.

`laris login` is optional: it asks for the key outside the interface and still accepts `--server URL` and
`--trust-fingerprint SHA256:...` (the fingerprint of the authority, or of the certificate).
`laris logout` forgets the key; `laris whoami` shows the role and the tokens left. The key can also come from
`LARIS_API_KEY`. Certificates are always verified. There is no offline mode: the client needs a server.

`laris config get [PATH]`, `laris config set PATH VALUE` and `laris config schema` read, change and describe
`~/.laris/settings.json` (a dotted path such as `permissions.defaultMode`; the value is JSON or plain text).
`/config` does the same inside a session.

**The global home `~/.laris/`** (created on first start, never overwritten):

| Path | Content |
| :--- | :--- |
| `settings.json` | every client setting, no secrets, validated by the shipped schema |
| `.credentials.json` | the API key, mode 0600 |
| `.venv/`, `python/` | the sandbox and its interpreters, built by `uv` |
| `LARIS.md`, `skills/`, `commands/`, `memory/` | personal instruction layers, skills, slash commands and memory |
| `projects/<slug>/` | per-project SQLite space, `state.json` (saved permission answers, trust) and checkpoints |
| `trusted/` | pinned server certificates |
| `logs/` | local audit (event type, tool name, status, sizes and hashes; never message content) |
| `backups/` | what the 1.x migration replaced |

A project's `./.laris/` carries **no configuration**: `config.yaml`, `settings.json`, `settings.local.json`
and a `.env` setting `LARIS_*` are ignored on the client and named in a warning, so a cloned repository cannot
change permissions, hooks, the server address or the model. `laris init` creates the project's
`.laris/` folder for instructions, skills and commands only.

**Settings schema** (`laris config schema` prints the JSON Schema; unknown keys are rejected):

| Key | Type, default | Meaning |
| :--- | :--- | :--- |
| `server.url` | string, empty | server address (HTTPS, or loopback) |
| `server.caFingerprint` | string, empty | SHA-256 of the pinned certificate |
| `server.timeoutSeconds` | number, 120 | request timeout |
| `model` | string, empty | model name sent to the server |
| `ui.theme`, `ui.markdown`, `ui.spinner`, `ui.showStatusLine` | `auto`, true, true, true | front-end display |
| `permissions.defaultMode` | `default`, `acceptEdits`, `plan`, `bypass` | starting mode |
| `permissions.allow`, `ask`, `deny` | lists of `Tool` or `Tool(pattern)` | permission rules |
| `permissions.additionalDirectories` | list of paths | extra folders the tools may reach |
| `env` | object | environment passed to tools and hooks |
| `hooks` | object: event to a list of `{matcher, hooks: [{type: "command", command, timeout}]}` | see 1.5; timeout default 30 s, at most 600 |
| `statusLine` | `{type: "command", command}` | status line command |
| `sandbox.python`, `packages`, `inheritEnv`, `indexUrl`, `pythonSource` | `3.12`, list, false, empty, empty | the sandbox build |
| `context.autoCompact`, `windowTokens`, `compactThreshold` | true, 32768, 0.8 | automatic compaction |
| `vault.autoRecord` | true | record notes in the project vault after verified turns |
| `learning.collect` | true | keep good turns locally as fine-tune data |
| `extraInstructions` | string | extra user instructions (length-capped, after policy) |
| `cleanupPeriodDays`, `autoUpdates` | 30, true | housekeeping |

Precedence, highest last: schema defaults, `configs/default.yaml`, `settings.json`, `LARIS_*` environment
(`__` separates nesting, JSON for lists; credentials are referenced by variable name only), command-line flags.
See [AGENT_HARNESS](../architecture/AGENT_HARNESS.md) section 2.

### 1.3 Slash commands

`/help` lists them; `/` followed by Tab completes. Built-in commands: `help`, `how-to-use` (the prepared guide,
printed without a model call), `new` or `clear`, `sessions`, `resume ID`, `continue`, `compact [note]`,
`model [URL [NAME]]`, `status`, `cost`, `context`, `config [get PATH | set PATH VALUE]`, `permissions [mode
MODE|next | allow|ask|deny RULE [everywhere]]`, `memory`, `init`, `trust [off]`, `login`, `logout`, `doctor`,
`vault [words]`, `skills`, `workflows`, `workflow NAME REQUEST`, `hooks`, `sandbox [reset]`, `rewind [N|all]`
(restore files changed by `Write` and `Edit`), `tools`, `write on|off`, `learn on|off`, `rate up|down`, `exit`
and `quit`. User commands are Markdown files in `~/.laris/commands/` (`$ARGUMENTS` is replaced by the text after
the command); a project's own commands and skills load only after `/trust`. `/<skill-name> request` runs a skill.
Several commands print the same status values as the status line, so they cannot drift apart.

### 1.4 Tools and permissions

Coding tools (`Read`, `Write`, `Edit`, `Glob`, `Grep`, `Bash`, with diffs and checkpoints) and the research tools
(`search_corpus`, `answer_question`, `extract_discourse`, `corpus_status`, `ingest_path`, `read_file`,
`list_files`, vault and scholarly tools) are shown to the model; `/tools` lists them. Arguments are validated
against a JSON Schema, each call has a timeout and a cap, and results from documents are marked untrusted.
Tools reach only the working folder, `permissions.additionalDirectories` and uploads; policy folders, `.git`,
`.env` and the learning data are denied by glob; planted symlinks, `..`, `~` and `/proc` do not escape.

Permission modes and the order in which rules are decided are in
[AGENT_HARNESS](../architecture/AGENT_HARNESS.md) section 2. In short: `default` asks before writing;
`acceptEdits` lets edits through; `plan` is read-only; `bypass` asks nothing and needs the policy to allow it
(`agent.approval.allow_bypass`). Installing packages outside the sandbox is denied in every mode; installs into
`~/.laris/.venv` are allowed. An `allow` rule written for one command never admits a chained line
(`Bash(git status:*)` does not allow `git status && rm -rf ~`); `deny` and `ask` rules match any part of a line.

### 1.5 Hooks

Declared only in `~/.laris/settings.json`. Events: `SessionStart`, `UserPromptSubmit`, `PreToolUse`,
`PostToolUse`, `Stop`. `matcher` selects tools for the two tool events. A hook runs in the project folder with
the event as JSON on standard input and the sandbox first on `PATH`. Exit 0 with no output continues; exit 2
blocks and standard error is the reason; a JSON object `{"decision": "block", "reason": "..."}` blocks and
`{"additionalContext": "..."}` adds text for the model; any other exit code, a timeout or malformed output is a
warning and the session carries on. A `PreToolUse` hook can only tighten a decision. Output is read with a size
bound and stripped of control characters. `/hooks` lists them.

### 1.6 Status line and sandbox

The status line shows model, mode, context use, tokens left (asked from the server every 30 s at most), git
branch and sandbox state; `statusLine.command` can replace it. The sandbox is built, checked and repaired by `uv`
without action by the user; states are `ready`, `missing`, `broken`, `outdated`, `building` and `failed`
(`/sandbox`, `/sandbox reset`, `/doctor`). A failed build is a message, not a crash. Pinned versions and the
node requirement are recorded in ADR-019.

### 1.7 Engine protocol E1 (`laris engine --stdio`)

The engine writes events and reads commands, one JSON object per line, each with a `type`. The `ready` event
carries `version` (currently `"1"`); a front end that does not know it refuses with a clear message and exit 2.
The schema ships as `src/laris/protocol/e1.schema.json` and is checked against the code by tests.

| Direction | Types |
| :--- | :--- |
| engine to front end (events) | `ready` (version, engine, session, cwd, mode, server), `text` (delta), `tool_call` (id, name, arguments), `tool_result` (id, name, result), `plan` (steps), `permission_request` (id, tool, arguments, reason, rule, diff, scopes), `status` (kind, data: `verify`, `reflect`, `brain`, `learning`, `mode`, `notice`, `line`, `queued`, `sandbox`), `usage` (tokens, window), `compact` (before, after, summarized, method), `goal`, `completion` (id, items), `error` (code, message), `done` (status, answer) |
| front end to engine (commands) | `user_message` (text, attachments of pasted images or long text), `permission_response` (id, decision `allow`\|`deny`, scope `once`\|`session`\|`project`\|`everywhere`), `interrupt`, `command` (name, args), `set_mode` (`default`, `acceptEdits`, `plan`, `bypass`, `next`), `complete` (id, trigger `/` or `@`, text), `shutdown` |

Headless `--output-format stream-json` writes the same events. The `engine` options are `--stdio`, `--resume ID`,
`--continue [ID]`, `--workspace`, `--chat-dir`, `--model-api-url`, `--model-name`, `--api-key-env` and
`--allow-write`. The front end holds no tool, permission or storage logic.

### 1.8 Documents, search and the workspace

```bash
laris app ingest path/to/docs data/raw/scifact/corpus__corpus-00000-of-00001.parquet
laris app search --query "..."     # BM25, works without a model
laris app index                    # embed the passages through the server for dense search
laris app status
```

Accepted inputs are txt, md, pdf (needs `pypdf`) and BEIR corpus `.jsonl` or `.parquet`. The workspace is
SQLite (`chunks`, `embeddings`); adding a document invalidates the dense index. Dense search embeds through the
server (`POST /v1/laris/embed`) and caches the vectors; the client never loads an encoder. Until the foundation
model is qualified, BM25 is the reliable channel and extractive answers are quoted from passages without
entailment checks.

### 1.9 Skills, learning and the project vault

`laris skills list|show|check|lint|add|sync` inspect and install skills (`.laris/skills/<name>/SKILL.md`, YAML
`name` and `description`, Markdown body; project skills override `~/.laris/skills`). Only name and description
are in the prompt; the model loads a skill with `use_skill`. Skills are made on request; `skills sync` builds optional corpus
skills. Good answers are kept locally (`laris learn stats|export --kind K --out FILE|purge --yes`, `/rate`,
`/learn`); the system never trains. Ingesting documents adds knowledge notes by domain under
`vault/Knowledge/<domain hub>/`.

`laris vault init|status|check|search|show|graph|sync|repair|migrate-memory|propose|review|accept|reject` manage
the project vault (see [BRAIN_AND_VAULT](../architecture/BRAIN_AND_VAULT.md)). `check` runs format, schema
(`.laris/vault/schema.yaml`), secret, oversize and alias lint; `graph --format json|graphml|canvas [--out FILE]`
exports the link graph; `sync [--accept]` lists or adopts hand edits inside managed blocks; `repair [--restore
NOTE]` fixes damage or restores a backup.

### 1.10 Instructions and context compaction

- **Instruction layers**, in prompt order: `~/.laris/LARIS.md`, `.laris/LARIS.md` of the project, and the
  git-ignored `LARIS.local.md`. They apply on the next message. The system policy `LARIS.md` of the server is
  confidential and is never shown to users.
- **Autocompact** is on by default (`context.autoCompact`, `windowTokens` 32768, `compactThreshold` 0.8). Above the
  threshold the session trims old tool output, then replaces older turns by a summary (model-written when a
  server answers, otherwise extracted), keeping recent turns and every tool-call and result pair. A
  context-length error triggers one forced compaction and a retry. `/compact [note]` compacts now and
  `/context` shows use. Originals are archived.
- A turn stops after 10 steps, an identical repeated call, or the time budget.

## 2. The operator side (`laris-server`)

Run on the server machine, normally inside the Docker stack ([runbook](SERVER_DEPLOYMENT_RUNBOOK.md)).

| Command | Purpose |
| :--- | :--- |
| `laris-server model serve [--host --port --model-name --backend --tls-cert --tls-identity ...]` | serve the P1 API in one process (the stack runs it as the `api` container) |
| `laris-server keys create --label L --role user\|readonly\|auditor\|admin --tokens N\|unlimited [--allow-ip CIDR --expires-days D --permission P]` | make a key; it is printed once |
| `laris-server keys list\|show ID\|revoke ID\|limit ID --tokens N [--add]\|roles\|reveal ID\|default\|ip ID --allow CIDR` | manage keys; keys are stored encrypted (master secret `LARIS_SERVER_MASTER` or a Docker secret file) |
| `laris-server usage summary` | token use per key |
| `laris-server reasoning list\|show ID\|purge` | the model's reasoning; for the operator only, never sent to a client |
| `laris-server tls init --host NAME` | self-signed certificate for a setup without Caddy |
| `laris-server db migrate` and `db import-sqlite FILE` | create or update the PostgreSQL schema; copy a 1.x server database in one transaction (repeatable) |
| `laris-server harness verify\|lock` | check or refresh `integrity.lock` after an owner-approved policy change |
| `laris-server workflows list\|show\|check` | inspect workflows |
| `laris-server brain check\|tree\|route\|propose\|review\|accept\|reject` | the system brain |
| `laris-server data acquire\|partition\|check`, `train ...`, `evaluate ...` | research tooling, in the next section |

The built-in key (`keys reveal default`) works only from the server machine. Roles are `user`, `readonly`,
`auditor` and `admin`; a request without the route's permission gets 403 and a key without tokens left gets 429.
The server refuses to start without keys, answers 401 to an unknown key, and refuses plain HTTP on any address
except loopback unless `serving.allow_plain_http` is set (behind a proxy that ends TLS).
`laris-model serve [--host --port --model-name --backend --checkpoint --tokenizer-model --device]` runs the
model service (P2).

## 3. Owner research commands (`laris-server data|train|evaluate`)

Documented below as before. They never run in the client and none of them runs without the owner.

### Command table

| Command | Purpose | Authorization |
| :--- | :--- | :--- |
| `laris-server data acquire [--only IDS] [--cc100-max-docs N]` | Download and verify datasets; `--only` merges into the existing manifest. Resumable. | none |
| `laris-server data check [--verify-sha256]` | Verify manifest files, per-task train/val/test coverage and `sentencepiece` before any training step. Exit 0 ready, 1 not ready. | none |
| `laris-server data partition [--datasets ...] [--num-workers N] [--include-unreviewed-licenses]` | Leakage-safe train/val/test partitioning. Datasets with `NEEDS_LICENSE_REVIEW` are skipped by default. A subset run merges into the existing manifest by `dataset_id`. | none |
| `laris-server train tokenizer [--extract-only] [--authorized]` | Extract train-only text and fit the SentencePiece 32k BPE tokenizer. | `--authorized` |
| `laris-server train language-encoder --model-size {compact,large} [--profile-only] --tokenizer-model FILE` | `--profile-only` measures real GPU memory on real tokenized train batches (forward only; with training authorized, backward plus a real optimizer step on a discarded model). Otherwise trains, validates, checkpoints and evaluates the encoder. | training needs `--authorized` and `LARIS_TRAINING_AUTHORIZED=1` |
| `laris-server evaluate language-encoder --checkpoint DIR --tokenizer-model FILE [--split val\|test]` | Score a checkpoint against baselines and thresholds. Exit codes: 0 passed, 1 below threshold, 2 usage or integrity error. | none |
| `laris-server evaluate readiness --reports REPORT...` | Offline formal foundation audit; requires matching test evidence and protocols. No model loaded. Exit 0 qualified, 1 not qualified, 2 invalid input. | none |
| `laris-server evaluate calibrate --reports VAL_REPORT...` | Ratchet `configs/evaluation/language_encoder.yaml` up from passing `val` reports; never lowers, refuses `test` reports. | none |
| `laris-server evaluate suite [--fast] [--only ...] [--out reports/...]` | Model-free suites (retrieval, citation, extraction, leak, injection, vault round-trip); also `make eval-fast`, `make test-model-free`, `make bench-vault`. | none |
| `laris-model infer {nli,...} --checkpoint DIR --tokenizer-model FILE` | Run a single prediction from a checkpoint. | none |

### Owner training and evaluation

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

### Report verification scope

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
