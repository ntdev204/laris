# LARIS Changelog

All notable changes to the LARIS project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Documentation of the restructured system (T84):** `SYSTEM_OVERVIEW` (blocks, protocols, storage, trust boundaries), `DATA_FLOW` (pipeline 0, one chat turn), `AGENT_HARNESS` (where each part runs, client configuration precedence, permissions, hooks, sandbox), `MODEL_BOUNDARY` (model service and P2), a rewritten CLI reference (Ink, plain and headless modes, E1, settings schema, slash commands, `laris-server`, `laris-model`), edge limits and security checks in the deployment runbook, a new migration guide 1.x to 2.0 (`docs/development/MIGRATION_1X_TO_2_0.md`); owner runbooks now name `laris-server data|train|evaluate`. The user guide `.laris/help` is unchanged (owner approval pending, see `CLIENT_GUIDE_DRAFT.md`).
- **Security suite (T83):** `tests/security` and `make test-security` (a CI step): hostile network clients, a compromised container (static compose checks and the real `caddy:2`), a hostile project folder, hostile hook output, injected shell and install requests, a tampered sandbox download.
- **Client acceptance suite (T82):** scripted sessions through the engine, headless `stream-json`, plain mode and the Ink front end (recorded from the engine and kept equal by a test), `make test-client` in CI, and a draft user-guide section for owner approval (`docs/development/CLIENT_GUIDE_DRAFT.md`).
- **Three blocks (ADR-019):** `client`, `server` and `model` programs over shared `protocol` and `shared` packages, with import-boundary tests; protocols P1 (client-server, HTTPS and SSE), P2 (server-model, internal) and E1 (engine protocol over stdio, `laris engine --stdio`).
- **Server storage on PostgreSQL:** numbered migrations, atomic token quota (reserve, settle, release), monthly partitions, retention worker, SQLite importer, `laris-server db migrate|import-sqlite`.
- **Docker deployment:** API and model images (CPU and CUDA), Compose stack behind Caddy with Docker secrets and read-only policy, backup and restore scripts, image scanner, end-to-end smoke test, deployment runbook.
- **Client storage:** one SQLite file per project and key under `~/.laris/projects/<slug>/`, with idempotent import of older data.
- **Settings:** schema-validated `~/.laris/settings.json`, `laris config get|set|schema`, `.credentials.json` (0600), certificate pinning by `server.caFingerprint`, global-home migration from 1.x; project files no longer contribute settings.
- **Automatic sandbox:** `~/.laris/.venv` built and repaired with `uv` under a file lock; installs outside the sandbox are denied by a built-in rule.
- **Slash-command registry** with custom commands (`~/.laris/commands`, `./.laris/commands`, `$ARGUMENTS`), per-project trust state and completion through E1.
- **Permission modes and rules:** `default`, `acceptEdits`, `plan`, policy-gated `bypass`; `allow`/`ask`/`deny` rules; "always allow" kept per session, project or everywhere.
- **Coding tools:** `Read`, `Write`, `Edit`, `Glob`, `Grep`, `Bash` with diffs in permission requests, a checkpoint per edit and `/rewind`.
- **Input forms:** `@path` mentions, `!command`, `# note`, long pasted text and pasted images (local OCR).
- **Headless mode:** `laris -p` with `--output-format text|json|stream-json`, `--continue`, `--resume`, `--max-turns`, `--permission-mode`, `--allowed-tools`, `--disallowed-tools` and documented exit codes.
- **Hooks and folder trust:** `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse` and `Stop` hooks declared only in `~/.laris/settings.json`, run in the sandbox with block decisions and timeouts, `/hooks`; project commands and skills are used only after the folder is trusted.
- **Status line, queued input and interrupt:** engine `status` events (model, mode, context use, tokens left from the account route, git branch, sandbox state), `/cost` and `/context` from the same values; messages typed while the agent works are queued in order; an interrupted turn leaves every tool call answered in the saved conversation.
- **Plain-text mode:** `laris --plain` is an E1 front end that uses only `input` and `print` (messages, slash commands, approvals with diffs as text, Ctrl+C); it replaces the old `input()` loop and needs no extra dependency.
- **Ink front end:** `laris` opens a terminal interface written in TypeScript with Ink and React over engine protocol E1: multi-line input (backslash+Enter), history and Ctrl+R search, `/` and `@` completion from the engine, streamed Markdown with code highlighting, a spinner, approval dialogs with diffs and "always allow" scopes, a status line, Esc to interrupt, Ctrl+C twice to exit, Shift+Tab to change mode and typing while the agent works (queued). It checks the protocol version in `ready` and refuses a mismatch; if the interface cannot load, the launcher starts `--plain`. `laris --resume` lists sessions to choose from; `laris --continue [ID]` continues the newest session or the one named by id (unique prefix accepted).

### Fixed
- **Dead command removed:** `laris app ask` was in no command table and always raised (extractive answers need a server-side QA model); ADR-019 section 2c records it and that `laris login --server` stays as a shortcut.
- **Permission rules and installs:** an `allow` rule for one shell command no longer lets a chained, piped or substituted second command through; `deny` and `ask` rules match any part of a line; the built-in install rule reads `&`, new lines, `$(…)`, backticks, groups, `bash -c` and wrappers, and checks every part of a line.
- **Hostile project folder:** the client no longer reads a project `.env` (it could redirect the model, switch approvals off and disable the integrity check); `Grep` no longer follows a symlink out of the project.
- **Server and proxy:** a deeply nested JSON body is a 400, not a 500; Caddy now closes slow TLS handshakes and slow headers (`read_header`, `read_body`, `idle`).
- **Hooks:** invalid UTF-8 output no longer crashes the runner, output is read with a bound, and terminal escape sequences are removed from what a hook shows.

### Changed
- The npm package now needs Node 22 or newer (Ink 8) and ships the compiled front end; `ink` 8.0.0 and `react` 19.3.1 are runtime dependencies.
- Diagnostics of `laris -p` go to standard error; tests no longer read or write the real `~/.laris`.

