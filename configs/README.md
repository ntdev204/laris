# LARIS Configuration Directory

Declarative configuration files, organised by function.

| Path | Purpose |
|---|---|
| `default.yaml` | Canonical defaults for `LarisConfig` |
| `stem-brain.json` | Main-brain STEM sources (OpenStax pins at CC BY 4.0 commits, CODATA), sections left out, gate thresholds and retrieval k of the snapshot build (T277) |
| `admissible-sources.json` | Source classes a brain-only answer may rest on (textbook, reference table, journal paper: registries, licences, venues, retraction check) read by `laris-brain::certain`, the server decider and `laris-server brain retrieve/certify`; acquisition settings and the approved papers of `scripts/acquire_papers.py` (T285) |
| `stem-benchmarks.json` | STEM benchmark sources (pinned revisions), split seeds, leakage n-gram, equivalence and baseline settings (T275, ADR-026) |

## Guidelines
- Name files by function, never by version or training stage. The self-trained model's configs (encoder, evaluation, data partition) were removed in T233.
- Runtime tuning (agent, context, model API, security, serving, app, prompts) lives in `default.yaml`; override per user or project in `.laris/config.yaml` or with `LARIS_*` variables (`.env.example`).
- Do not store credentials, API keys, or machine-specific absolute paths here.
- Every YAML file must validate against `LarisConfig` (enforced by `tests/contract/test_config_contracts.py`).
