---
document_id: "DOC-GUIDE-DISTRIBUTION-001"
title: "Installing laris and making a release"
document_type: "architecture"
status: "DRAFT"
version: "0.1.0"
created_at: "2026-11-19"
updated_at: "2026-11-19"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/guide/CLIENT.md"
  - "docs/adr/ADR-021-rust-generation.md"
decision_references:
  - "ADR-021"
change_summary: "Installation and release steps of the Rust generation."
---

# Installing laris and making a release

## For users

One command per platform. `<release address>` is the address the release was rendered for.

```sh
# Linux and macOS
curl -fsSL <release address>/latest/install.sh | sh
# Windows (PowerShell)
irm <release address>/latest/install.ps1 | iex
# anywhere with Node 18 or later
npm install -g laris
```

Every route does the same checks before it puts anything in place: it downloads `SHA256SUMS`, `SHA256SUMS.sig` and the
archive for this machine; it checks the signature of `SHA256SUMS` against the public key written into the script (or
the npm package); it checks the archive against its line in the signed list; it checks that the archive holds one file,
`laris`. If any check fails it stops with the reason and installs nothing.

| Variable | Meaning |
|---|---|
| `LARIS_VERSION` | Release to install (default `latest`; the npm package uses its own version). |
| `LARIS_INSTALL_DIR` | Where the binary goes (`~/.local/bin`; on Windows `%LOCALAPPDATA%\Programs\laris`). |
| `LARIS_RELEASE_URL` | Another release address (a mirror). The signature is still checked against the built-in key. |

`install.sh` needs `openssl`, `tar` and `curl` or `wget`. `laris --version` shows the installed version.

## For the owner: making a release

Targets: `x86_64-unknown-linux-musl`, `aarch64-unknown-linux-musl`, `x86_64-apple-darwin`, `aarch64-apple-darwin`,
`x86_64-pc-windows-msvc`. The release profile uses fat LTO, one codegen unit and stripped symbols.

1. Once: `cargo xtask dist keygen --out ~/.laris-release` makes the ECDSA P-256 key pair. Keep `release.key` outside the
   repository (it is in `.gitignore`); the public key is not secret.
2. Build each target (the workflow `release-build` does it: `cross` for the static Linux targets, native runners for
   macOS and Windows) and package it: `cargo xtask dist package --target T --bin PATH --out out`.
3. `cargo xtask dist manifest --dir out` writes `SHA256SUMS` and `size-report.md`.
4. `LARIS_RELEASE_KEY=~/.laris-release/release.key cargo xtask dist sign --dir out` writes `SHA256SUMS.sig`.
5. `cargo xtask dist verify --dir out --pubkey ~/.laris-release/release.pub` checks what was made, as an installer would.
6. `cargo xtask dist scripts --dir out --url https://<release address> --pubkey ~/.laris-release/release.pub` renders
   `install.sh`, `install.ps1` and the npm package (`out/npm`; `npm publish` stays with the owner).
7. Upload `out` as `<release address>/<version>/` and copy it to `latest/`. With GitHub as the host, the workflow does this
   itself when run with `publish` (owner's order, 2026-11-20): it creates the release named by the version (no `v`, so that
   `https://github.com/<owner>/<repo>/releases/download/<version>/<file>` is the layout above; set `LARIS_RELEASE_URL` to
   `https://github.com/<owner>/<repo>/releases/download`) and runs `npm publish` with the secret `NPM_TOKEN`. `latest` is not a
   release there: the installers need `LARIS_VERSION=<version>`; the npm package pins its own version.

The release address is never in the sources: it is an argument or `LARIS_RELEASE_URL` at this step.

## What is checked, and what is not

- Tested here with a fake binary and a real release build on Linux: good install, a changed archive, a changed list, a
  changed or foreign signature, an unlisted archive, an archive with extra files, a missing or plain-`http` address
  (`xtask/tests/dist.rs`); the same refusals for the npm wrapper.
- NOT tested on a clean machine: macOS, Windows (`install.ps1` was written for Windows PowerShell 5.1 and 7 and has
  not been run), `aarch64` Linux, and the `cross` and native release builds. The static musl binaries are built by CI
  only; the one built here is `x86_64-unknown-linux-gnu`.
- No macOS notarisation and no Windows Authenticode signature: the owner holds no certificates yet (ADR-021 section 4).
  The first run of an unsigned binary may show a system warning on those platforms.
- The key is a single key with no rotation or revocation scheme; a lost key means a new public key in new scripts.
