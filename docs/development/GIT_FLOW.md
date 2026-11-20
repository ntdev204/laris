---
document_id: "DOC-SPEC-DEV-002"
title: "LARIS Git Flow, Branch Governance & Review Lifecycle Specification"
document_type: "specification"
status: "APPROVED"
version: "2.0.0"
created_at: "2026-10-15"
updated_at: "2026-11-20"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/development/DOCUMENTATION.md"
decision_references:
  - "ADR-007"
  - "ADR-008"
change_summary: "Rewritten for generation 2: main and laris-v2, one feature branch per task (ADR-021 D42)."
---

# LARIS Git Flow

## 1. Branches

| Branch | Role |
| :--- | :--- |
| `main` | Released state. Receives `laris-v2` at a release; tags `vX.Y.Z` are cut here. |
| `laris-v2` | Integration. Each finished task is merged here. |
| `feature/Txx-<slug>` | One branch per task, cut from `laris-v2`, one task per session. |

There is no `develop`, `release/*` or `laris-v1` branch.

## 2. Task lifecycle

1. Read `.claude/spec/` (spec, plan, task) and cut `feature/Txx-<slug>` from `laris-v2`.
2. Implement; update spec, plan and task together.
3. Run `cargo fmt --check`, `cargo clippy -D warnings`, `cargo test`, `cargo deny check` and `cargo xtask spec`
   (Python model block: `scripts/verify_model_block.py`; documents: `scripts/validate_docs.py`).
4. Cross-check the task against plan and spec, commit, merge into `laris-v2` and delete the feature branch.

## 3. Release

The owner authorises each push, tag and release (SR-G4). A release merges `laris-v2` into `main`, records the
checklist in the task note, updates `CHANGELOG.md`, and tags `vX.Y.Z` on `main`.