## [1.5.2] - 2026-11-12

### Changed
- **The client is a self-contained program (like Claude Code):** each platform package now carries the frozen client (PyInstaller, built from the compiled wheel), so `npm i -g @ntdev204/laris-cli` needs no Python, no `uv` download, no pip and no internet at first start; the launcher only runs it. Replaces the wheel-plus-private-Python design of 1.5.1, whose Windows package must not be used.
- **Releases publish themselves:** pushing a `v*` tag builds all five platforms, smoke-tests each program and publishes the six npm packages from CI (repository secret `NPM_TOKEN`); no manual `npm publish`.

## [1.5.1] - 2026-11-11

### Changed
- **Install and run on every OS (no build, no Python needed):** the npm client is now a small launcher (`@ntdev204/laris-cli`) plus one package per platform (`-win32-x64`, `-linux-x64`, `-linux-arm64`, `-darwin-x64`, `-darwin-arm64`, optional dependencies, so npm fetches only the matching one). When no suitable Python is installed, the first run downloads a private one through uv (SHA-256 checked; `LARIS_NO_DOWNLOAD=1` forbids it). Windows tries each installed Python through `py -3.x`. The compiled wheels are built by the manual workflow `client-package.yml` (5 platforms x Python 3.10-3.13) and split by `packaging/assemble_npm.py`; `build_client.py` no longer assumes Linux, `uv` or gcc.
- **`laris --version`** prints the installed version; a global install adds the npm bin folder to the user PATH on Windows (`postinstall`, opt out with `LARIS_NO_PATH_EDIT=1`) or prints the line to add elsewhere.

### Added
- **S2ORC acquisition (stages 01 and 02):** `laris-server data acquire --only S2ORC-GENERAL-LM|S2ORC-STEM` streams `s2orc` shards from the Semantic Scholar Datasets API (key from `S2ORC_API_KEY` only), filters on the fly (STEM identifier, open per-paper license, full text; both release schemas), and stores parquet with a hard byte budget per stage (`--s2orc-budget-gb`, default 10) and per-run shard limit (`--s2orc-max-shards`). No raw shard is stored; stages use disjoint shards; interrupted runs resume. STEM is approximated by external id, not field of study. No training is run.

## [1.5.0] - 2026-11-11

### Security
- **Trust on first use for private certificates:** `laris login --server URL` shows the server certificate's SHA-256 fingerprint and pins it after the user confirms (or `--trust-fingerprint`), so clients no longer need `SSL_CERT_FILE`; `laris-server tls init` and `model serve` print the fingerprint.
- **Client `settings.json` like Claude Code:** `~/.laris/settings.json` holds `base_url`, `model`, `api_key` (written by `laris login`, file mode 0600), `api_key_env` and personal notes; `laris logout` removes only the key.
- **AES-256-GCM and automatic HTTPS:** stored API keys now use AES-GCM (`cryptography`, new `server` extra; older blobs are resealed on next use); `laris-server tls init` creates a certificate and `model serve` turns HTTPS on from `serving.tls_dir`; the user guide now says model reasoning is stored on the server for operators only (integrity lock refreshed with owner approval).
- **Managed keys, quotas and private reasoning (ADR-018):** server database (SQLite) with API keys (`laris-server keys create|list|show|revoke|limit|roles`; digest only, shown once, accepted by the running server at once), roles and permissions (403), token quotas including unlimited (429, usage chunk, `GET /v1/laris/account`, `laris whoami`), a TTL cache, and the model's reasoning stored for the operator only (`laris-server reasoning list|show|purge`): it is diverted from `reasoning` events and `<think>` tags and never sent to any client, admin keys included. `laris-server usage summary`. Amends ADR-015 (the server now stores keys, usage and reasoning traces).
- **Encrypted keys, built-in server-only key (ADR-018):** keys are stored encrypted with a master secret (`LARIS_SERVER_MASTER` or a 0600 file outside the database; `laris-server keys reveal`), lookups use a keyed HMAC; the first start creates a built-in admin key with every permission, no limit, usable only from this machine (addresses found automatically); any key can be restricted by address (`--allow-ip`, `keys ip`).
- **TLS:** `laris-server model serve --tls-cert/--tls-identity` (or `serving.tls_cert_file`/`tls_identity_file`) serves HTTPS, TLS 1.2+; plain HTTP is refused off loopback unless `serving.allow_plain_http`. Clients always verify certificates (`SSL_CERT_FILE` for a private CA).
- **Compiled client wheel:** `packaging/build_client.py` compiles every client module to a native extension (Cython, build time only, new optional extra `build`), ships no `.py`, `.c` or docstrings, and smoke-tests the unpacked wheel (every module imports, no server or gateway code). Wheels are per Python version and platform; the launcher installs only the bundled wheel (`--no-index`) and then the pinned libraries.
- **System policy stays on the server (ADR-016):** prompt modules, rules, workflows and the brain are composed, consulted and guarded by the server (`src/gateway/`, `POST /v1/laris/chat`); the downloadable client never contains `.laris/` policy and works in an empty folder. The bare `/v1/chat/completions` endpoint is closed when the gateway runs and client `system` messages are dropped.

### Added
- **Agentic loop (ADR-017, T43-T46):** the model plans with `update_plan` (the harness records a plan itself when a multi-step goal starts without one), the plan is shown (`plan` events) and kept in the conversation; each tool result is checked (typed error or empty answer triggers at most `agent.reflect.max_replans` replans, then one stop-retrying notice); a goal is not closed while steps are pending or in progress (`agent.reflect.completion_retries`, then the answer says what is unfinished); an interrupted plan resumes with `--resume`; the finished goal and its plan go to the vault. 14 scripted scenarios (`docs/testing/AGENTIC_SCENARIOS.md`); the core model is still NOT QUALIFIED.
- **Layers and Agentic (ADR-017):** runtime layers loop -> harness -> prompt and capability ladder LLM -> RAG -> Agent -> Agentic; Agentic is a system requirement (SR-H8, tasks T42-T46). `tests/unit/architecture/test_layers.py` enforces the layer dependencies; the API-key helpers moved to `harness/credentials.py`.
- **Client-only package:** the npm wheel is built from the modules `cli.client` reaches (no gateway, serving or operator commands); first start creates `~/.laris/` (`settings.json`, `config.yaml`, `LARIS.md`, `skills/`, `memory/`); preferences live in `~/.laris/settings.json` (`app.settings_file`).
- **npm client:** `packaging/npm` (`@ntdev204/laris-cli`: launcher plus wheel, private virtualenv on first run; not published). `laris login --server URL` and `laris init`; client folders are global `~/.laris` and project `./.laris`. `laris-server model serve --policy-root`.

