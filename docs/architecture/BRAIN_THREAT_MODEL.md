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
| TH1 | A file tool reads or lists the brain | deny glob `.laris/brain/**`; brain folder is not in the sandbox roots | `test_brain.py::test_file_tools_cannot_reach_the_brain`, `test_project_and_loop.py::test_brain_paths_are_not_readable_by_file_tools`, `test_security_suite.py::test_file_and_ingest_tools_cannot_reach_the_brain` |
| TH2 | Path tricks (`..`, symlinks) reach the vault or brain | `resolve_inside` confines writes; deny globs match the resolved path; a symlinked folder or note that leaves the vault is refused or never indexed | `test_vault_core.py::test_safe_title_and_path_confinement`, `test_security_suite.py::test_writer_refuses_a_symlinked_folder_that_leaves_the_vault`, `test_security_suite.py::test_a_symlinked_note_pointing_outside_is_never_indexed` |
| TH3 | The brain is edited to steer behaviour | brain files are in `integrity.lock`; a changed file stops the session | `test_brain.py::test_tampering_with_a_brain_note_stops_the_session` |
| TH4 | The agent writes to the brain | `Brain` has no write method; brain tools are read-only; write tools are confined to the output folder and the project vault; the project vault may not overlap the brain | `test_proposals.py::test_no_runtime_path_writes_to_the_system_brain`, `test_security_suite.py::test_file_and_ingest_tools_cannot_reach_the_brain` |
| TH5 | The brain text leaks in an answer | brain bodies feed the leak detector (shingles) under a memory budget; excerpts are budgeted and marked internal | `test_brain.py::test_brain_text_counts_as_confidential_for_leak_detection`, `test_brain_leak_adversarial.py::test_adversarial_extraction_variants_are_all_caught`, `test_brain_leak_adversarial.py::test_streamed_leak_is_blocked_even_when_split_into_tiny_chunks` |
| TH6 | Brain content is shown to the user as a "trace" | only note titles are emitted as an event; the brief is a hidden harness message; audit stores titles only; answer notes store titles only | `test_project_and_loop.py::test_consult_adds_a_hidden_brief_and_shows_only_titles`, `test_project_lifecycle.py::test_answer_note_stores_the_brain_path_and_links_only_notes_that_exist` |
| TH7 | A document injects instructions into a vault note | injection scan on write; notes made from documents carry `trust: untrusted` | `test_project_and_loop.py::test_injection_in_a_document_is_not_written_as_a_note`, `test_security_suite.py::test_injection_in_a_document_never_becomes_a_trusted_note` |
| TH8 | A secret is written into a note | secrets are redacted before notes are built and by the writer; `vault check` reports any that remain | `test_security_suite.py::test_secrets_are_redacted_in_every_note_path`, `test_vault_phase1.py::test_rate_limit_and_redaction` |
| TH9 | A system update destroys a user's edits | managed blocks with hash conflict detection; backups before every rewrite; text outside blocks is never touched | `test_vault_core.py::test_managed_block_updates_and_detects_user_edits`, `test_sync_repair_ux.py::test_interleaved_user_and_system_edits_never_lose_user_text` |
| TH10 | A learning turns into permanent brain change | learnings go to the `_inbox` and enter the project vault only when accepted; the brain changes only through an owner-approved release | `test_project_and_loop.py::test_proposals_stay_in_the_inbox_outside_normal_folders`, `test_proposals.py::test_accept_moves_into_the_project_vault_and_reject_discards` |
| TH11 | Brain text is sent to an external endpoint | existing egress policy (loopback only unless configured); brain text is only used in local prompts | `test_harness.py::test_egress_only_to_loopback_unless_allowed` |
| TH12 | The brain grows into an unreadable mass that costs context | hub tree with depth, width and budget limits enforced by lint and runtime budgets | `test_brain.py::test_shipped_brain_passes_structure_lint`, `test_brain.py::test_structure_lint_catches_orphan_wide_hub_missing_summary_and_depth` |
| TH13 | A hostile document plants instructions in a knowledge note that the brain then shows to the model | knowledge notes are untrusted, titles and summaries pass the injection scan before they reach the model, flagged full text is withheld; the core brain is never written | `test_knowledge.py::test_injection_text_in_a_document_title_or_summary_is_not_passed_to_the_model`, `test_knowledge.py::test_save_knowledge_refuses_injection_and_unknown_domain_falls_back` |
| TH14 | An unauthenticated or unauthorised caller uses the model server | database keys required (the built-in key is server-only), 401 on wrong, missing or revoked keys, 403 without permission, 429 over quota; digests and encrypted secrets only | `test_server_auth.py::test_server_rejects_missing_and_wrong_keys_and_accepts_each_valid_key`, `test_keys_quota_reasoning.py::test_roles_and_permissions`, `test_encrypted_keys_and_default.py::test_other_keys_can_be_limited_to_addresses` |
| TH15 | The server stores or leaks what users send | the `serving` package imports no data or tool code, writes no files and logs nothing; plain HTTP is refused off loopback | `test_server_auth.py::test_model_server_cannot_touch_user_data_or_tools`, `test_server_auth.py::test_model_server_writes_no_files_and_logs_nothing`, `test_server_auth.py::test_serve_refuses_plain_http_off_loopback_and_half_a_tls_pair` |
| TH16 | A link or embed in a note makes LARIS read a file outside the vault | the index only reads notes inside the vault; links with `..` or absolute paths stay unresolved | `test_security_suite.py::test_links_and_embeds_that_try_to_leave_the_vault_stay_unresolved` |
| TH17 | A YAML bomb in note properties exhausts memory or time | front matter size and depth caps; anchors and aliases are refused before parsing | `test_security_suite.py::test_yaml_bombs_are_rejected_before_they_expand` |
| TH18 | A hostile note, once retrieved, steers the model | `search_vault` results are untrusted data, flagged by the injection scan, never instructions | `test_security_suite.py::test_injection_text_in_a_vault_note_is_flagged_when_the_model_reads_it` |
| TH19 | The model sweeps the whole brain through its tools | per-turn read budget and no repeat of opened ids | `test_security_suite.py::test_bulk_extraction_through_brain_tools_hits_the_turn_budget` |
| TH20 | Model reasoning (which contains users' task text) is taken from the server | reasoning is diverted before any response is built, redacted, stored for the operator only | `test_keys_quota_reasoning.py::test_reasoning_never_reaches_a_client_but_is_kept_for_the_operator`, `test_keys_quota_reasoning.py::test_secrets_are_redacted_before_a_trace_is_stored` |
| TH21 | A stolen database file yields API keys | keys are stored encrypted (AES-GCM) with the master secret kept outside the database | `test_encrypted_keys_and_default.py::test_keys_are_stored_encrypted_and_can_be_revealed`, `test_encrypted_keys_and_default.py::test_secret_box_round_trip_and_tamper_detection` |

Residual risk (accepted): a shingle detector sees words, so a model that translates, paraphrases or
encodes brain text (base64, one letter per line) is not blocked by TH5. The controls that bound this
are the per-turn budget (TH19), the internal marking of excerpts, and that full text is returned only
when explicitly requested.

## 4. Open work

- Paraphrase, translation and encoding of brain text are not detected by the shingle guard (see the
  residual risk above); a semantic guard would need a model and is out of scope until the core model
  is resumed (T39).
- Encrypting the brain at rest stays deferred (decision D3).
