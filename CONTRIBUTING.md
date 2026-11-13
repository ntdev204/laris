# Contributing to LARIS

Thank you for contributing to the Local Agentic Research Intelligence System (LARIS).

To ensure that research provenance, documentation integrity, and local hardware safety are maintained, all contributors (human engineers and AI agents) MUST adhere strictly to the following guidelines.

---

## 1. Non-Negotiable Operational Invariants

1. **Local-First Boundary:** Never introduce mandatory cloud inference APIs or remote endpoints into the core pipeline.
2. **Self-Built Language Foundation ([ADR-002](docs/adr/ADR-002-self-built-language-foundation.md)):** Never introduce pretrained foundation LLMs as foundational dependencies.
3. **Evidence-First Provenance ([ADR-004](docs/adr/ADR-004-evidence-provenance-first-class.md)):** Never write code that generates unanchored claims without `EvidenceCoordinate` references.
4. **Hardware Safety Limits:** Never write code that assumes unbounded VRAM. Active GPU allocations must remain $\le 15.0$ GB on the RTX 5070 Ti.
5. **No Claims Without Benchmarks ([ADR-008](docs/adr/ADR-008-evaluation-before-capability-claims.md)):** Never claim an accuracy or capability advancement without committing reproducible benchmark results.

---

## 1a. Workflow

Every change starts as a GitHub issue (templates in `.github/ISSUE_TEMPLATE/`), then a `feature/<issue-id>-<description>` branch from `develop`, then a PR into `develop` that is squash-merged and its branch deleted. Closing the issue is part of done. Update `CHANGELOG.md` for user-visible changes. Details: [GIT_FLOW](docs/development/GIT_FLOW.md). Security reports: [SECURITY.md](SECURITY.md).

---

## 2. Documentation Governance

- All documentation files MUST adhere to [docs/development/DOCUMENTATION.md](docs/development/DOCUMENTATION.md) and include valid YAML front matter.
- Direct edits to documents marked `FROZEN` are strictly prohibited. Modifications to frozen baselines MUST proceed via a formal Change Request (CR) as specified in [docs/development/DOCUMENTATION.md](docs/development/DOCUMENTATION.md).
- Run `python3 scripts/validate_docs.py` before submitting changes. Zero validation errors are permitted.

---

## 3. Code Standards & Testing

- Strict Git Flow branching, review cycles, and merge policies are defined in [docs/development/GIT_FLOW.md](docs/development/GIT_FLOW.md).
- Python 3.10+ with strict type annotations (`typing`, `dataclasses`, `pydantic`).
- All new features require unit tests in `tests/unit/` or contract tests in `tests/contract/`.
- Local quality gates must pass prior to opening PRs: `pytest`, `ruff check .`, `mypy src`, and `python3 scripts/validate_docs.py`.
