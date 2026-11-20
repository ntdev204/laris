# LARIS Changelog

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). Earlier releases and tags were removed on 2026-11-20;
this is the first release of the Rust generation. History lives in git.

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
