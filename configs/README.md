# LARIS Configuration Directory

Declarative configuration files, organised by function.

| Path | Purpose |
|---|---|
| `default.yaml` | Canonical defaults for `LarisConfig` |
| `language_encoder/compact.yaml` | Compact (~110M parameter) language encoder architecture and training |
| `language_encoder/large.yaml` | Large (~513M parameter) language encoder architecture and training |
| `evaluation/language_encoder.yaml` | Acceptance thresholds for `laris evaluate language-encoder` (not a `LarisConfig`) |
| `data/partition.yaml` | Train/val/test ratios, partition seed and leakage settings |

## Guidelines
- Name files by function and size preset, never by version or training stage.
- Do not store credentials, API keys, or machine-specific absolute paths here.
- Every YAML file must validate against `LarisConfig` (enforced by `tests/contract/test_config_contracts.py`).
