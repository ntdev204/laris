---
document_id: "DOC-ADR-014"
title: "ADR-014: Obsidian-Compatible Project Vault and Protected System Brain"
document_type: "adr"
status: "ACCEPTED"
version: "1.0.0"
created_at: "2026-11-11"
updated_at: "2026-11-11"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/specifications/OBSIDIAN_VAULT_FORMAT.md"
  - "docs/architecture/BRAIN_THREAT_MODEL.md"
  - "docs/architecture/AGENT_HARNESS.md"
decision_references:
  - "ADR-013"
change_summary: "Adopts Obsidian-format vaults as project memory and as a protected hub-tree brain read through navigation tools."
---

# ADR-014: Obsidian-Compatible Project Vault and Protected System Brain

## Metadata
- **ADR ID:** ADR-014
- **Status:** ACCEPTED
- **Date Decided:** 2026-11-11
- **Decision Owner:** project owner (instruction to build the brain on the defaults below)

## 1. Context

The system needs durable memory and a linked body of reasoning guidance. Reading all of it into the model
costs context and tokens, and guidance stored as prompt text is hard to extend. The owner asked for an
Obsidian-based memory and knowledge graph, created in each user's codebase as they work, and for a secure
brain used by the whole system for reasoning.

## 2. Decision

1. Two vaults in the Obsidian file format (plain Markdown, properties, wikilinks): the **project vault**
   `vault/` (user-owned, system-maintained inside managed blocks) and the **system brain** `.laris/brain/`
   (protected, read-only at runtime).
2. The brain is a **hub tree**: root, domain hubs, topic hubs, leaves. It is entered at the root, followed
   parent to child, and opened note by note with budgets; it is never read as a whole.
3. LARIS implements the format itself; no dependency on Obsidian or its CLI.
4. The brain is reached only through `brain_*` tools and a harness consult step; file tools are denied;
   it is covered by the integrity lock and by leak detection.
5. Runtime learnings go to the project vault or to `_inbox/`; the brain changes only by owner-approved
   release.

## 3. Owner decisions D1 to D9

The owner instructed the work to proceed on these defaults (2026-11-11); each remains changeable by a later
ADR.

| ID | Decision |
|---|---|
| D1 | Project vault at `vault/` (visible folder), tracked in Git; Obsidian workspace files ignored |
| D2 | Vault format is Obsidian-compatible Markdown, implemented in `src/vault/` |
| D3 | No encryption at rest in v1 (a new dependency would be needed) |
| D4 | No use of the Obsidian CLI |
| D5 | System brain is shipped in the repository under `.laris/brain/` and locked by `integrity.lock` |
| D6 | System-generated notes are written automatically inside managed blocks; free-form model proposals go to `_inbox/` |
| D7 | Brain notes are written in English; replies follow the configured language |
| D8 | `.laris/memory` migrates into `vault/Memory/` (task T14) |
| D9 | No runtime self-modification of the brain |

## 4. Consequences

- Positive: memory and knowledge are inspectable, linkable and editable by people; the brain costs a few
  hundred tokens per task; the structure is checked by lint.
- Negative: a second format to maintain; a leak guard that blocks verbatim reuse of brain text.
- Validation: `laris brain check`, `tests/unit/vault/`, the threat model tests.
