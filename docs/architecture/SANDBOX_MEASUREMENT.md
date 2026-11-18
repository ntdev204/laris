---
document_id: "DOC-ARCH-SANDBOX-001"
title: "Sandbox Measurement: Cutting the codex Sandbox"
document_type: "architecture"
status: "DRAFT"
version: "0.3.0"
created_at: "2026-11-18"
updated_at: "2026-11-18"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: false
related_documents:
  - "docs/adr/ADR-021-rust-generation.md"
  - "docs/architecture/THREAT_MODEL.md"
  - "THIRD_PARTY.md"
decision_references:
  - "ADR-021"
change_summary: "0.2.0: owner decisions recorded (section 10). First version (task T134): measured size of the codex sandbox per platform and a proposed cut, for owner approval."
---

# Sandbox Measurement: Cutting the codex Sandbox

Task T134, requirement SR-H6, decision D30 (fork the sandbox from codex, OS mechanisms only). This is a **measurement
and a proposal**. Nothing has been forked, copied or built yet; T135 does that after the owner approves the cut in
section 6. The foundation model is NOT QUALIFIED; this document makes no claim about it.

## 1. What was measured and how

- Source: `github.com/openai/codex` at commit `aa5f492031f7edb75a40973d19eda8efb9512c61` (2026-11-13), cloned
  read-only into a scratch directory outside the repository. Licence: Apache-2.0 (`LICENSE`); `NOTICE` names only
  Ratatui (MIT) and does not touch the sandbox crates.
- Method: transitive closure of workspace crates from the sandbox crates, following `[dependencies]` and the
  `[target.'cfg(...)'.dependencies]` tables for the platform, then `wc -l` over `src/` (code) and over test files
  (`*_tests.rs`, `tests/`). Comment and blank lines are included, so these are upper bounds on logic.
- Limits: this machine is Linux. macOS and Windows numbers come from reading and counting source, **not from building
  or running it**. The cfg matching is a script heuristic. Nothing was compiled, and the codex toolchain/MSRV against
  our pinned stable Rust was not checked. Treat the cut estimates as ±25%.

## 2. Uncut size (the whole closure)

| Platform | Workspace crates | Code lines | Test lines |
|---|---|---|---|
| Linux (`codex-linux-sandbox` + `codex-sandboxing`) | 30 | 139,763 | 48,668 |
| macOS (`codex-sandboxing`) | 28 | 134,409 | 43,921 |
| Windows (`codex-sandboxing` + `codex-windows-sandbox`) | 28 | 134,409 | 43,921 |

Forking the closure as it is would import about 135k lines, over 100 external crates and an HTTP client, OpenTelemetry,
a SOCKS/HTTP network proxy and the whole `codex-protocol` model. That contradicts D29 (in-house logic on vendored base
crates). The actual confinement code is a small part of it:

| Crate | Code lines | Role |
|---|---|---|
| `codex-sandboxing` | 5,237 | policy transform, launch, Landlock/bwrap/seatbelt glue |
| `codex-linux-sandbox` | 4,991 | bwrap + seccomp helper binary |
| `codex-windows-sandbox` | 25,229 | restricted token, ACLs, elevated users, firewall/WFP, service |
| `codex-process-hardening` | 193 | disable core dumps / ptrace |
| `codex-mxc-sandbox` | 1,005 | Windows MXC backend (needs `mxc-sdk`) |
| **Confinement crates, total** | **36,655** | |
| `codex-protocol` | 29,185 | all codex wire/model types (only a sliver is used) |
| `codex-network-proxy` | 25,666 | managed network proxy |
| `codex-otel` | 6,296 | telemetry |
| `codex-utils-pty` | 6,549 | PTY / process driver |

## 3. Replacing `codex-protocol`

The sandbox crates use `codex-protocol` for one concept: the permission policy. Used items (non-test code):
`FileSystemSandboxPolicy`, `FileSystemSandboxEntry`, `FileSystemPath`, `FileSystemSpecialPath`,
`FileSystemAccessMode`, `NetworkSandboxPolicy`, `PermissionProfile` (+ `AdditionalPermissionProfile`,
`FileSystemPermissions`, `NetworkPermissions`), `WritableRoot`, `ReadDenyMatcher`, `PROTECTED_METADATA_PATH_NAMES`,
`WindowsSandboxLevel`, `ExecToolCallOutput`, and an error type (`CodexErr`/`SandboxErr`). The Windows crate also reads two
`OPENAI_*` environment-variable names from `shell_environment`; those are dropped.