### Changed
- **Client and server executables:** `laris` (client: agent, account, vault, skills, learn, `app ingest|search|status`) and `laris-server` (operator: `model serve`, `harness`, `brain`, `workflows`, data, training, evaluation, `app index|ask`). The client no longer lists or accepts server commands.
- **Brain approved by the owner; Vietnamese routing:** domain hubs gained Vietnamese keywords, so Vietnamese tasks reach their hub (they matched none before).

## [1.4.0] - 2026-11-11

### Security
- **Server authenticates keys (ADR-015):** `laris model serve` accepts only configured API keys (`LARIS_SERVER_KEYS`, comma separated, or `serving.allowed_file`), refuses to start without any (`serving.require_auth`), answers 401 otherwise and `/health` reveals nothing. The client checks its key at `laris login` (a rejected key is not saved) and at session start. The `serving` package is contract-tested to hold no user data: no tool/vault/application imports, no file writes, no logging. Principle: the user's disk is the database and the user's machine is the sandbox.

### Removed
- **Web interface:** `src/application/server.py`, `web_ui.py`, `laris app serve`, the `/guide` page and all HTTP chat routes are removed by owner decision; LARIS is terminal-only for now. `laris model serve` (the OpenAI-compatible model API) stays.

### Changed
- **API key per user:** `laris login|logout|whoami`; bare `laris` asks for the key (hidden input) when none is known (`LARIS_API_KEY`, else the 0600 file `~/.laris/credentials.json`, config `app.key_env`, `app.account_file`). The key is the model API bearer token and names a private space: conversations, settings, uploads, archive, audit and collected sessions live under `artifacts/chat/users/<one-way fingerprint>/`; another key sees none of it. `laris --resume` lists only the signed-in key's sessions. Keys typed into a message are masked before they reach the model, the conversation file or its title.
- **User guide is for users; `laris` opens the chat:** `/how-to-use` no longer documents running servers or operator commands (a test enforces it). Bare `laris` opens the terminal chat; `laris --resume` lists saved sessions to choose from (Enter = newest, `n` = new) and `laris --resume <id|prefix>` reopens one.
- **New knowledge goes to the brain by domain; skills only on request:** ingestion no longer creates `corpus-*` skills (`learning.skill_on_ingest` now defaults to false). Instead each ingested document adds a Knowledge note under `vault/Knowledge/<domain hub>/` (domain chosen by routing over the brain hubs, `General` otherwise) with key terms, claims, methods, datasets and metrics; the brain tools list these notes beside the matching hub while the protected core brain stays unchanged. New tool `save_knowledge` (approval required) adds taught knowledge; `save_skill` is reserved for skills the user asks for.

### Added
- **Project vault and system brain (Obsidian format):** `src/vault/` reads, indexes, lints and safely writes Obsidian-format vaults (properties, wikilinks, tags, managed blocks with user-edit conflict detection). The first piece of work in a codebase creates `vault/` and every ingest and verified chat turn adds linked Source, Concept, Question and Session notes. The system brain `.laris/brain/` is a protected hub tree (65 notes: root, ten domain hubs, topic hubs, leaves, playbooks for the six scholarly directions) read only through `brain_open_root|route|open|neighbors|search|consult`; a consult step adds a short hidden brief per task and shows only note titles. Brain text is covered by `integrity.lock`, denied to file tools and counted as confidential by the leak guard. New: `laris vault init|check|status`, `laris brain check|tree|route`, ADR-014, `docs/specifications/OBSIDIAN_VAULT_FORMAT.md`, `docs/architecture/BRAIN_THREAT_MODEL.md`, a golden fixture vault. Prompt manifest 1.2.0, rule C-7, workflows 1.1.0.
- **System ledger for the next phase:** `.claude/spec/spec.md`, `plan.md` and `task.md` define the Obsidian-compatible brain (system brain and project vault), six scholarly application directions, a harness-first plan and 39 tasks; `scripts/validate_spec.py` and a contract test keep the three files consistent. The core model stays paused.

## [1.3.1] - 2026-11-11

### Removed
- **Spec/plan/task ledger:** `.agents/spec.md`, `.agents/plan.md`, `.agents/task.md`, `scripts/validate_work_plan.py`, its contract test and the `workflow` make target are retired by owner decision; the system harness is built first and the core model resumes afterwards. Earlier changelog entries still mention them as history.

### Added
- **`/how-to-use`:** a detailed Vietnamese user guide prepared in `.laris/help/how-to-use.md` and printed verbatim by `/how-to-use` (web chat, web "Hướng dẫn" button, terminal) and `laris agent guide`, with no model call. The file is covered by `integrity.lock`; the web chat renderer now supports tables, quotes and rules. Help turns are shown in history but never sent to the model, counted in context or collected as training data.

## [1.3.0] - 2026-11-11

### Changed
- **Flat source layout:** the `src/laris/` package directory is removed; every domain package (`agent`, `application`, `cli`, `config`, `core`, `corpus`, `evaluation`, `execution`, `graph`, `language`, `orchestration`, `reasoning`, `reporting`, `retrieval`, `scientific`, `serving`) now lives directly in `src/`. Imports change from `laris.language...` to `language...`, `python -m laris.x` to `python -m x`, and the `laris` command points at `cli.main:main`. `__version__` moved to `core`. Reinstall once with `uv pip install -e . --no-deps` to refresh the console script.

