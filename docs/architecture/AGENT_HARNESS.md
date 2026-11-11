---
document_id: "DOC-ARCH-HARNESS-001"
title: "LARIS Agent Harness, System Prompt and Confidentiality Architecture"
document_type: "architecture"
status: "DRAFT"
version: "0.1.0"
created_at: "2026-11-11"
updated_at: "2026-11-11"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/architecture/SYSTEM_OVERVIEW.md"
  - "docs/architecture/DATA_FLOW.md"
  - "docs/development/CLI.md"
decision_references:
  - "ADR-001"
  - "ADR-004"
  - "ADR-013"
change_summary: "Defines the shared harness: prompt modules, agent loop, guards, policies and configuration precedence."
---

# LARIS Agent Harness, System Prompt and Confidentiality Architecture

The harness is the single runtime that every front end (the terminal client; the model server only authenticates and infers, see ADR-015) uses to run a model with tools. It turns the project policy (`LARIS.md`), the versioned prompt modules and the configuration into one governed session. No component carries its own prompt text, limits or endpoints.

## 1. Design rules

1. **No hardcoded tunables.** Every limit, path, endpoint, pattern and message lives in `configs/default.yaml`, `.laris/` or the environment. Source code holds only schemas with safe defaults (ADR-001, ADR-013).
2. **Internal policy is confidential.** `LARIS.md`, the prompt modules, configuration, credentials, internal paths and other conversations are never disclosed in any form.
3. **Fail closed.** A missing prompt module, an unknown placeholder, a literal secret in YAML, a non-loopback model API or a leak in output stops the action instead of degrading silently.
4. **Evidence first.** Answers grounded in tool results must cite `[source #rank]` (ADR-004); the verifier asks for one rewrite, then marks the answer uncited.

## 2. Configuration precedence

Later layers win:

| # | Layer | Notes |
|---|-------|-------|
| 1 | Schema defaults | `config/runtime_schemas.py`, `config/schemas.py` |
| 2 | `configs/default.yaml` | Checked in; equals the schema defaults |
| 3 | `~/.laris/config.yaml` | Per user |
| 4 | `<project>/.laris/config.yaml` | Per project |
| 5 | User preferences | `<chat_dir>/settings.json`; only a whitelist (model URL/name, API-key variable name, autocompact, window, threshold, write approval, extra instructions) |
| 6 | `LARIS_*` environment | `__` separates nesting, JSON for lists, e.g. `LARIS_APP__PORT=9000`; `<project>/.env` is loaded first and never overrides real variables |
| 7 | Command-line flags | `--model-api-url`, `--workspace`, ... |

YAML may name an environment variable (`api_key_env`) but never contain a credential; the loader rejects literal secrets. `.env.example` lists the supported variables. Security settings (deny globs, secret patterns, `allow_remote`) are not in the preference whitelist.

## 3. System prompt

`.laris/prompts/manifest.yaml` (version, variables, module order) and `.laris/prompts/system/*.md` form the prompt. The composer:

1. Loads every module and substitutes `{{variable}}` strictly (unknown variable = error).
2. Inserts `LARIS.md`, then every `.laris/rules/*.md` in file order, then the optional `.laris/LARIS.md` and `LARIS.local.md` as `<internal_policy classification="internal" disclose="never">` right after the principles, so policy outranks everything below it.
3. Adds the skills index, memory index, user extra instructions (length-capped, always after policy), date, session id and a per-session canary token.
4. Returns the text with a SHA-256 and version. Audit logs record the hash, never the text.

Authority order (P-1): system prompt and policy, then the user, then skills, then data. Skills, preferences and files may tighten rules but never weaken them (P-2).

## 4. Loop

```
BEGIN -> [COMPACT -> MODEL -> TOOLS -> GUARD]* -> VERIFY -> DONE
```

- **BEGIN** composes the prompt, builds the guard (shingled confidential text and canary) and audit log.
- **COMPACT** estimates tokens; above the threshold, trims old tool output then summarises older turns (model or extractive fallback), never splitting tool-call pairs, archiving originals. On a context-overflow error it compacts once and retries.
- **MODEL** streams through the stream guard (hold-back buffer, leak block, secret redaction).
- **TOOLS** validates arguments against JSON schema, applies the approval policy (`allow`/`ask`/`deny`), per-tool timeouts and call caps, and marks results from documents or OCR as untrusted.
- **GUARD** halts on a repeated identical call, the step ceiling (at most 10), the time budget or a blocked disclosure.
- **VERIFY** enforces citations for grounded answers (one retry).

Statuses: `completed`, `max_steps`, `cyclic`, `timeout`, `provider_error`, `blocked`.

## 5. Confidentiality and injection defences

| Threat | Control |
|--------|---------|
| Prompt or policy extraction | Fixed refusal rule; hashed word shingles of every confidential source and the canary token checked on the stream and the final text; blocked output is replaced by the configured refusal |
| Credential disclosure | Environment values whose names contain configured markers, token regexes and absolute paths are redacted from output, tool results, files written, memory and audit |
| File exfiltration through tools | `security.deny_read_globs` (policy, prompts, `.env`, configs, chat state, `.git`) enforced in the sandbox; reads limited to the project and upload folder; writes only to the output folder or project memory |
| Indirect prompt injection | Tool results from documents are tagged `_trust: untrusted`, scanned with configurable patterns (English and Vietnamese) and flagged to the model; only the user may authorise actions (U-3) |
| Remote leakage | The model API must be loopback unless `model_api.allow_remote` is true |
| Error leakage | Tool errors and statuses carry project-relative paths only; no stack traces |
| Over-collection | Audit logs hold event type, tool name, status, sizes and hashes, never message content |

