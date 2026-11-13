# Third-party components

Skeleton created in T121. Every crate vendored under `vendor/` and every forked source is listed here with its
version, licence and origin. `deny.toml` is the machine-checked allowlist; this file is the human record.

## Forked source

| Component | Origin | Licence | Used by | Task |
| --- | --- | --- | --- | --- |
| Sandbox (OS confinement) | codex, commit `aa5f492` (ADR-021 D30) | Apache-2.0 | `laris-sandbox` | T132 (pending) |

## Vendored crates (approved in T119)

| Crate | Version | Licence | Needed by | Task |
| --- | --- | --- | --- | --- |
| regex | 1.13.1 | MIT OR Apache-2.0 | `xtask` | T121 |
| regex-automata | 0.4.18 | MIT OR Apache-2.0 | regex | T121 |
| regex-syntax | 0.8.11 | MIT OR Apache-2.0 | regex | T121 |
| aho-corasick | 1.1.5 | Unlicense OR MIT | regex | T121 |
| memchr | 2.8.3 | Unlicense OR MIT | regex | T121 |

Crates approved in T119 but not yet used are listed in `deny.toml`; each row is added here when its task vendors it.

## Tools (not vendored)

`cargo-deny` 0.20.2 (CI and local), `cross` and `minisign` (release, ADR-021 section 4), `uv` (Python environment).