### Added
- **Learning from use:** ingesting documents now builds a complete generated RAG skill (`corpus-*`, metadata only, never overwrites hand-written skills), `skill-authoring` skill and an approval-gated `save_skill` tool with a completeness and safety lint, `laris skills lint|add|sync`, and local fine-tune data collection (`sft`, `retrieval` pairs, `preference` pairs) behind a quality gate with redaction, ratings, `laris learn stats|export|purge`, `/rate` and `/learn`. Nothing is trained by the system.
- **`.laris/` policy folder:** prompts moved to `.laris/prompts/`, `LARIS.md` split into an entry file plus `.laris/rules/*.md`, declarative `.laris/workflows/` (`grounded-qa`, `document-intake`, `evidence-review`, `research-brief`) enforced by the loop (tool allow-list, step cap, stricter approval, required output sections), and `integrity.lock` so tampered policy stops every session. New `laris workflows` and `laris harness verify|lock` commands, `/workflow` and `/workflows` in chat.
- **Agent harness and standard system prompt:** versioned prompt modules in `.laris/prompts/` (manifest, strict placeholders, per-session canary, hashed in audit logs), `LARIS.md` rewritten as strict internal policy with stable rule IDs, and a shared `harness` package (guards, path and approval policy, answer verifier, audit log, preferences) driving the agent loop. Leak defences: secret and absolute-path redaction, shingle and canary leak detection on streamed and final text, deny-listed internal files, untrusted tool-result tagging with injection flags, and a loopback-only model API unless allowed. All limits, paths, endpoints and messages now come from configuration (`configs/default.yaml`, `.laris/config.yaml`, saved preferences, `LARIS_*` environment, `.env`, flags); see `docs/architecture/AGENT_HARNESS.md` and `.env.example`.
- **Instructions, skills, memory and autocompact:** `LARIS.md` is always read into the system prompt; 15 research skills in `.laris/skills` load on demand through `use_skill` or `/<skill>` (with a `/` menu in the web UI and `laris skills list|show|check`); project memory in `.laris/memory`; and automatic context compaction (on by default) with archive, `/compact` and `/context`, so long sessions continue without hitting the context limit.
- **Local chat application and agent:** chat web UI, Claude-Code-style terminal session, typed tool layer with OCR, and an OpenAI-compatible model server with a pluggable backend (placeholder until the core model is trained).

## [1.2.0] - 2026-11-11

### Added
- **Foundation tokenizer remediation F06-R1:** 48k SentencePiece BPE without digit splitting passes fertility (EN 1.286, VI 1.193 against a 1.35 limit), a shared scientific-text normalization (`--normalize-input`) applied at training and inference, `--vocab-size` and `--no-split-digits` options, and a first from-scratch 10,000-step round (best validation mean loss 0.3827). Dense retrieval is still untrained (SciFact dev MRR 0.007 against BM25 0.636) because the contrastive stage has not run; the model is NOT QUALIFIED.
- **Retrieval benchmark and human-gold workflow:** frozen SHA-256 retrieval benchmark (BM25, dense, hybrid RRF) with SciFact expert relevance and a Vietnamese cross-lingual diagnostic, pooling, blind sheets, weighted kappa and adjudication for human relevance gold (no agent-created labels), plus the D05 protocol and owner prerequisites documents.

### Changed
- Documentation consolidated (research strategy, templates, archive) and the owner runbook gained the F07 held-out measurement commands.

