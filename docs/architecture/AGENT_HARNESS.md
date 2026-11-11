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

The harness is the single runtime that every front end (command line, web UI, model server) uses to run a model with tools. It turns the project policy (`LARIS.md`), the versioned prompt modules and the configuration into one governed session. No component carries its own prompt text, limits or endpoints.

## 1. Design rules

1. **No hardcoded tunables.** Every limit, path, endpoint, pattern and message lives in `configs/default.yaml`, `configs/prompts/` or the environment. Source code holds only schemas with safe defaults (ADR-001, ADR-013).
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

`configs/prompts/manifest.yaml` (version, variables, module order) and `configs/prompts/system/*.md` form the prompt. The composer:

1. Loads every module and substitutes `{{variable}}` strictly (unknown variable = error).
2. Inserts `LARIS.md` and the optional `LARIS.local.md` as `<internal_policy classification="internal" disclose="never">` right after the principles, so policy outranks everything below it.
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

## 6. Skills and memory

Skills live in `.laris/skills/<name>/SKILL.md` (front-matter `name`, `description`); roots come from `prompts.skill_roots`. The model loads one with `use_skill`; users type `/<skill> request`. Memory notes in `.laris/memory/` are written through `save_memory` after approval, are redacted and listed by name in the prompt.

## 7. Change control

`LARIS.md` and `configs/prompts/` are versioned in Git. A change needs owner approval, a manifest `version` bump and a passing run of `tests/unit/harness`. Prompt behaviour is tested, not trusted: tests cover precedence, strict placeholders, shingle and canary leaks, stream splitting, redaction, deny globs, egress, verifier retry, audit content and the absence of hardcoded endpoints.
