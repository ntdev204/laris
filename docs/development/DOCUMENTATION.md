---
document_id: "DOC-GOV-DOC-001"
title: "LARIS Documentation Standard and Lifecycle Governance"
document_type: "specification"
status: "DRAFT"
version: "0.2.0"
created_at: "2026-10-15"
updated_at: "2026-10-29"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/GLOSSARY.md"
  - "docs/adr/README.md"
  - "docs/OPEN_QUESTIONS.md"
decision_references:
  - "ADR-007"
change_summary: "Condensed to the enforceable rules: metadata schema, writing standard, source-of-truth order and lifecycle."
---

# LARIS Documentation Standard and Lifecycle

How documents are structured, reviewed, frozen and changed. `scripts/validate_docs.py` enforces the metadata, uniqueness, link and ADR-reference rules in CI.

## 1. Principles

- One topic, one document. Link instead of copying; never duplicate a specification.
- Documents describe the repository as it is. Delivered plans, task lists and session notes belong in GitHub issues, PRs and `CHANGELOG.md`, not in `docs/`.
- Every number cites its source or is labeled `[ESTIMATE]` / `[THEORETICAL TARGET]`. Illustrative snippets are prefixed `[EXAMPLE]`.
- Use RFC 2119 keywords (MUST, SHOULD, MAY) for requirements. Separate facts, decisions (backed by an ADR), assumptions, hypotheses and open questions ([OPEN_QUESTIONS](../OPEN_QUESTIONS.md)).
- No unquantified marketing claims; a performance claim needs a metric, a baseline and the benchmark protocol.
- Use the terms defined in [GLOSSARY](../GLOSSARY.md).

## 2. Required Metadata

Every file under `docs/` (except `archive/` and `templates/`) starts with this front matter:

```yaml
---
document_id: "DOC-<TYPE>-<ID>"        # unique, matches DOC-[A-Z0-9]+(-[A-Z0-9]+)*
title: "<title>"
document_type: "idea | architecture | specification | adr | plan | research | test | report"
status: "DRAFT | IN_REVIEW | APPROVED | FROZEN | DEPRECATED"
version: "X.Y.Z"                      # semantic version of the content
created_at: "YYYY-MM-DD"
updated_at: "YYYY-MM-DD"
owner: "<role or team>"
reviewers: []
source_of_truth: true | false
related_documents: []                 # repository-relative paths that must exist
decision_references: []               # ADR ids, for example "ADR-001"
change_summary: "<what changed in this version>"
---
```

| Type | Scope |
| :--- | :--- |
| `idea` | Vision, tenets and system boundaries |
| `architecture` | Topology, layers, data flow, routing, storage |
| `specification` | Testable contracts: schemas, errors, invariants, CLI |
| `adr` | One decision: context, alternatives, consequences |
| `plan` | Milestones, dependencies, exit criteria, risks |
| `research` | Method evaluations and experimental notes |
| `test` | Benchmark protocols, metrics, acceptance criteria |
| `report` | Measured findings and audits |

Bump `version` and `updated_at` on every content change (patch: wording; minor: new section or rule; major: changed meaning) and describe it in `change_summary`.

## 3. Source-of-Truth Order

When documents disagree, the higher item wins. Do not pick the newer file by default; fix the lower one in the same change.

1. Accepted ADRs (`docs/adr/`)
2. Architecture overview and vision ([SYSTEM_OVERVIEW](../architecture/SYSTEM_OVERVIEW.md))
3. Specifications (`docs/specifications/`)
4. Architecture documents (`docs/architecture/`)
5. Research and testing (`docs/research/`, `docs/testing/`)
6. Plans (`docs/plans/`); plans never override specifications
7. READMEs: indexes only, no independent requirements

## 4. Lifecycle

```
DRAFT -> IN_REVIEW -> APPROVED -> FROZEN -> DEPRECATED
```

| State | Meaning | Edits |
| :--- | :--- | :--- |
| DRAFT | Being written | Free |
| IN_REVIEW | PR open for review | Reviewer-requested only |
| APPROVED | Merged to `develop` | Normal PR with review |
| FROZEN | Baseline for a release or experiment | Change request only |
| DEPRECATED | Replaced; names its successor | None |

### Freezing

1. Quality gates pass and the document is APPROVED.
2. Set `status: FROZEN` and list the `document_id`, date and tag in the freeze register of [adr/README](../adr/README.md).
3. Tag the release (`vX.Y.Z`) from `main`.

A freeze may be scoped to a section or schema; state the scope in the document.

### Changing a frozen document

Open an issue titled `[CR] <document id>: <change>` with the motivation, affected documents and tests, and the version bump. After approval, bump the major or minor version in the same PR that updates the document and any dependent contract tests.

## 5. Review Checklist

- Front matter valid; `python3 scripts/validate_docs.py` passes.
- Every `related_documents` path and internal link resolves.
- Each decision references an ADR; each metric has a source or label.
- No duplicated content; index in [docs/README.md](../README.md) updated when a file is added or removed.