Where they live: `permissions.rs` (2,663 lines, +1,618 in `permissions/`), `models.rs` (4,850), `protocol.rs` (6,950),
`error.rs` (1,073), `config_types.rs` (980). Proposal: do not port them. `laris-sandbox` defines its own small policy
type, with these fields only and no serde wire format of its own:

- readable roots, writable roots, deny-read paths, protected metadata names (`.git`, `.laris`, ...);
- network: on or off (no proxy mode);
- Windows level: `RestrictedToken` or `Elevated` (see section 5);
- a `SandboxError` enum and an exec-output struct (exit status, stdout, stderr, timed out).

Estimate: 400-800 lines of our own code replace about 17k lines of foreign types. The `permissions` semantics worth
keeping (special paths such as "project roots", glob deny-read, protected metadata) are re-implemented against these
types and covered by the T135 tests.

## 4. Proposed cut per platform

Common drops (all platforms): `codex-network-proxy` and every `ManagedNetworkSandboxContext` use (network is a plain
on/off; managed proxy routing is out of scope), `codex-otel`/Statsig, `codex-http-client`, `codex-api`, `codex-client`,
`codex-uds`, `codex-install-context`, `codex-utils-path-uri`, `codex-utils-image`, `codex-utils-stream-parser`,
`codex-websocket-client`, `codex-execpolicy` (command approval is T133, ours), Bazel glue, and `codex-mxc-sandbox` (needs
`mxc-sdk`, a crate outside the T119 list). `codex-utils-pty` is replaced by `std::process` plus a small own PTY/ConPTY
wrapper only where the Bash tool needs a terminal.

### Linux (primary development platform)

| Keep | Lines |
|---|---|
| `linux-sandbox`: `bwrap`, `linux_run_main`, `seccomp`, `launcher`, `bundled_bwrap`, `fd_mount`, `daemon_mounts`, `exec_util`, `wslg`, `lib`, `main` | 3,934 |
| `sandboxing`: `landlock`, `bwrap`, `launch`, `spawn`, `linux_pid_namespace`, `policy_transforms`, `manager`, `denial`, `violation`, `lib` | 3,021 |
| `process-hardening` | 193 |
| **Upper bound** | **7,148** |

Cut: `proxy_routing`, `proxy_lifecycle`, `managed_tcp`, `managed_tcp_dns` (983, all network-proxy coupled),
`bazel_bwrap` (74), `bundled_bwrap` if the owner accepts a system `bwrap` requirement with Landlock fallback (-223).
Expected after trimming `manager` and `policy_transforms` to the own policy type: **about 4-5k lines**.
Approved crates already cover the mechanisms (`landlock`, `seccompiler`); `libc` is already vendored; `rustix` and
`indexmap` would be new (see section 7).

### macOS

| Keep | Lines |
|---|---|
| `sandboxing`: `seatbelt`, `seatbelt_scratch`, `seatbelt_daemon`, four `.sbpl` profiles | 1,525 |
| `sandboxing` shared: `launch`, `spawn`, `policy_transforms`, `manager`, `denial`, `violation`, `lib` | about 2,300 |
| `process-hardening` | 193 |
| **Upper bound** | **about 4,000** |

Cut: the network `.sbpl` branches that depend on the managed proxy. Expected: **about 3k lines**. macOS uses
`sandbox-exec` with generated profiles and needs no extra crate beyond `libc`. Not verified here (no macOS machine).

### Windows (largest cost, owner decision needed)

`codex-windows-sandbox` is 25,229 lines and has two backends:

- **Restricted token** (`WindowsSandboxLevel::RestrictedToken`, the "legacy" path): `CreateRestrictedToken` with
  write-restricting SIDs, ACLs on the allowed roots, private desktop, job object. Files: `token`, `acl`, `allow`, `cap`,
  `env`, `process`, `desktop`, `winutil`, `path_normalization`, `workspace_acl`, `no_reparse_dir`, `deny_read_*`,
  `spawn_prep`, `resolved_permissions`, `wrapper`, `conpty`, `unified_exec/backends/legacy`, and related. About **9-10k
  lines** upper bound.
- **Elevated** (`WindowsSandboxLevel::Elevated`): dedicated sandbox user accounts, DPAPI-stored credentials, Windows
  Firewall and WFP rules, an elevated setup/provisioning service and a command-runner IPC. `setup` (2,757),
  `setup_provisioning` (1,589 + 1,483), `identity`, `dpapi`, `provisioning_client`, `elevated/` (1,077), `wfp*`,
  `uninstall_windows` (532), `bin/command_runner` (885) and others: about **12-13k lines more**.

