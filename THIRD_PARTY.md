# Third-party components

Skeleton created in T121. Every crate vendored under `vendor/` and every forked source is listed here with its
version, licence and origin. `deny.toml` is the machine-checked allowlist; this file is the human record.

## Forked source

| Component | Origin | Licence | Used by | Task |
| --- | --- | --- | --- | --- |
| Sandbox (OS confinement) | codex (`github.com/openai/codex`), commit `aa5f492031f7edb75a40973d19eda8efb9512c61` (ADR-021 D30) | Apache-2.0 | `laris-sandbox` | T134 (measured, planned), T135 (Linux, macOS and Windows parts rewritten after the codex approach; macOS and Windows never run, T214) |
| shadcn/ui components and mobile hook | shadcn registry, generated with CLI 4.23.0 | [MIT](apps/web/components/ui/LICENSE.md) | `apps/web` | T258 |

Files planned for the fork (T134, `docs/architecture/SANDBOX_MEASUREMENT.md`). T135 copied only `seatbelt_base_policy.sbpl` and `seatbelt_network_policy.sbpl` (headers kept, origin noted, in `crates/laris-sandbox/src/macos/`); the bubblewrap, seccomp, Landlock and Seatbelt generator code was rewritten against the LARIS `Policy` after the codex approach, with an attribution note in each file, not copied; no Windows file is taken yet; each copied file keeps
its Apache-2.0 header and gets a "Modified by LARIS" note plus the origin commit). Cut approved by the owner on 2026-11-18 (option A):

- `codex-rs/linux-sandbox/src/`: `bwrap.rs`, `linux_run_main.rs`, `seccomp.rs`, `launcher.rs`, `fd_mount.rs`,
  `daemon_mounts.rs`, `exec_util.rs`, `wslg.rs`, `lib.rs`, `main.rs` (`bundled_bwrap.rs` is not forked).
- `codex-rs/sandboxing/src/`: `landlock.rs`, `bwrap.rs`, `launch.rs`, `spawn.rs`, `linux_pid_namespace.rs`,
  `policy_transforms.rs`, `manager.rs`, `denial.rs`, `violation.rs`, `seatbelt.rs`, `seatbelt_scratch.rs`,
  `seatbelt_daemon.rs`, `seatbelt_*.sbpl`, `lib.rs`. To modify: replace `codex-protocol` types with the `laris-sandbox`
  policy type; remove `codex-network-proxy`, `codex-otel`, `codex-uds`, `codex-mxc-sandbox` and `codex-utils-pty` uses.
- `codex-rs/process-hardening/src/lib.rs`.
- `codex-rs/windows-sandbox-rs/src/` (restricted-token path, option A): `token`, `acl`, `allow`, `cap`, `env`,
  `process`, `desktop`, `winutil`, `path_normalization`, `workspace_acl`, `no_reparse_dir`, `deny_read_*`,
  `spawn_prep`, `resolved_permissions`, `wrapper`, `conpty`, `unified_exec/backends/legacy.rs`. The elevated backend
  (`setup*`, `identity`, `dpapi`, `wfp*`, `elevated/`, `bin/command_runner`) only if the owner chooses option B.
- Not forked: `codex-protocol`, `codex-network-proxy`, `codex-otel`, `codex-mxc-sandbox`, `codex-utils-pty`.

## Vendored crates (approved in T119)

