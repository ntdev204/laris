---
document_id: "DOC-SPEC-DEV-002"
title: "LARIS Git Flow, Branch Governance & Review Lifecycle Specification"
document_type: "specification"
status: "APPROVED"
version: "1.0.0"
created_at: "2026-10-15"
updated_at: "2026-10-16"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/development/CODING_STANDARDS.md"
  - "docs/development/DOCUMENTATION.md"
  - "docs/plans/ROADMAP.md"
  - "docs/plans/ROADMAP.md"
decision_references:
  - "ADR-007"
  - "ADR-008"
change_summary: "Formal specification of Git Flow branching model, PR gates, review-repair lifecycle, and solo-maintainer governance."
---

# LARIS Git Flow, Branch Governance & Review Lifecycle Specification

## 1. Overview & Branch Roles

LARIS strictly follows the Git Flow branching model. All code contributions must adhere to the defined branch lifecycle and promotion rules.

### 1.1 Branch Taxonomy
- **`main`**: Production and release-ready branch. Contains only verified, tagged milestones and releases. Never commit directly to `main`.
- **`develop`**: Integration branch for active feature development. Feature branches merge here via approved pull requests. Never commit directly to `develop`.
- **`feature/<issue-id>-<short-description>`**: Dedicated branch for implementing exactly one roadmap subtask. Cut from `develop` and merges back into `develop`.
- **`release/<version>`**: Release preparation branch cut from `develop` when milestone exit criteria pass. Merges into `main` (with release tag) and back into `develop`.
- **`hotfix/<issue-id>-<short-description>`**: Urgent production fixes cut from `main` and merged back into both `main` and `develop`.

---

## 2. Issue-to-PR Traceability & Lifecycle State Machine

Each implementation unit follows a strict deterministic lifecycle:

```
[Issue READY] 
      │
      ▼
[Create feature/<issue-id>-* branch from develop]
      │
      ▼
[Implement changes + tests + docs + CHANGELOG update]
      │
      ▼
[Run all local quality gates: pytest, ruff, mypy, validate_docs]
      │
      ▼
[Push branch & Open PR targeting develop (Closes #ID, Refs #Parent)]
      │
      ▼
[Automated CI checks & Code Review] ◄──────┐
      │                                     │
   Passed? ─── No ──► [Fix on same branch] ─┘
      │
     Yes
      │
      ▼
[Squash & Merge into develop via authorized mechanism]
      │
      ▼
[Verify GitHub merge status & close issue with audit comment]
      │
      ▼
[Advance to next eligible issue in dependency order]
```

### 2.1 One Implementation Unit, One PR
- Every subtask must have its own isolated, focused PR.
- Unrelated tasks must never be bundled into a single PR.
- Parent milestone issues are coordination gates; child tasks must be completed and merged individually.

### 2.2 Rejection & Repair Lifecycle
- If review findings or CI checks identify defects or contract violations, work does NOT abandon the PR.
- The PR remains open.
- Fixes are implemented and tested on the exact same feature branch.
- The updated revision is pushed, and re-review is performed.

---

## 3. Solo-Maintainer Ruleset Policy

The repository is governed by active GitHub Rulesets on `main` and `develop`:
- **Pull Request Required:** Direct pushes to `main` and `develop` are prohibited.
- **Approving Reviews:** Set to 0 to accommodate solo maintainer workflows without requiring synthetic human approvals.
- **Conversation Thread Resolution:** Mandatory before any merge.
- **Branch Protection:** Deletion and force-pushes (`non_fast_forward`) are strictly prohibited.
- **CI Status Checks:** Required checks must pass before merging once registered.
