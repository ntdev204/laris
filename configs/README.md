# LARIS Configuration Directory

Declarative configuration files, organised by function.

| Path | Purpose |
|---|---|
| `default.yaml` | Canonical defaults for `LarisConfig` |
| `stem-benchmarks.json` | STEM benchmark sources (pinned revisions), split seeds, leakage n-gram, equivalence and baseline settings (T275, ADR-026) |

## Guidelines
- Name files by function, never by version or training stage. The self-trained model's configs (encoder, evaluation, data partition) were removed in T233.
- Runtime tuning (agent, context, model API, security, serving, app, prompts) lives in `default.yaml`; override per user or project in `.laris/config.yaml` or with `LARIS_*` variables (`.env.example`).
- Do not store credentials, API keys, or machine-specific absolute paths here.
- Every YAML file must validate against `LarisConfig` (enforced by `tests/contract/test_config_contracts.py`).
