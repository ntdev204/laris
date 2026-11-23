# LARIS Changelog

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). Earlier releases and tags were removed on 2026-11-20;
this is the first release of the Rust generation. History lives in git.

## [Unreleased]

### Changed
- **One engine for chat and evaluation (T282):** the packaged server (`docker/laris.sh up`) serves Qwen3.5-4B in BF16
  from a vLLM server container (`vllm/vllm-openai:v0.34.0`, internal network, offline, weights read-only). The model
  service forwards chat to it (`ServedChat`) with the same reasoning split, tool calls, input budget and streaming as
  before, and its GPU queue counts the server's reservation (`LARIS_ENGINE_GPU_SHARE`, default 0.85). The model
  service image no longer carries `torch`. The STEM benchmark runner calls the same server
  (`LARIS_ENGINE_PORT=38100`, loopback only); `scripts/stem_benchmarks.py engine-up/engine-down` are gone.
  `model_service.chat_quantization` now defaults to `none` (BF16).
- **VRAM ceiling 15 GB (owner):** `model_service.vram_budget_bytes` is 15,000,000,000 and the vLLM server reserves 0.78
  of the GPU by default; measured peak of the whole GPU under benchmark load: 13.70 GB.

### Fixed
- With thinking on, reasoning that the chat template opens in the prompt no longer streams as answer text, also when a
  reply is cut off before `</think>`; a partial `<tool_call>` tag no longer reaches the chat body.

## [1.5.0] - 2026-11-21

### Added
- **Reading real papers:** a PDF the built-in reader cannot use (scan, unusual fonts) is read by `pdftotext`, then by
  `pdftoppm` + `tesseract` (`vault.ocr`; nothing hardcoded). `WebFetch` now reads PDF links. `ingest_document` and
  `WebFetch` report `read_by`; `ingest_document` also returns `origin` and `cite_as`.
- **`research-gap` workflow:** from PDFs, a folder or keywords to a paper register (`P1..Pn`), per-paper abstract,
  methods, limitations and future work, conflicts, and ranked research gaps with paper ids as evidence.

### Changed
- **VRAM on tool turns:** the model service bounds the prompt (`model_service.chat_max_input_tokens`, default 8192) by
  shortening old tool results, and returns GPU memory after every reply (`chat_release_cache`). The new peak is not yet
  measured.
- A repeated identical call is refused instead of ending the turn; the packaged server defaults to the 4B chat model.

## [1.4.1] - 2026-11-21

### Fixed
- The interface no longer draws the loop's own `too_many_calls` refusal as a failed tool.

### Changed
- A step may call as many tools as the model asks: `agent.maxToolCallsPerStep` now defaults to `0` (no limit), so several
  searches in parallel no longer fail with `too_many_calls`. Set a positive value to cap it again.

## [1.4.0] - 2026-11-21

### Added
- **Web tools and clock, built in:** `Now` (date, time, machine), `WebFetch` (reads a public page as text) and `WebSearch`
  (keyless search through a configurable HTML search page). They run in the client, read public addresses only, and
  refuse requests that carry a secret. Settings under `web`.
- **MCP mechanism:** the client starts the MCP servers named in `mcp.servers` inside the OS sandbox and offers their tools
  as `mcp__<server>__<tool>`; none is configured by default. `/mcp` shows what runs. Permission rules may end a tool name
  in `*` (`mcp__x__*`).

## [1.3.0] - 2026-11-21

### Changed
- `/usage`, `/context` and `/config` look like Claude Code's: progress bars for the session and the key, a context grid
  with a legend (used, free space, autocompact buffer), and an aligned, titled settings list.

## [1.2.0] - 2026-11-20

### Added
- **Automatic update, always on:** a release build checks its release address in the background, installs a newer
  signed release over the program, and shows a notice above the input box, at the right, when one is installed. `/restart`
  starts Laris again with the new version and goes on with the session. The release gains a signed `VERSION` file and a
  rolling `latest` release.

### Removed
- The setting `autoUpdates` (it was never read): updating is always on.

## [1.1.0] - 2026-11-20

