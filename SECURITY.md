# Security Policy

## Reporting a vulnerability

Do not open a public issue for a security problem. Report it privately to the repository owner through GitHub's "Report a vulnerability" (Security tab) or by email to the maintainer listed in the repository profile. Include the affected commit, a description and reproduction steps. Expect an acknowledgement within 7 days.

## Scope

- Local-first boundary: no component may send corpus or user data to external services without an accepted ADR ([ADR-001](docs/adr/ADR-001-local-first-system-boundary.md)).
- Training authorization: neural training must stay behind `src/laris/core/authorization.py` and `LARIS_TRAINING_AUTHORIZED=1`.
- Artifacts: checkpoints are verified by SHA-256 before loading; never load unverified weights.
- Secrets and credentials must not be committed; datasets and model weights are gitignored.

## Supported versions

Only the latest commit on `develop` and the most recent tagged release receive fixes.