### Changed
- **System-level project documents (Issue #316):** replaces the completed preparation ledger with `.agents/spec.md`, `.agents/plan.md` and `.agents/task.md`: twelve system requirements, eight ordered phases and 32 project tasks. Generalizes three-way validation for multi-task requirements, owner-only training, stage gates and completion evidence. The next implementation task remains unstarted.
- **Owner-only training preparation (Issue #315):** adds cross-checked `.agents/spec.md`, `.agents/plan.md` and `.agents/task.md`, preserves functional source packages, moves diagnostics to `experiments/` and measurements to `reports/`, and removes conflicting/historical training claims. Model 01 qualification precedes model 02. Agent/CI preparation checks explicitly exclude optimizer-bearing tests.

### Added
- **Formal offline readiness (Issue #315):** `laris evaluate readiness` audits all twelve foundation gates, protocols, split and artifact identities without loading a model. Current validation remains NOT QUALIFIED. Future model evaluation reports include PAWS macro F1, explicit QA token-span protocols and split-manifest provenance. An owner runbook provides parsed profiling/training commands without executing them.

- **Empirical readiness (Issue #313):** records validation of the compact checkpoint on 27,213 samples and a reproducible 20-paper scientific-NLP pilot, including weak dense retrieval and manual extraction failures. Adds bounded experiment scripts, measured evidence, and current-readiness links; training and thresholds are unchanged.

### Fixed
- **Benchmark certification (Issue #309):** evaluation now requires an evaluator or explicit measured metrics, rejects empty/non-finite measurements, and fails runs with incomplete or failed benchmark items instead of returning fixed passing scores.

### Fixed
- **Source-backed reports (Issue #311):** `SourceEvidenceGate` validates actual source hashes, citation identities, offsets and verbatim excerpts, rejects unsupported synthesis and unregistered prose, and refuses zero-assertion reports. The existing gate labels its verification scope as citation IDs only.

## [1.1.7] - 2026-10-30

### Fixed
- **Dataset order, validation and allocator (Issue #305):** found in a real 60k-step run that early-stopped at step 5800. The loader read a task's datasets one file after another (SQuAD, then ViQuAD, then HotpotQA; 2.0M English Wikipedia rows before any Vietnamese), so a run would meet Vietnamese MLM only at the very end; it now samples across a task's datasets in proportion to their rows. Validation kept streaming, so each evaluation scored a different slice: after about 3,286 rows the QA validation moved from SQuAD to ViQuAD (qa 0.55 to 0.92) and early stopping fired at 10% of the schedule; the validation loader is now rewound before every evaluation so it scores the same records, and `--eval-batches` defaults to 16. Variable batch shapes fragmented the CUDA caching allocator (OOM retries at 16 GB with 9 GB allocated); `laris` now sets `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` unless already set.

## [1.1.6] - 2026-10-30

### Changed
- **Training no longer computes on padding or unused heads (Issue #301):** on the real train data the mean sequence is 28% of 1024 tokens for MLM, 50% for QA and 3-6% for NLI/paraphrase/similarity, yet every batch was padded to 1024 and every micro-batch computed the full (batch, 1024, 32000) MLM logits even for other tasks (a compact run took 1.12 s per optimizer step, 31 h for 100k steps, GPU at 99%). The model now computes only the head of the task being trained, and for MLM only at the masked positions; training and validation batches are trimmed to their longest real sequence (multiple of 8) and similar lengths are grouped inside a pool of 8 batches. The loss is unchanged (tests compare padded vs trimmed and full vs masked-only heads). Profiling keeps full-length batches so it still reports the worst case. Measured forward-only on the GPU with real data and an identical task sequence: 198 ms to 40 ms per micro-batch; the backward pass was not measured.

## [1.1.5] - 2026-10-30

### Fixed
- **Flaky evaluation exit-code test (Issue #298):** the fixture feeds identical inputs to the similarity head, so Spearman is decided by float noise and could fall below the test's `min_absolute` of 0.0; the test now relaxes that floor and still asserts the exit code from `min_margin`.
- **Token order and weight decay (Issue #295):** the PyTorch backbone never applied rotary position embeddings, although the config fixes `pos_encoding="rope"` and the NumPy reference does; reversing the tokens left every hidden state unchanged (max difference 2e-6), so the model could not learn word order for MLM or QA. Q and K now get split-half RoPE (same formula as the reference, tested against it). AdamW weight decay no longer touches RMSNorm gains, biases and the tied embedding, the QA span softmax ignores padded positions, and an MLM batch with no masked token yields a zero loss instead of NaN. Runs started before this fix train an order-blind model and must be restarted.
- **Encoder initialisation (Issue #293):** the PyTorch encoder kept the `nn.Embedding` default N(0, 1) for the tied token embedding, so a fresh model produced logits with a standard deviation of 27.8 and a raw MLM cross-entropy of 542.7 instead of about ln(32000) = 10.4 (a real run logged loss 197.66 and gradient norm 259 at step 1, clipped to 1.0 every step). The model now uses GPT-2 style initialisation (normal std 0.02, zero biases, residual projections scaled by 1/sqrt(2L)) and seeds itself before creating parameters, which it did too late before. Measured on real validation data with the fitted tokenizer, the initial raw MLM loss is now 10.20. Runs started before this fix begin from the bad initialisation and should be restarted.
- **Compact sequence length (Issue #288):** `--model-size compact` clamped the model config to 512 tokens even when `--max-seq-len` was larger, while the dataloader used the requested length. Evaluation and inference read the length from the saved config, so a compact model trained at 1024 tokens would have been evaluated and used at 512. `--max-seq-len` now defaults to 1024 for large and 512 for compact and is honored as given.

### Added
- **Live training display (Issue #291):** `laris train language-encoder` now shows a progress bar with elapsed time, ETA and rate, and a metrics line with the running loss of each task (exponentially smoothed, so single-task micro-batches no longer make it jump), learning rate, gradient norm, GPU memory and the accumulation position. Validation prints as a table with the best step and the early-stopping counter. When output is not a terminal (`nohup`, redirected logs) or `tqdm` is missing it falls back to one plain line per `--log-interval` steps with the ETA. `tqdm` joins the `training` extra.

## [1.1.4] - 2026-10-30

Re-release of 1.1.3 under a new version: the first `v1.1.3` tag pointed at an older commit and was withdrawn. The changes are the 1.1.3 entries below.

## [1.1.3] - 2026-10-30

### Fixed
- **Review fixes before release (Issue #282):** the authorized profile now scales the loss with the trainer's `GradScaler` before backward (it crashed with `--precision fp16`), and an answer with text but no `answer_start` is rejected by the ViQuAD2 partitioner and by the loader instead of becoming a "no answer" label (the real data has no such row).

### Fixed
- **Real data only (Issue #282):** an audit against the partitioned data showed rows that were silently given fabricated labels. 4,892 HotpotQA train questions without an answer span and 154 UIT-ViQuAD2.0 rows with a wrong `answer_start` were labelled "no answer"; 2 Quora pairs had an empty question. They are now dropped at partition time and `HOTPOTQA`, `UIT-VIQUAD-V2` and `QUORA-DUPLICATES` were re-partitioned (a scan of all 7,999,454 rows now finds 0 defects). The training loader raises on unknown NLI or paraphrase labels, a missing similarity score and a mismatched answer offset instead of mapping them to neutral, 0 or 0.0; with `require_real_data` (used by training, evaluation and profiling) it also refuses a missing tokenizer, default row counts and the synthetic fallback, and asking for a task without shards no longer silently returns another task.
- **Profile on real data:** `--profile-only` now needs the fitted tokenizer and measures real tokenized train batches (random token ids are gone). With `LARIS_TRAINING_AUTHORIZED=1` it runs a real optimizer step on a discarded randomly initialised model and measures the steady-state peak, so optimizer state and the bitsandbytes kernels are measured, not estimated. The analytic VRAM figure is removed from the CLI and `verify_target_server.sh` no longer runs a toy model on synthetic input.

## [1.1.2] - 2026-10-29

### Fixed
- **Measured GPU profile and paraphrase loss crash (Issue #278):** `laris train language-encoder --profile-only` no longer prints a formula result as "feasible". It builds the real model on the GPU and measures peak memory per task (forward only; with `LARIS_TRAINING_AUTHORIZED=1` also backward, still no optimizer step or weight update), exits non-zero without CUDA, and states that training memory is not certified until backward is measured. The analytical figure is labelled as a formula. The measurement exposed that the paraphrase loss (`binary_cross_entropy`) raised under CUDA bf16 autocast, which would have crashed training at the first paraphrase batch; it now runs in fp32 outside autocast. `scripts/verify_target_server.sh` no longer hard-codes another user's virtualenv path, and the runbook lists the profile as step 5/5b.

## [1.1.1] - 2026-10-29

### Removed
- **Dataset registry narrowed from 24 to 17 (Issue #274):** the registry keeps the 14 datasets that feed the language encoder plus S2ORC-STEM, LARIS-GOLD and NATURAL-QUESTIONS (planned for fine-tuning). VI-PAWS, UIT-VIQUAD v1.1, PUBLAYNET-MINI, DOCLAYNET-BOUNDED, UD-EWT-EN, UD-VTB-VI and SCIFACT lose their acquirers, manifest entries, coverage handling and tests; the manifest now reports 17 datasets, 8,288,209 records and 12.06 GB. Their raw directories (about 48 MB) were deleted from disk; they are re-downloadable from the public sources if a consumer appears.

## [1.1.0] - 2026-10-29

### Added
- **Pairwise dataset partitioning (Issue #264):**
  - `laris data partition` now partitions All-NLI, ANLI (R1-R3), PAWS-Wiki and STSB, keeping the upstream train/dev/test splits and removing train rows that collide with held-out val/test (pair level for NLI and STSB, either-sentence level for PAWS). The NLI, paraphrase and similarity tasks read them from `data/processed`.
  - A partial run (`--datasets X`) now merges into the existing `task_splits_manifest.json` by `dataset_id` instead of overwriting it.
- **Server preparation (Issue #266):** `laris data check` verifies manifest files, per-task train/val/test coverage and `sentencepiece` before training (exit 1 when not ready); `docs/development/CLI.md` carries the step-by-step server runbook.
- **FEVER evidence and threshold calibration (Issue #262):**
  - `laris data acquire --only FEVER` now resolves evidence references against the official FEVER Wikipedia snapshot (`wiki-pages.zip`) into `evidence_sentences.parquet` (the Hugging Face parquet copy is truncated and is not used). `laris data partition` turns SUPPORTS/REFUTES claims into entailment/contradiction premise-hypothesis pairs; NOT ENOUGH INFO has no evidence and is dropped. The language encoder's NLI task now loads `fever`.
  - `laris evaluate calibrate` ratchets `configs/evaluation/language_encoder.yaml` up from passing `val` reports (never lowers; refuses `test` reports). The shipped thresholds remain baseline-relative floors until a trained checkpoint is measured.

### Changed
- **Security reporting (Issue #265):** `SECURITY.md` points to GitHub private vulnerability reporting, which is now enabled for the repository.
- **Documentation trim (Issue #267):** condensed `LAYER_ARCHITECTURE` (216 to 66 lines), `ORCHESTRATION_SPECIFICATION` (195 to 140) and `DATA_SCHEMAS` (185 to 71) into tables; every invariant, enum and required field is preserved.
- **Documentation slimmed and standardized (Issue #260):**
  - Removed redundant or historical files: `docs/archive/`, `docs/RELEASE_NOTES.md` (this changelog is the release history), `docs/DECISION_LOG.md` (the ADR index is the register), `docs/plans/BACKLOG.md` (work is tracked in GitHub issues), `SESSION.md` and `implement_plan.md`.
  - Condensed `DOCUMENTATION.md` (262 to ~110 lines) and the language encoder training specification (494 to ~330); stage 2-6 detail now lives in a gate table and the roadmap.
  - ADR index lists ADR-001 to ADR-013 and holds the FROZEN-document register used by `validate_docs.py`.
  - Added `SECURITY.md`, `.github/CODEOWNERS` and issue templates (bug, task, documentation); README and CONTRIBUTING describe the issue-to-PR workflow.

### Changed
- **Documentation consolidation (Issue #251):**
  - Merged overlapping documents: agent/skill/tool/workflow specs into `ORCHESTRATION_SPECIFICATION`; documentation standard and lifecycle into `development/DOCUMENTATION`; roadmap and milestones into `plans/ROADMAP`; training specification and staged pipeline into `LANGUAGE_ENCODER_TRAINING_SPECIFICATION`; language foundation, local model and semantic strategies into `research/LANGUAGE_AND_MODEL_STRATEGY`.
  - Moved `IDEA.md` and the delivered M1-M10 backlog task specifications to `docs/archive/` (excluded from the documentation gate); removed the duplicate ADR template.
  - Replaced machine-specific `file:///` links with relative links; rebuilt `docs/README.md`; shrank `SESSION.md`; added `docs/development/CLI.md`.

### Added
- **CLI evaluation and inference (Issue #250):**
  - `laris evaluate language-encoder` scores a checkpoint on `val`/`test` for MLM, NLI, paraphrase, similarity and QA per dataset and per language against baselines, writes a JSON report and exits non-zero when a task/language group misses `configs/evaluation/language_encoder.yaml`.
  - `laris train language-encoder` runs the same check on the best checkpoint after training (`--evaluate-after`, default on).
  - `laris infer fill-mask|nli|paraphrase|similarity|qa|embed` for single-example predictions; checkpoints and tokenizers are verified by SHA-256 before use.
  - Evaluation refuses the `train` split and requires a leakage-verified split manifest.

### Added
- **Language encoder training loop (Issue #248):**
  - Linear-warmup + cosine LR schedule (`training/schedule.py`); `--steps`, `--learning-rate`, `--warmup-steps` and loss weights now come from `configs/language_encoder/<size>.yaml` with CLI overrides.
  - Real mixed precision: `torch.autocast` for bf16/fp16 (+ `GradScaler` for fp16 on CUDA); non-finite gradients skip the update instead of corrupting weights.
  - Steps are counted per optimizer update (gradients accumulate across micro-batches and tasks); snapshots carry learning rate and gradient norm.
  - Atomic checkpoints (`training/checkpoint.py`): `model.pt`, `training_state.pt` (optimizer, scheduler, scaler, RNG, counters) and a provenance `manifest.json` (git commit, seed, config, tokenizer and dataset digests, model SHA-256); corrupt checkpoints are rejected on load.
  - `training/loop.py`: periodic validation on the held-out `val` split (never `test`), `best/` and `last/` checkpoints, early stopping and `--resume`.

### Added
- **Partitioning for the bilingual expansion datasets (Issue #249):**
  - `laris data partition` now handles ViNLI, ViSTS, HotpotQA, FEVER, UIT-ViQuAD2.0 and CC-100 VI with leakage-safe splits (per-dataset modules in `corpus.splits.partitioners`).
  - ViNLI keeps official splits and drops the 4th `other` label (the NLI head is 3-way); ViSTS is split by connected sentence components and rescaled to [0, 1]; HotpotQA is converted to extractive QA (supporting paragraphs first; yes/no answers carry no span); UIT-ViQuAD2.0 keeps its official train and sub-splits validation by article (it supersedes v1.1 on the same contexts, so v1.1 is not used as a QA source); CC-100 is hash-split with exact-duplicate removal against Wikipedia-VI; FEVER (claims only, no evidence text) is partitioned but not loaded for training.
  - Datasets whose license is not approved are skipped unless `--include-unreviewed-licenses` is given.
  - The streaming loader discovers the new directories and derives task sampling weights from Parquet footers instead of hard-coded counts.

### Changed
- **Functional package layout and `laris` CLI (Issue #247, ADR-013):**
  - `language/` split into `tokenization/`, `encoder/`, `training/`, `benchmarks/`; BM25 and the baseline comparison moved to `retrieval/`.
  - `corpus.acquisition` (common, sources, registry, runner) replaces the 1,450-line acquisition script; `corpus.splits` (ratios, physical, partitioners, coverage, runner) replaces `task_splits.py`.
  - Names no longer encode versions or stages: `LanguageEncoderTrainer`, `MultiTaskLossCalculator`, `LanguageEncoderConfig`/`LargeLanguageEncoderConfig`, `CorpusIngestionPipeline`; `--model-tier 500m` is now `--model-size large`.
  - New `laris` command (`data acquire|partition`, `train tokenizer|language-encoder`); `scripts/*.py` are thin wrappers. `train_stage1.py` is now `train_language_encoder.py`.
  - Configs organised by function (`configs/language_encoder/{compact,large}.yaml`, `configs/data/partition.yaml`); unit tests mirror the source tree under `tests/unit/<domain>/`.

### Fixed
- **Training data integrity (Issue #246):**
  - `StreamingParquetMultiTaskDataLoader` reads only the configured split (`split="train"` by default); val/test shards are never mixed into training.
  - Extractive QA labels now come from the real gold answer offsets (unanswerable or truncated answers point to `[CLS]`) instead of a fixed position.
  - Fallback tokenizer uses CRC32 so token ids are stable across processes; `scripts/train_stage1.py` now requires `--tokenizer-model` and a vocab match.
  - No silent synthetic-data fallback (`fallback_to_synthetic=False` by default); unreadable shards are logged and dropped and cannot hang the stream.
  - Trainer moves the model to its device; falling back from 8-bit AdamW emits a `RuntimeWarning`.
  - SentencePiece args reserve `[MASK]` as id 4, matching the special-token contract (previously id 4 was `[MATH]`).
  - CI installs CPU PyTorch so neural tests run instead of being skipped.

### Added
- **Bilingual expansion dataset acquisition (Issue #244):**
  - Automated, resumable acquisition for `VINLI`, `VISTS`, `HOTPOTQA`, `FEVER`, `UIT-VIQUAD-V2` and streamed `CC100-VI-CLEAN` (2.7M documents), plus `VI-PAWS` recorded as `BLOCKED` (no Vietnamese PAWS-X exists). `scripts/acquire_datasets.py --only DATASET_ID` merges into the existing manifest.
  - Manifest now tracks 24 datasets, 8,347,135 acquired records (4.23M English, 4.12M Vietnamese), 12.09 GB. `VINLI`, `UIT-VIQUAD-V2`, `CC100-VI-CLEAN` declare no license; the project owner approved their use on 2026-10-29 (`APPROVED_BY_OWNER`, a governance decision rather than a legal clearance), so they are `VERIFIED`.
  - Corrected spec sources/licenses (FEVER CC-BY-SA-3.0, ViSTS MIT) and documented that the ~16.5M projection is unreachable with real data.
  - Manifest accounting contract test now checks invariants instead of a hard-coded total.
- **Genuine Multi-Task Parameter Optimization in `Stage1LanguageTrainer` (Issue #242):**
  - Implemented real autograd forward, task loss computation (`F.cross_entropy`, `F.binary_cross_entropy`, `F.mse_loss`), `loss.backward()`, gradient accumulation, `clip_grad_norm_`, and `optimizer.step()`.
  - Supported plug-and-play 8-bit AdamW (`bitsandbytes`) with automatic fallback to standard PyTorch AdamW.
  - Telemetry tracking genuine loss values, effective batch size, and peak CUDA VRAM allocation.
  - Strict authorization enforcement raising `TrainingExecutionProhibitedError` on unauthorized runs.
- **Real Streaming Parquet Multi-Task DataLoader (`StreamingParquetMultiTaskDataLoader`) (Issue #242):**
  - Streaming reader using `pyarrow.parquet.ParquetFile.iter_batches` guaranteeing strictly bounded RAM ($\le 250\text{ MB}$).
  - Temperature-scaled task selection ($\alpha = 0.7$) interleaving MLM, NLI, Paraphrase, Similarity, and QA streams.
  - Real dynamic MLM masking at 15% rate (80% `[MASK]`, 10% random token, 10% unchanged) with `-100` target masking.
  - Multi-task sequence formatting with `[CLS]`, `[SEP]`, padding, and attention masks.
  - Infinite shard cycling across epochs and support for both PyTorch tensors (`return_tensors="pt"`) and NumPy arrays (`return_tensors="np"`).
- **Stage 1 Training CLI Integration (`scripts/train_stage1.py`) (Issue #242):**
  - Integrated `StreamingParquetMultiTaskDataLoader` and `Stage1LanguageTrainer` into CLI runner supporting `--data-dir`, `--steps`, and `--log-interval`.
- **Unit & Contract Verification (`tests/unit/test_trainer_and_streaming_dataloader.py`) (Issue #242):**
  - Verified genuine parameter optimization, loss calculation, and weight changes after `optimizer.step()`.
  - Verified gradient flow across all 5 Stage 1 multi-task objectives.
  - Verified gradient accumulation behavior across micro-batches.

## [1.0.0] - 2026-10-23

### Added
- **Full 12-Layer System Baseline (Milestones M0–M10):**
  - Layer 0: Corpus ingestion, exact SHA-256 deduplication, and non-destructive task partitioning.
  - Layer 1: From-scratch 12-layer bidirectional Transformer encoder (109.56M backbone params, 109.76M with multi-task heads), RoPE rotary positional encoding, RMSNorm pre-normalization, GELU activation, and tied MLM embeddings (`src/laris/language/neural.py`).
  - Layer 1 Tokenizer: SentencePiece 32k BPE tokenizer training pipeline with clean train-only Wikipedia extraction and Unicode preservation validation (`src/laris/language/tokenizer_trainer.py`).
  - Layer 2: 3-way scientific NLI classifier, semantic equivalence, and negation/contradiction detection (`src/laris/semantic/`).
  - Layer 3: Scientific NLP, discourse segmentation, heading-agnostic section parsing, and STEM unit normalizer (`src/laris/scinlp/`).
  - Layer 4 & 5: Embedded evidence knowledge graph on SQLite with indexed nodes, edges, and provenance metadata (`src/laris/graph/`).
  - Layer 6: Multi-channel hybrid retrieval combining BM25 and dense cosine projections with Reciprocal Rank Fusion (`src/laris/retrieval/`).
  - Layer 7: Epistemic research reasoning, 12-class research gap discovery matrix, and contradiction analysis (`src/laris/reasoning/`).
  - Layer 8: Multi-agent orchestrator with state-machine DAG execution, cycle detection, and token budget governance (`src/laris/orchestration/`).
  - Layer 9: Adaptive local execution, hardware memory headroom governor (14.5 GB ceiling), and LRU module cache (`src/laris/execution/`).
  - Layer 10: Capability evaluation suites, benchmark isolation, and feedback tracking (`src/laris/evaluation/`).
  - Layer 11: Structured report synthesis, citation attribution, and epistemic verification (`src/laris/reporting/`).
- **Data Acquisition & Scalable Inventory (Milestone M11 / M1):**
  - Acquired 14 open-access datasets totaling 5,106,491 records (3.78M English, 1.32M Vietnamese) across Wikipedia EN/VI, Universal Dependencies, All-NLI, ANLI, Quora Duplicates, PAWS-Wiki, STS-B, SQuAD v1.1, UIT-ViQuAD, SciFact, and PubLayNet.
  - Cryptographic verification via SHA-256 digests in `data/acquisition_manifest.json`.
- **High-Performance Physical Dataset Partitioning (Issues #232, #234):**
  - Streaming Parquet partitioning via `pyarrow.parquet.ParquetFile.iter_batches` guaranteeing bounded memory.
  - Multi-worker parallel processing across shards via `ProcessPoolExecutor` utilizing 14 CPU cores on target server.
  - Streaming merge engine consolidating intermediate shard parts directly on NVMe SSD with automatic temporary cleanup.
  - CLI utility `scripts/partition_datasets.py` supporting `--batch-size` and `--num-workers`.
- **Tokenizer Pipeline & Clean Extraction Runner (Issue #232):**
  - Train-only Wikipedia text extraction strictly rejecting validation and test partitions (`DataLeakageError`).
  - SentencePiece 32k BPE training runner gated by centralized authorization.
  - CLI utility `scripts/train_tokenizer.py` supporting `--authorized` execution.
- **Centralized Configuration System (Issue #215 / PR #217):**
  - 4-tier configuration architecture (`src/laris/config/`) enforcing immutable invariants (14.5 GB VRAM ceiling, zero data leakage) alongside tunable parameters.
- **Target Workstation Verification & Blackwell Support (PR #224, #229):**
  - Target server verification kịch bản `scripts/verify_target_server.sh` verifying NVIDIA GeForce RTX 5070 Ti, Blackwell `sm_100/sm_120`, CUDA $\ge 12.6$, and PyTorch $\ge 2.6.0$.
  - Bounded forward-only profiling and non-training hardware telemetry (`src/laris/language/profiling.py`).
- **Governance & Stop Condition Barrier:**
  - Mandatory authorization gate in `src/laris/core/authorization.py` ensuring zero accidental training on developer workstation.
- **Comprehensive Quality Gates:**
  - 1018 automated tests passing in `tests/`.
  - Zero `ruff` and zero `mypy` errors across 90 source files.
  - 61 formal documentation files validated by `scripts/validate_docs.py`.
  - Canonical `SESSION.md` capturing full codebase state and target server execution guide.

### Changed
- Reconciled documentation and updated `docs/specifications/NATURAL_LANGUAGE_TRAINING_SPECIFICATION.md` to serve as the single source of truth for neural architecture, hardware envelopes, and formal readiness gates.
- Resolved and closed open architecture questions OQ-001, OQ-002, OQ-003, and OQ-005 in `docs/OPEN_QUESTIONS.md`.

### Removed
- Removed resolved, one-off audit reports (`REPOSITORY_AUDIT.md`, `CONFIG_AUDIT_REPORT.md`, `MODEL_TRAINING_AUDIT.md`, `TRAINING_READINESS_AUDIT.md`) following full remediation and consolidation into core specifications.