### Added
- **Default slash commands:** `/usage` (tokens this session used, and the key's used, limit and left), `/context` (how
  full the context window is), `/model` (the models the server offers), `/config` (the session's settings) and
  `/export [file]` (the conversation as Markdown). The status line's `context N%` now comes from the usage the server
  reports after each answer.
- **`auto` permission mode, now the default:** the client reads, writes, creates and deletes files and runs commands
  without asking. Clearly destructive commands still ask: the calls that fit `permissions.autoAsk` (by default `sudo`,
  `su`, `doas`, recursive deletion of `/`, `~`, `$HOME` or a parent, `git push`, `git reset --hard`, `git clean`,
  `git branch -D`, `mkfs`, `dd`, `chmod -R`, `chown -R` and power commands). A list in the settings replaces the default
  one. `deny` and `ask` rules, `plan`, hooks, folder scope and the sandbox still apply. To keep asking first, set
  `permissions.defaultMode` to `default`. Available in `/mode`, Shift+Tab and `--permission-mode`.

### Changed
- **Client interface:** the input box is two rules with a `>` prompt (no side borders); the banner is two lines (name and
  version, folder); the status line shows model, context and tokens left (no mode, branch or sandbox); the server's
  working stages (checking, deciding, asking) are hidden unless one fails.

### Removed
- `/quit` (use `/exit`).

## [1.0.2] - 2026-11-20

### Added
- **Request pipeline in the server (ADR-025):** the compose stack runs the Prefilter, retrieval from the main brain, the
  rule decider, the evidence gate and answer assembly before and around the model. A covered question is answered from
  accepted claims without the model, an uncovered one abstains (`grounding=required`) or goes to the model
  (`optional`). Every stage is a setting (`LARIS_PIPELINE_*`, `LARIS_DECIDER_*`, `LARIS_BRAIN_*`). Protocol 2: the answer
  carries step events, the decision and the evidence list; the client shows the stages and the sources.
- `docker/smoke_test.sh` checks the pipeline; `scripts/server_eval.py` repeats the cognitive evaluation through the server.

### Fixed
- **Client display:** no flicker while typing or while a turn runs (one synchronised frame per redraw, a slower spinner
  that moves only while a turn runs); the spinner glyph is no longer one that terminals draw as a colour emoji. The
  banner is three plain lines.

### Notes
- An old client (protocol 1) gets 426 from this server. The model stays NOT QUALIFIED; the T243 reports are system
  measurements only. The gate and decider thresholds are untuned starting values.

## [1.0.1] - 2026-11-20

### Added
- **Zero-setup client:** the release is built with the server address compiled in (`LARIS_BUILD_DEFAULTS`, from the
  repository variable `LARIS_DEFAULT_SERVER_URL`), so a user installs the package, runs `laris` and enters a key. The
  address uses a publicly trusted certificate (Tailscale HTTPS), so no authority is pinned.
- **One command for the server:** `docker/laris.sh up | down | status | key`.
- **Release workflow** creates the GitHub release and publishes the npm package (`@ntdev204/laris`) when run with `publish`.

### Notes
- 1.0.0 was published first (GitHub release and npm) without the default address; 1.0.1 replaces it as the version to install.

## [1.0.0] - 2026-11-20

First release of LARIS as a Rust system. It stands alone and reads nothing from earlier generations.

### Added
- **System and server (Rust):** the terminal client (`laris`), the agent loop, harness and prompt layers, the policy gateway
  server (`laris-server`, PostgreSQL schema `laris2`), the sandbox, the evidence gate, retrieval, the vault and the
  protocol crates P1 (client-server) and P2 (server-model), with JSON schemas checked by `cargo xtask schema --check`.
- **Policy under an integrity lock:** `.laris/` (policy, prompts, rules, workflows, harness policy) covered by
  `integrity.toml`; refresh with `laris-server policy lock`.
- **Gates:** `cargo xtask spec | guard | scan | schema | security | bench`; the security suite covers 30 threats of the
  threat model (`docs/architecture/THREAT_MODEL.md`).
- **Distribution:** release profile (LTO, strip), `cargo xtask dist` (package, manifest, sign, verify), `install.sh`,
  `install.ps1` and an npm wrapper; every route checks a signature and a checksum. See `docs/guide/DISTRIBUTION.md`.
- **Model service (Python):** `laris-model serve` with scientific and scholarly tools and the chat backend; the model is
  an open-weight third-party LLM chosen by the owner (D48, `reports/verification/T228-open-llm-selection.md`).

- **Main brain (ADR-024):** knowledge notes with a certainty ladder, the single write gate, answer assembly from accepted
  claims with an outside-set check, the rule decider behind the loop's `Decider` seam, a decision dataset with a sealed
  held-out split and a decision network (inference in Rust). The network is **not promoted**: held-out gate N1 fails
  and N5 is not verified (`reports/brain/T171-decision-net-gates.json`); the rule decider decides.
- **Evaluation:** `cargo xtask decision-gates` and the cognitive evaluation (`reports/brain/T172-cognitive-evaluation.json`,
  system measurements, not a model qualification).
- **Chat model in the stack:** `docker/compose.chat.yaml` serves Qwen3.5-9B (8 bit, GPU) through the model service.

### Removed
- **Self-trained model (D48):** the encoder, tokenizer, training and evaluation code and data pipeline, with their
  commands, configs, documents and reports.

### Notes
- The model is **NOT QUALIFIED**: no capability is claimed without a measurement on a held-out gate (ADR-008).
- Verified before release: `cargo fmt --check`, `cargo clippy -D warnings`, `cargo test` (886 tests, with PostgreSQL),
  `cargo deny check`, `cargo xtask spec|guard|scan|schema --check|security`.