These controls reduce risk; they do not make disclosure impossible for a model that is not trusted, which is why the policy is also enforced outside the model.

## 6. The `.laris/` folder, workflows and integrity

`.laris/` holds everything that steers RAG and the agent (see `.laris/README.md`). `prompts/`, `rules/`, `workflows/`, `integrity.lock` and `config*.yaml` are on the read deny-list, so no tool can read, list or describe them.

**Integrity (G-3).** `integrity.lock` stores a SHA-256 for `LARIS.md` and every file under `prompts/`, `rules/` and `workflows/`. Each runtime start compares them: a changed, added, removed or missing file stops the session (`prompts.integrity: enforce`, default; `warn` and `off` are owner-only configuration). `laris harness verify` also composes the prompt and cross-checks workflows against the real tool registry; `laris harness lock` refreshes the lock after an approved change. A policy that exceeds `prompts.max_instruction_chars` fails instead of being truncated.

**Workflows (W-1..W-4).** `.laris/workflows/<name>.yaml` defines ordered phases and limits the harness enforces: `allowed_tools` (other tools are hidden from the model and blocked), `max_steps` (at most the global ceiling of 10), `approval` (`ask` or `deny` can only tighten the user's mode), `require_citations`, and `output_sections` (missing sections trigger one rewrite, then a warning). A user starts one with `/workflow <name> <request>`; the model cannot start or widen a workflow. Shipped: `grounded-qa`, `document-intake`, `evidence-review`, `research-brief`. Audit records name the workflow, not the task.

## 7. Skills and memory

Skills live in `.laris/skills/<name>/SKILL.md` (front-matter `name`, `description`); roots come from `prompts.skill_roots`. The model loads one with `use_skill`; users type `/<skill> request`. Memory notes in `.laris/memory/` are written through `save_memory` after approval, are redacted and listed by name in the prompt.

## 8. Learning from use: RAG skills and fine-tune data

**New knowledge joins the brain by domain; skills only on request.** Every ingestion path (`laris app ingest`, the `ingest_path` tool, chat uploads) goes through `SearchService.ingest`, whose hook writes a Source note and a Knowledge note under `vault/Knowledge/<domain hub>/` (domain by keyword routing over the brain hubs, `General` when none matches). The notes carry key terms, claims, methods, datasets and metrics extracted from the document, are marked `trust: untrusted`, and are listed beside the matching hub by the brain tools; the protected core brain is never modified. `save_knowledge` (approval required) adds knowledge the user teaches. Skills are no longer generated on ingestion (`learning.skill_on_ingest` defaults to false; `laris skills sync` still builds optional `corpus-*` skills).

**New skills from the user.** The `skill-authoring` skill guides the model to gather the missing facts and draft a skill; the `save_skill` tool (approval required) installs it only after the same lint used by `laris skills lint|add`: front matter, "Use when" description, required sections (`learning.skill_required_sections`), size, no instruction-override wording, no credentials and no references to policy or secret files.

**Useful interactions are kept for later fine-tuning.** After each finished turn the collector applies a quality gate and writes local JSONL under `learning.dir` (default `artifacts/finetune`, git-ignored and on the tool deny-list): `sft.jsonl` (chat turns without the system prompt), `retrieval.jsonl` (query with cited positives and uncited negatives, for retrieval training) and `preference.jsonl` (draft rejected by the verifier vs the final answer). A turn is kept only when it completed, passed citation verification, produced no leak or credential and no injection flag, and is long enough; duplicates are skipped. The user can rate an answer (web buttons, `/rate up|down`), disliked turns are excluded from export, and collection can be switched off (`learning.enabled`, the settings checkbox, `/learn on|off`). `laris learn stats|export|purge` manages the data. **Nothing is trained by the system**; export writes JSONL plus a manifest with a hash for the owner to use later.

## 9. Change control

`LARIS.md` and the protected parts of `.laris/` (`prompts/`, `rules/`, `workflows/`) are versioned in Git. A change needs owner approval, a manifest `version` bump, `laris harness lock` and a passing run of `tests/unit/harness`. Prompt behaviour is tested, not trusted: tests cover precedence, strict placeholders, shingle and canary leaks, stream splitting, redaction, deny globs, egress, verifier retry, audit content and the absence of hardcoded endpoints.

## Project vault and system brain

Two Obsidian-format vaults support the harness (see ADR-014 and `docs/specifications/OBSIDIAN_VAULT_FORMAT.md`).

- **Project vault** (`vault/`, configuration `vault.*`): created on first work, then extended after every
  ingest and verified chat turn with linked Source, Concept, Question and Session notes. LARIS writes only
  inside managed blocks and never overwrites a person's edit (conflict is reported). Notes made from
  documents carry `trust: untrusted` and pass the injection scan.
- **System brain** (`.laris/brain/`, configuration `brain.*`, `prompts.brain_dir`): a hub tree (root, domain hub, topic
  hub, leaf) that is never read whole. The loop's consult step routes the task to a domain hub by workflow
  name or keywords and adds a short hidden brief; the model can navigate further with `brain_open`,
  `brain_neighbors`, `brain_route`, `brain_search`. Output is marked internal, redacted, and budgeted per turn.
  The brain is in `integrity.lock`, denied to file tools, counted as confidential by the leak guard, and has
  no write path at runtime. Threats and tests: `docs/architecture/BRAIN_THREAT_MODEL.md`. How the vault, the brain and the analytics fit together: `docs/architecture/BRAIN_AND_VAULT.md`.