Finding that constrains the choice: in `unified_exec/backends/legacy.rs` the restricted-token path refuses a
restricted **read-only** policy ("requires the elevated Windows sandbox backend"). So the restricted-token backend
confines **writes** (what SR-H6 acceptance tests: "writes outside allowed roots fail") but cannot hide files from reads.
Network blocking on Windows without the elevated backend also needs separate handling (no firewall rules).

Also cut on Windows: the otel/Statsig hooks inside `setup` and `setup_provisioning` (`codex_otel`), `service_diagnostics`,
`ssh_config_dependencies`, `app_package`/`package_identity` unless needed, and the `codex-windows-sandbox-test-support`
crate. External crates needed: `windows-sys` (approved) with about 30 feature flags, plus `dunce`, `glob`/`globset`
(approved), `rand`; the `windows` 0.58 crate (firewall COM) only for the elevated backend.

## 5. Options for the owner

| Option | Linux | macOS | Windows | Total after cut (estimate) |
|---|---|---|---|---|
| A. Restricted token on Windows (recommended) | 4-5k | 3k | 9-10k | **about 16-18k lines** |
| B. A plus elevated Windows backend | 4-5k | 3k | 22-23k | about 30k lines |
| C. Linux and macOS now, Windows deferred | 4-5k | 3k | 0 | about 7-8k lines (does not meet SR-H6 on Windows) |

Recommendation: **A**. It meets the SR-H6 acceptance (writes outside allowed roots fail on all three platforms), keeps
the fork near 17k lines, and avoids a Windows service, persistent sandbox users and firewall rules that change the user's
machine. Cost of A: no read-hiding and no OS-level network block on Windows; the policy layer (T133) must refuse such
requests there and say so. B can be added later because the backend choice is a level flag, not a redesign.

## 6. Decisions requested

1. Approve the replacement of `codex-protocol` by an own policy type (section 3).
2. Choose the Windows option A, B or C (section 5).
3. Approve the common drops, in particular: no managed network proxy, no `mxc-sandbox`, no bundled `bwrap` (system
   `bwrap` or Landlock fallback on Linux).
4. Approve the new crates in section 7.

## 7. Dependencies outside the T119 approved list

Needed by the cut code and not named in T119 or ADR-021: `libc` (already vendored as a transitive crate), `rustix`,
`dunce`, `which` (path lookup), `indexmap` (Linux), `anyhow` (replace with `thiserror`, our standard, to avoid it),
`rand` (Windows account names, elevated only), `tempfile` (tests only). Each needs the owner's approval before T135
vendors it (AGENTS.md: no new dependencies without approval). `landlock`, `seccompiler`, `windows-sys`, `globset`,
`ignore`, `clap`, `sha2`, `serde`, `serde_json`, `tokio`, `url` are already approved.

## 8. THIRD_PARTY.md and licence handling

`THIRD_PARTY.md` now records the origin, licence and files to modify (the row is `planned`, no file copied yet). For
each forked file T135 keeps the Apache-2.0 header, adds a "Modified by LARIS" note and the origin commit, and ships the
Apache-2.0 text and an attribution notice with the binary. No Apache-2.0 `NOTICE` obligation beyond that arises, since
the codex `NOTICE` names only Ratatui, which is not forked.

## 9. Not verified

- Nothing was compiled; per-platform line counts are source counts, not built-binary sizes.
- macOS and Windows behaviour was not run; the Windows read-only limitation comes from reading one code path.
- The effort to replace the permission types is an estimate until T135 writes them.
- The cut files may still hold references to dropped crates that only appear on compilation.

## 10. Owner decisions (2026-11-18)

1. Own policy type replaces `codex-protocol`: approved.
2. Windows: option A (restricted token only; no read-hiding and no OS network block on Windows, T133 must refuse such
   requests there): approved.
3. Common drops (no managed network proxy, no `mxc-sandbox`, no bundled `bwrap`): approved.
4. New crates `rustix`, `dunce`, `which`, `indexmap`: approved. `rand` and `tempfile` are not approved (elevated
   backend and tests only); `anyhow` is replaced by `thiserror`.

## 11. What T135 built (2026-11-18)

Linux (bubblewrap, seccomp, Landlock fallback) and the `uv` Python environment are built and tested; the macOS
Seatbelt profile is generated and tested as text only; the Windows restricted-token backend is **not built**. The Linux
code was rewritten against the LARIS `Policy` after the codex approach (about 700 lines, not the 4-5k estimated in
section 4, because the proxy, launcher re-exec and WSL parts are gone); only the two `.sbpl` profiles are copied
verbatim. Details and limits: task T135 in `.claude/spec/task/2-system.md`.
