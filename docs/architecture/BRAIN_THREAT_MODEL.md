---
document_id: "DOC-ARCH-BRAIN-THREAT-001"
title: "Threat Model for the System Brain and the Project Vault"
document_type: "architecture"
status: "DRAFT"
version: "0.1.0"
created_at: "2026-11-11"
updated_at: "2026-11-11"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/architecture/AGENT_HARNESS.md"
  - "docs/specifications/OBSIDIAN_VAULT_FORMAT.md"
decision_references:
  - "ADR-014"
change_summary: "Lists assets, attackers, threats, controls and the test that proves each control for the system brain and the project vault."
---

# Threat Model for the System Brain and the Project Vault

## 1. Assets

| Asset | Where | Why it matters |
|---|---|---|
| System brain | `.laris/brain/` | internal reasoning guidance; confidential (rule C-7) |
| Policy files | `LARIS.md`, `.laris/{prompts,rules,workflows}` | define behaviour (rules C, U, T, W) |
| Project vault | `vault/` | the user's notes and the system's memory of the project |
| Credentials | environment, `.env` | must never reach notes, prompts or logs |

## 2. Attackers

- **Hostile document**: ingested text that carries instructions or tries to be written into a note.
- **Hostile note**: a note (edited or synced) that carries instructions for the model.
- **Manipulated model**: a model steered to read, copy or reveal the brain.
- **Curious or compromised tool call**: arguments that traverse paths or abuse write tools.

Out of scope: a person with administrator access to the user's own machine, who can read any local file
(the brain is protected from the agent, not from the machine's owner). Encrypting the brain at rest is
deferred (decision D3).

## 3. Threats, controls and tests

| ID | Threat | Control | Test |
|---|---|---|---|
| TH1 | A file tool reads or lists the brain | deny glob `.laris/brain/**`; brain folder is not in the sandbox roots | `test_brain.py::test_file_tools_cannot_reach_the_brain`, `test_brain_paths_are_not_readable_by_file_tools` |
| TH2 | Path tricks (`..`, symlinks) reach the vault or brain | `resolve_inside` confines writes; deny globs match the resolved path | `test_vault_core.py::test_safe_title_and_path_confinement`, `test_file_tools_cannot_reach_the_brain` |
| TH3 | The brain is edited to steer behaviour | brain files are in `integrity.lock`; a changed file stops the session | `test_brain.py::test_tampering_with_a_brain_note_stops_the_session` |
| TH4 | The agent writes to the brain | `Brain` has no write method; brain tools are read-only; write tools are confined to the output folder and the project vault | `test_brain.py` (no write API), `tools` registry review |
| TH5 | The brain text leaks in an answer | brain bodies feed the leak detector (shingles); excerpts are budgeted and marked internal | `test_brain.py::test_brain_text_counts_as_confidential_for_leak_detection`, `test_turn_budget_is_enforced_and_unknown_ids_fail` |
| TH6 | Brain content is shown to the user as a "trace" | only note titles are emitted as an event; the brief is a hidden harness message; audit stores titles only | `test_project_and_loop.py::test_consult_adds_a_hidden_brief_and_shows_only_titles` |
| TH7 | A document injects instructions into a vault note | injection scan on write; notes made from documents carry `trust: untrusted` | `test_project_and_loop.py::test_injection_in_a_document_is_not_written_as_a_note` |
| TH8 | A secret is written into a note | secrets are redacted before notes are built | `vault/hooks.py` uses `runtime.redactor`; covered by the redactor suite |
| TH9 | A system update destroys a user's edits | managed blocks with hash conflict detection; text outside blocks is never touched | `test_vault_core.py::test_managed_block_updates_and_detects_user_edits`, `test_user_edits_survive_later_updates` |
| TH10 | A learning turns into permanent brain change | learnings go to the project vault or the `_inbox`; the brain changes only through an owner-approved release | `test_project_and_loop.py::test_proposals_stay_in_the_inbox_outside_normal_folders` |
| TH11 | Brain text is sent to an external endpoint | existing egress policy (loopback only unless configured); brain text is only used in local prompts | `test_harness.py` egress tests |
| TH12 | The brain grows into an unreadable mass that costs context | hub tree with depth, width and budget limits enforced by lint and runtime budgets | `test_brain.py::test_shipped_brain_passes_structure_lint`, `test_structure_lint_catches_orphan_wide_hub_missing_summary_and_depth` |

| TH13 | A hostile document plants instructions in a knowledge note that the brain then shows to the model | knowledge notes are untrusted, titles and summaries pass the injection scan before they reach the model, flagged full text is withheld; the core brain is never written | `test_knowledge.py::test_injection_text_in_a_document_title_or_summary_is_not_passed_to_the_model`, `test_save_knowledge_refuses_injection_and_unknown_domain_falls_back`, `test_ingest_adds_knowledge_under_the_matching_domain_and_no_skill` |

## 4. Open work

- Extraction suite (paraphrase, translation, encoding, step-by-step) against the leak guard: task T33.
- Property tests for writer crash safety and 100 rewrites: task T07 follow-up.
