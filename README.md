# Local Agentic Research Intelligence System (LARIS)

[![Status: Greenfield Baseline (Milestone M0)](https://img.shields.io/badge/status-Milestone%20M0-blue.svg)](file:///home/thientn204/laris/docs/plans/MILESTONES.md)
[![Hardware Target: RTX 5070 Ti 16GB](https://img.shields.io/badge/hardware-RTX%205070%20Ti%2016GB-green.svg)](file:///home/thientn204/laris/docs/architecture/SYSTEM_OVERVIEW.md)
[![License: Internal / Work-in-Progress](https://img.shields.io/badge/license-Proprietary%20%2F%20Internal-lightgrey.svg)](file:///home/thientn204/laris/docs/DOCUMENTATION_STANDARD.md)

**LARIS** is an autonomous, local-first scientific intelligence platform engineered to comprehend natural language, model complex semantic relations, reason over empirical scientific evidence, synthesize knowledge across multiple publications, discover verifiable research gaps, and propose actionable experimental directions.

LARIS is **not** a generic PDF chatbot, not a naive semantic search tool, and not an off-the-shelf RAG pipeline wrapping cloud LLM APIs. It is a ground-up scientific research platform constructed on self-built language foundations, selective compute orchestration, and evidence-first epistemology.

---

## Key Architectural Principles

1. **Self-Built Language Foundation ([ADR-002](file:///home/thientn204/laris/docs/adr/ADR-002-self-built-language-foundation.md)):** Core NLP components (tokenizers, encoders, semantic equivalence, NLI, discourse analyzers) are trained in-house on clean, auditable corpora. No mandatory third-party foundation models.
2. **Language-First, Document-Agnostic ([ADR-003](file:///home/thientn204/laris/docs/adr/ADR-003-language-first-not-pdf-first.md)):** Deep linguistic competence precedes document layout parsing. Operates on canonical `DocumentTree` structures without relying on brittle section titles or keywords.
3. **Evidence-First Epistemology ([ADR-004](file:///home/thientn204/laris/docs/adr/ADR-004-evidence-provenance-first-class.md)):** Fluency is never mistaken for truth. Every claim and conclusion is anchored to physical `EvidenceCoordinate` spans down to page and sentence index.
4. **Selective Loading, Computation & Access ([ADR-005](file:///home/thientn204/laris/docs/adr/ADR-005-selective-loading-computation-access.md)):** Engineered specifically to run within local workstation constraints (NVIDIA RTX 5070 Ti 16GB VRAM, 32GB RAM, Intel i5-14600KF) via dynamic weight staging and modular specialist routing.
5. **Default Output: Structured Research Report ([DOC-SPEC-REP-001](file:///home/thientn204/laris/docs/specifications/REPORT_SPECIFICATION.md)):** Compiles exhaustive, evidence-anchored research reports by default. Academic manuscripts are drafted strictly on-demand.

---

## Repository Structure

```
/
├── README.md                           # Project entry point and overview
├── CHANGELOG.md                        # Versioned change history
├── CONTRIBUTING.md                     # Contributor guidelines and workflow
├── .gitignore                          # Git ignore rules
├── docs/                               # Canonical technical documentation
│   ├── IDEA.md                         # Official System Vision and Principles
│   ├── DOCUMENTATION_STANDARD.md       # Metadata schema and authoring rules
│   ├── DOCUMENT_LIFECYCLE.md           # Lifecycle states, freeze protocol, and CRs
│   ├── DECISION_LOG.md                 # Chronological log of accepted decisions
│   ├── OPEN_QUESTIONS.md               # Active research questions and trade-offs
│   ├── GLOSSARY.md                     # Canonical definitions of system terms
│   ├── architecture/                   # System topology, layers, and data flows
│   ├── specifications/                 # Formal module contracts and data schemas
│   ├── research/                       # Research strategies across capability areas
│   ├── adr/                            # Architecture Decision Records (ADR-001 - 008)
│   ├── plans/                          # Milestones (M0 - M10) and implementation roadmap
│   ├── testing/                        # Testing strategy, benchmark protocols, acceptance
│   └── templates/                      # Document, specification, ADR, and report templates
├── src/                                # Source package
│   └── laris/                          # Core python package skeleton
│       ├── core/                       # Shared schemas, errors, and base interfaces
│       └── layers/                     # Layer boundary implementations (L0 - L11)
├── tests/                              # Test suites
│   ├── unit/                           # Algorithmic and deterministic tests
│   ├── contract/                       # Module interface schema validation
│   ├── integration/                    # Multi-agent workflow integration tests
│   └── documentation/                  # Documentation and governance tests
├── configs/                            # Configuration files and hyperparameter specs
├── scripts/                            # Validation scripts and build tooling
├── data/                               # Local corpus placeholders (gitignored)
└── artifacts/                          # Checkpoints, benchmark reports, and logs (gitignored)
```

---

## Documentation Quickstart

To understand the architecture and design of LARIS, read in the following sequence:

1. [Official System Vision (docs/IDEA.md)](file:///home/thientn204/laris/docs/IDEA.md)
2. [Twelve-Layer Architecture (docs/architecture/LAYER_ARCHITECTURE.md)](file:///home/thientn204/laris/docs/architecture/LAYER_ARCHITECTURE.md)
3. [Evidence Provenance Architecture (docs/architecture/EVIDENCE_AND_PROVENANCE.md)](file:///home/thientn204/laris/docs/architecture/EVIDENCE_AND_PROVENANCE.md)
4. [Accepted ADRs (docs/adr/README.md)](file:///home/thientn204/laris/docs/adr/README.md)
5. [Implementation Roadmap (docs/plans/IMPLEMENTATION_ROADMAP.md)](file:///home/thientn204/laris/docs/plans/IMPLEMENTATION_ROADMAP.md)

---

## Verifying Governance and Documentation Integrity

Run the automated validation tool to verify all document metadata, internal links, and ADR references:

```bash
python3 scripts/validate_docs.py
```
