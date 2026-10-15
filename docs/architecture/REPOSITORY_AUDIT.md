---
document_id: "DOC-ARCH-AUDIT-001"
title: "LARIS Repository Discovery and Initial Audit"
document_type: "architecture"
status: "DRAFT"
version: "0.1.0"
created_at: "2026-10-15"
updated_at: "2026-10-15"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/IDEA.md"
  - "docs/DOCUMENTATION_STANDARD.md"
  - "docs/DECISION_LOG.md"
decision_references:
  - "ADR-001"
  - "ADR-002"
change_summary: "Initial repository audit establishing clean-slate baseline."
---

# LARIS Repository Discovery and Initial Audit

## 1. Executive Summary

This document records the discovery findings of the Local Agentic Research Intelligence System (LARIS) workspace at `/home/thientn204/laris` as of October 15, 2026. The repository begins as an empty greenfield project. No legacy codebase, conflicting third-party framework wrappers, or pre-existing dependencies were present prior to the establishment of the documentation and architectural baseline.

## 2. Current Repository State

- **Root Location:** `/home/thientn204/laris`
- **Operating System:** Linux x86_64
- **Runtime Environment:** Python 3.10.12, Git 2.34.1
- **VCS State:** Git initialized on primary branch `main` (`git init && git branch -m main`).
- **Initial Contents:** No files or folders existed prior to the baseline scaffold initialization.
- **Git Status:** Clean, untracked scaffold directories created for documentation, skeleton code, tests, configuration, scripts, data placeholders, and artifacts.

## 3. Reusable Components

- **Existing Code:** None. No legacy source code exists.
- **Existing Documentation:** None prior to this setup.
- **Existing Tests/CI:** None.
- **Third-Party Pretrained Models:** None present. In accordance with architectural principles, none are introduced as foundation dependencies.

## 4. Missing Parts Identified

To fulfill the requirements of Milestone M0 and prepare for Milestone M1, the following elements are required:
1. Complete architectural and research documentation set.
2. Formal documentation standards and freeze lifecycle governance.
3. Architectural Decision Records (ADRs) for all locked architectural choices.
4. Formal module contracts and data schemas defining boundary interfaces for all 12 layers.
5. Minimal Python package skeleton (`src/laris/`) without executing premature model training.
6. Documentation validation tooling (`scripts/validate_docs.py`) to enforce metadata consistency and link integrity.
7. Test scaffolding for unit, integration, contract, and documentation verification.

## 5. Conflicts and Technical Debt

- **Direct Conflicts:** None. No competing architectures or legacy design baggage exist.
- **Technical Debt:** None. Zero legacy debt.
- **Risk of Accidental Debt:** High risk if developers prematurely integrate heavy external deep learning packages (e.g. Hugging Face Transformers, LangChain, LlamaIndex, or cloud APIs) before self-built component contracts and evaluation protocols are finalized.

## 6. Risks During Scaffold Creation

1. **Premature Architectural Lock-In:** Specifying rigid neural layer shapes or parameter counts before empirical evaluation on corpus tokens.
2. **False Completion Illusion:** Marking documents as `FROZEN` or claiming benchmark numbers before actual experiments are executed.
3. **Hardware Overcommitment:** Designing modules under the assumption that multi-billion parameter foundation models can reside simultaneously in GPU memory alongside retrieval indexes and working memory.
4. **Scope Creep into Generic RAG:** Slipping into standard PDF-chunking or vector-similarity search pipelines instead of the required language-first, multi-layer scientific discourse reasoning.

## 7. Explicit Assumptions

- **Target Hardware Envelope:**
  - GPU: NVIDIA GeForce RTX 5070 Ti (16 GB VRAM).
  - System Memory: 32 GB RAM.
  - Processor: Intel Core i5-14600KF.
  - Storage: Fast NVMe SSD for local corpus, embeddings, checkpoints, and expert weights.
- **Execution Paradigm:**
  - Strictly local-first. Cloud inference or external web APIs are prohibited as mandatory architectural dependencies.
  - Tier 1 core language foundation must be self-built; no pretrained foundation LLM is allowed as a foundational crutch.
- **Programming Language & Standards:**
  - Python 3.10+ for core orchestration, contracts, and scripts.
  - Standardized Markdown documentation with YAML front matter metadata.

## 8. Decisions Requiring Project Owner Approval

The following items are flagged for explicit stakeholder/owner review:
1. **Review and Approval of `docs/IDEA.md`:** Formally accepting the vision, 12-layer architecture, and operational boundaries.
2. **Acceptance of Initial ADRs:** Formally validating ADR-001 through ADR-008.
3. **Corpus Sourcing and Licensing Strategy:** Deciding which open scientific repositories (e.g. arXiv open access subsets, PubMed Open Access, open-licensed STEM corpora) will be targeted for Milestone M1.
4. **Tokenization Strategy Approval:** Authorizing proposed candidate algorithms (e.g. custom Byte-level BPE, Unigram LM) to be benchmarked in Milestone M1.
