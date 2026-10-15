# Contributing to LARIS

Thank you for contributing to the Local Agentic Research Intelligence System (LARIS).

To ensure that research provenance, documentation integrity, and local hardware safety are maintained, all contributors (human engineers and AI agents) MUST adhere strictly to the following guidelines.

---

## 1. Non-Negotiable Operational Invariants

1. **Local-First Boundary ([ADR-001](file:///home/thientn204/laris/docs/adr/ADR-001-local-first-system-boundary.md)):** Never introduce mandatory cloud inference APIs or remote endpoints into the core pipeline.
2. **Self-Built Language Foundation ([ADR-002](file:///home/thientn204/laris/docs/adr/ADR-002-self-built-language-foundation.md)):** Never introduce pretrained foundation LLMs as foundational dependencies.
3. **Evidence-First Provenance ([ADR-004](file:///home/thientn204/laris/docs/adr/ADR-004-evidence-provenance-first-class.md)):** Never write code that generates unanchored claims without `EvidenceCoordinate` references.
4. **Hardware Safety Limits ([ADR-005](file:///home/thientn204/laris/docs/adr/ADR-005-selective-loading-computation-access.md)):** Never write code that assumes unbounded VRAM. Active GPU allocations must remain $\le 15.0$ GB on the RTX 5070 Ti.
5. **No Claims Without Benchmarks ([ADR-008](file:///home/thientn204/laris/docs/adr/ADR-008-evaluation-before-capability-claims.md)):** Never claim an accuracy or capability advancement without committing reproducible benchmark results.

---

## 2. Documentation Governance

- All documentation files MUST adhere to [docs/DOCUMENTATION_STANDARD.md](file:///home/thientn204/laris/docs/DOCUMENTATION_STANDARD.md) and include valid YAML front matter.
- Direct edits to documents marked `FROZEN` are strictly prohibited. Modifications to frozen baselines MUST proceed via a formal Change Request (CR) as specified in [docs/DOCUMENT_LIFECYCLE.md](file:///home/thientn204/laris/docs/DOCUMENT_LIFECYCLE.md).
- Run `python3 scripts/validate_docs.py` before submitting changes. Zero validation errors are permitted.

---

## 3. Code Standards & Testing

- Python 3.10+ with strict type annotations (`typing`, `dataclasses`, `pydantic`).
- Code must reside within `src/laris/` adhering to layer modularity.
- All new features require unit tests in `tests/unit/` or contract tests in `tests/contract/`.
