# `.laris/` — policy and knowledge folder for RAG + Agent

A special folder: protected from the agent's own tools, checked for integrity before each session.

| Path | Purpose | Authority | Agent can read |
|---|---|---|---|
| `prompts/` | System-prompt modules (`manifest.yaml`, `system/*.md`) and runtime messages (`strings.yaml`) | Highest | No |
| `rules/` | Detailed rules by topic (C, U, E, T, O, M, L), loaded after `LARIS.md` | Highest | No |
| `workflows/` | Narrowing procedures: phases, allowed tools, step cap, approval, output sections | Under the user's request | No (rendered into the prompt when invoked) |
| `skills/` | Task knowledge, loaded with `use_skill` or `/<skill>` | Low | Through `use_skill` |
| `skills/corpus-*` | Optional generated corpus skills (off by default; `laris skills sync` or `learning.skill_on_ingest`) | Low | Through `use_skill` |
| `memory/` | Short dated notes, written through `save_memory` after approval | Data | Yes |
| `help/how-to-use.md` | Prepared user guide printed by `/how-to-use` (no model call) | — | Yes |
| `integrity.lock` | SHA-256 of `LARIS.md`, `prompts/`, `rules/`, `workflows/`, `help/` | — | No |
| `config.yaml` | Optional project overrides (never secrets) | Configuration | No |

Change control: owner approval, bump `prompts/manifest.yaml` `version`, `laris harness lock`,
`laris harness verify`, `pytest tests/unit/harness`. A mismatch stops every session (rule G-3).
Commands: `laris harness verify|lock`, `laris workflows list|show|check`, `laris skills list|show|check`.
In chat: `/workflow <name> <request>`, `/workflows`, `/<skill> <request>`.