| Crate | Version | Licence | Needed by | Task |
| --- | --- | --- | --- | --- |
| regex | 1.13.1 | MIT OR Apache-2.0 | `xtask` | T121 |
| regex-automata | 0.4.18 | MIT OR Apache-2.0 | regex | T121 |
| regex-syntax | 0.8.11 | MIT OR Apache-2.0 | regex | T121 |
| aho-corasick | 1.1.5 | Unlicense OR MIT | regex | T121 |
| memchr | 2.8.3 | Unlicense OR MIT | regex | T121 |
| serde | 1.0.229 | MIT OR Apache-2.0 | `laris-protocol` | T123 |
| serde_json | 1.0.154 | MIT OR Apache-2.0 | `laris-protocol` | T123 |
| schemars | 1.2.3 | MIT | `laris-protocol` | T123 |
| serde_core, serde_derive, serde_derive_internals | 1.0.229 / 1.0.229 / 0.30.0 | MIT OR Apache-2.0 | serde, schemars | T123 |
| schemars_derive | 1.2.3 | MIT | schemars | T123 |
| syn, quote, proc-macro2, unicode-ident | 3.0.10 / 1.0.47 / 1.0.107 / 1.0.27 | MIT OR Apache-2.0 (unicode-ident also Unicode-3.0) | serde, schemars | T123 |
| ref-cast, ref-cast-impl, dyn-clone | 1.0.27 / 1.0.27 / 1.0.20 | MIT OR Apache-2.0 | schemars | T123 |
| itoa, zmij | 1.0.19 / 1.0.23 | MIT OR Apache-2.0 / MIT | serde_json | T123 |
| axum | 0.8.9 | MIT | `laris-server` (features `http1`, `tokio` only) | T141 |
| axum-core | 0.5.6 | MIT | axum | T141 |
| matchit | 0.8.4 | MIT AND BSD-3-Clause | axum | T141 |
| mime, httpdate | 0.3.18 / 1.0.3 | MIT OR Apache-2.0 | axum, hyper | T141 |
| errno, signal-hook-registry | 0.3.15 / 1.4.8 | MIT OR Apache-2.0 | tokio (`signal`) | T141 |
| hyper, hyper-util | already vendored (T128) | MIT | `laris-server` uses them directly for the connection loop (header timeout); owner confirmed 2026-11-18 | T141 |
| sqlx | 0.8.6 | MIT OR Apache-2.0 | `laris-server` storage (features `runtime-tokio`, `postgres`; no TLS, no macros, no migrate) | T142 |
| sqlx-core, sqlx-postgres | 0.8.6 | MIT OR Apache-2.0 | sqlx | T142 |
| md-5, hkdf, rand 0.8.8, rand_chacha, rand_core 0.6.4, ppv-lite86, zerocopy | 0.10.6 / 0.12.4 / 0.8.8 / 0.3.1 / 0.6.4 / 0.2.21 / 0.8.63 | MIT OR Apache-2.0 (zerocopy also BSD-2-Clause) | sqlx-postgres (SCRAM login) | T142 |
| whoami, etcetera, home, libredox, redox_syscall, wasite, stringprep, unicode-bidi, unicode-normalization, unicode-properties, tinyvec | various | MIT OR Apache-2.0 (whoami also BSL-1.0) | sqlx-postgres (user name, password file, SASLprep) | T142 |
| atoi, byteorder, crc, crc-catalog, dotenvy, either, hex, indexmap, equivalent, num-traits, autocfg, allocator-api2 | various | MIT OR Apache-2.0 (atoi, dotenvy MIT) | sqlx-core | T142 |
| parking_lot, parking_lot_core, lock_api, scopeguard, parking, event-listener, futures-intrusive, crossbeam-queue, crossbeam-utils, tokio-stream, tracing-attributes, plain | various | MIT OR Apache-2.0 | sqlx-core (pool, listeners) | T142 |
| landlock | 0.4.7 | MIT OR Apache-2.0 | `laris-sandbox` (Linux) | T135 |
| seccompiler | 0.5.0 | Apache-2.0 OR BSD-3-Clause | `laris-sandbox` (Linux) | T135 |
| rustix | 1.1.6 | Apache-2.0 WITH LLVM-exception OR Apache-2.0 OR MIT | `laris-sandbox` (Linux, `no_new_privs`) | T135 |
| enumflags2, enumflags2_derive | 0.7.12 | MIT OR Apache-2.0 | landlock | T135 |
| linux-raw-sys | 0.12.1 | Apache-2.0 WITH LLVM-exception OR Apache-2.0 OR MIT | rustix | T135 |
| syn (second version) | 2.0.119 | MIT OR Apache-2.0 | enumflags2_derive (the workspace uses syn 3) | T135 |
| toml, toml_datetime, toml_parser, serde_spanned, winnow | 0.9.12, 0.7.5, 1.1.5, 1.1.3, 0.7.15 | MIT OR Apache-2.0 | `laris-server` (the policy files of `.laris/`) | T146 |
| crossterm | 0.29.0 | MIT | `laris-tui` (raw mode, key and paste input; default features) | T158 |
| crossterm_winapi, winapi and its two import crates | 0.9.1 / 0.3.9 / 0.4.0 | MIT; MIT OR Apache-2.0 | crossterm (Windows console) | T158 |
| derive_more, derive_more-impl, convert_case, unicode-segmentation | 2.1.1 / 2.1.1 / 0.10.0 / 1.13.3 | MIT; MIT OR Apache-2.0 | crossterm | T158 |
| signal-hook, signal-hook-mio | 0.3.18 / 0.2.5 | MIT OR Apache-2.0 | crossterm (event reader; mio and signal-hook-registry already vendored) | T158 |
| document-features, litrs, rustc_version, semver | 0.2.12 / 1.0.1 / 0.4.1 / 1.0.28 | MIT OR Apache-2.0 | crossterm, derive_more (build time) | T158 |
| ratatui | not vendored | | the T157 core draws its own lines, so ratatui has no use; stays approved in T119 | T158 |

Crates approved in T119 but not yet used are listed in `deny.toml`; each row is added here when its task vendors it.

## Python packages and data of the model image (not vendored)

| Component | Version | Licence | Used by | Task |
| --- | --- | --- | --- | --- |
| SymPy | 1.14.0 | BSD-3-Clause | `laris.model.solver` (`solve_stem`), `laris.research.stem.answers` | T276 (owner approval 2026-11-23) |
| mpmath | 1.3.0 | BSD-3-Clause | SymPy; the solver's independent numeric checks | T276 |
| CIAAW abridged standard atomic weights 2024 | page of 2024-10-23, SHA-256 `f9e95544…31b907d`; extracted table `6019c080…cddb669` | IUPAC CIAAW data, cited as Atomic Weights 2021 (Prohaska et al., Pure Appl. Chem. 94 (2022) 573-600) with the 2024 revisions | `src/laris/model/solver/data/ciaaw-abridged-atomic-weights.tsv` | T276 follow-up (owner approval 2026-11-23) |
| CODATA 2022 fundamental physical constants | NIST ASCII table, last modified 2024-05-07, SHA-256 `77fb90e6…3f67e67` | NIST data, cited as CODATA 2022 (NIST) | `src/laris/model/solver/data/codata-2022-allascii.txt` | T276 (owner approval 2026-11-23) |

## Tools (not vendored)

`cargo-deny` 0.20.2 (CI and local), `cross` and `minisign` (release, ADR-021 section 4), `uv` (Python environment).
