# Local Agentic Research Intelligence System (LARIS)

[![Status: Engineering baseline](https://img.shields.io/badge/status-engineering%20baseline-blue.svg)](docs/research/EMPIRICAL_STATUS.md)
[![Hardware Target: RTX 5070 Ti 16GB](https://img.shields.io/badge/hardware-RTX%205070%20Ti%2016GB-green.svg)](docs/architecture/SYSTEM_OVERVIEW.md)
[![License: Internal / Work-in-Progress](https://img.shields.io/badge/license-Proprietary%20%2F%20Internal-lightgrey.svg)](docs/development/DOCUMENTATION.md)

**LARIS** is an autonomous, local-first scientific intelligence platform engineered to comprehend natural language, model complex semantic relations, reason over empirical scientific evidence, synthesize knowledge across multiple publications, discover verifiable research gaps, and propose actionable experimental directions.

LARIS is **not** a generic PDF chatbot, not a naive semantic search tool, and not an off-the-shelf RAG pipeline wrapping cloud LLM APIs. It is a ground-up scientific research platform constructed on self-built language foundations, selective compute orchestration, and evidence-first epistemology.

Current measured readiness: the local compact checkpoint passes baseline-relative validation, but has not met the formal model 01 exit gates. Model 02 scientific-language learning is not implemented; the earlier paper pilot is diagnostic. See the [empirical status report](docs/research/EMPIRICAL_STATUS.md).

---

## Key Architectural Principles

1. **Self-Built Language Foundation ([ADR-002](docs/adr/ADR-002-self-built-language-foundation.md)):** Core NLP components (tokenizers, encoders, semantic equivalence, NLI, discourse analyzers) are trained in-house on clean, auditable corpora. No mandatory third-party foundation models.
2. **Language-First, Document-Agnostic ([ADR-003](docs/adr/ADR-003-language-first-not-pdf-first.md)):** Deep linguistic competence precedes document layout parsing. Operates on canonical `DocumentTree` structures without relying on brittle section titles or keywords.
3. **Evidence-First Epistemology ([ADR-004](docs/adr/ADR-004-evidence-provenance-first-class.md)):** Fluency is never mistaken for truth. Every claim and conclusion is anchored to physical `EvidenceCoordinate` spans down to page and sentence index.
4. **Selective Loading, Computation & Access ([ADR-005](docs/adr/ADR-005-selective-loading-computation-access.md)):** Engineered specifically to run within local workstation constraints (NVIDIA RTX 5070 Ti 16GB VRAM, 32GB RAM, Intel i5-14600KF) via dynamic weight staging and modular specialist routing.
5. **Default Output: Structured Research Report ([DOC-SPEC-REP-001](docs/specifications/REPORT_SPECIFICATION.md)):** Compiles exhaustive, evidence-anchored research reports by default. Academic manuscripts are drafted strictly on-demand.

---

## Repository Structure

```
/
├── README.md, CHANGELOG.md, CONTRIBUTING.md, SECURITY.md
├── docs/            # Architecture, specifications, training runbooks, ADRs and plans
├── experiments/     # Manually invoked diagnostic experiments
├── reports/         # Versioned measurements and verification evidence
├── src/       # Domain packages: language, corpus, retrieval, cli, core, config, ...
├── tests/           # unit/<domain>, contract, integration, cli
├── configs/         # YAML configuration by function (language_encoder, data, evaluation)
├── scripts/         # validate_docs.py and thin wrappers over the laris CLI
├── data/            # Local corpora (gitignored except manifests)
└── artifacts/       # Checkpoints, tokenizer, reports (gitignored)
```

---

## Developer Quickstart

Create and activate the isolated virtual environment `./laris-env/` using `pyproject.toml`:

```bash
# Setup virtual environment and install development dependencies
uv venv ./laris-env --python 3.10
source ./laris-env/bin/activate
uv pip install -e ".[dev]"

# Owner full-suite checks (may contain optimizer-bearing unit tests)
pytest
ruff check .
mypy src
python3 scripts/validate_docs.py   # or: make check
```

Owner-only language-encoder workflow (see [training index](docs/training/README.md) and [CLI reference](docs/development/CLI.md)): `laris-server data acquire`, `laris-server data partition`, `laris-server train tokenizer`, `laris-server train language-encoder`, `laris-server evaluate language-encoder`. Training requires explicit owner authorization.

Current agent preparation checks: `make PY=.venv/bin/python check-no-training`. This deliberately excludes optimizer-bearing tests; agents must not run the full `make check` during this task.

### Engineering Governance & Guidelines
- [Coding Standards & Engineering Principles (docs/development/CODING_STANDARDS.md)](docs/development/CODING_STANDARDS.md)
- [Git Flow & PR Governance (docs/development/GIT_FLOW.md)](docs/development/GIT_FLOW.md)
- [Command-line reference (docs/development/CLI.md)](docs/development/CLI.md)
- [Documentation index (docs/README.md)](docs/README.md)
- [Contributing Guidelines (CONTRIBUTING.md)](CONTRIBUTING.md)

---

## Documentation Quickstart

To understand the architecture and design of LARIS, read in the following sequence:

1. [System Vision and Topology (docs/architecture/SYSTEM_OVERVIEW.md)](docs/architecture/SYSTEM_OVERVIEW.md)
2. [Twelve-Layer Architecture (docs/architecture/LAYER_ARCHITECTURE.md)](docs/architecture/LAYER_ARCHITECTURE.md)
3. [Evidence Provenance Architecture (docs/architecture/EVIDENCE_AND_PROVENANCE.md)](docs/architecture/EVIDENCE_AND_PROVENANCE.md)
4. [Accepted ADRs (docs/adr/README.md)](docs/adr/README.md)
5. [Implementation Roadmap (docs/plans/ROADMAP.md)](docs/plans/ROADMAP.md)

---

## Verifying Governance and Documentation Integrity

Run the automated validation tool to verify all document metadata, internal links, and ADR references:

```bash
python3 scripts/validate_docs.py
```
