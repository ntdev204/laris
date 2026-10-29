---
document_id: "DOC-ADR-007"
title: "ADR-007: Document Lifecycle Governance, Baseline Freezing, and Scoped Control"
document_type: "adr"
status: "ACCEPTED"
version: "1.0.0"
created_at: "2026-10-15"
updated_at: "2026-10-15"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/architecture/SYSTEM_OVERVIEW.md"
  - "docs/development/DOCUMENTATION.md"
decision_references:
  - "ADR-007"
change_summary: "Formalized document lifecycle management, baseline freeze workflows, and change request procedures."
---

# ADR-007: Document Lifecycle Governance, Baseline Freezing, and Scoped Control

## Metadata
- **ADR ID:** ADR-007
- **Status:** ACCEPTED
- **Date Decided:** 2026-10-15
- **Decision Owner:** LARIS Architecture Team
- **Target Layers:** System-Wide Governance

## 1. Context and Problem Statement
In open-ended AI and research development projects, architectural documents frequently drift from code implementation, specifications are modified ad-hoc without assessing cascading impacts, and automated agents risk modifying baseline requirements without human authorization.

LARIS requires a rigorous, auditable documentation governance process that prevents arbitrary modifications to agreed-upon baselines while still permitting controlled, versioned evolution.

## 2. Decision
1. **Canonical Lifecycle States:** All technical documentation SHALL strictly transition through five formal states: `DRAFT` $\rightarrow$ `IN_REVIEW` $\rightarrow$ `APPROVED` $\rightarrow$ `FROZEN` (or `DEPRECATED`).
2. **Immutable Frozen Baselines:** Once a document is designated as `FROZEN` by the project owner, direct in-place edits are strictly forbidden. Any modification MUST proceed via a formal Change Request (CR) record and trigger a semantic version increment.
3. **Prohibition of Self-Freezing:** Automated agents and developers SHALL NOT mark documents as `APPROVED` or `FROZEN` merely because authoring or code generation has finished. Transition to `APPROVED` or `FROZEN` requires formal stakeholder authorization.
4. **Independent Freeze Scopes:** Freezing SHALL occur across independent functional scopes (Vision Baseline, Architecture Baseline, Contract Baseline, Test Baseline), ensuring that progress in higher layers is not blocked by ongoing iterations in lower layers.
5. **Automated Documentation Gates:** Automated scripts (`scripts/validate_docs.py`) SHALL continuously verify metadata validity, internal link integrity, and immutability of frozen documents.

## 3. Alternatives Considered
1. **Informal Markdown Evolution (Git commit messages only):**
   *Rejected because:* Unauditable semantic shifts occur silently, leading to architectural discrepancies between agents and human engineers.
2. **Monolithic Repository Freeze:**
   *Rejected because:* Halts all documentation updates across the entire project whenever one core contract is frozen.

## 4. Consequences
### 4.1. Positive
- Guarantees that baseline requirements, contracts, and evaluation protocols remain stable and auditable.
- Prevents agents or contributors from silently altering architectural invariants.
- Clear historical audit trail for every architectural evolution.

### 4.2. Negative & Trade-offs
- Modifying a frozen specification introduces procedural friction requiring a formal Change Request.
- Requires maintaining documentation validation scripts in the CI pipeline.

## 5. Risks and Mitigations
| Risk | Severity | Mitigation Strategy |
| :--- | :--- | :--- |
| Governance overhead slowing early research iteration | Medium | Keep initial documents in `DRAFT` or `IN_REVIEW` until stability is empirically demonstrated; freeze only true baselines. |
| Inadvertent editing of frozen files | High | Enforce pre-commit hooks and validation scripts that detect checksum changes on files marked `FROZEN`. |

## 6. Validation and Acceptance Criteria
- [ ] `scripts/validate_docs.py` verifies all document metadata and flags any modification to files marked `FROZEN` lacking a Change Request.
- [ ] Document lifecycle states in all YAML front matter blocks match allowed canonical enums.
