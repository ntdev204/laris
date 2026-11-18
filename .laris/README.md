# `.laris/` — the policy of the LARIS server

The server composes its system prompt, rules, workflows and help text from this folder. The client never receives it.

| Path | Purpose |
|---|---|
| `policy.toml` | Which prompt sections exist, their order, the variables they may use |
| `prompts/` | One Markdown file per prompt section, with `{{variable}}` placeholders |
| `rules/` | Rules by topic, composed into the prompt in file-name order |
| `workflows/` | One TOML file per workflow: phases, allowed tools, step cap, approval, output sections |
| `help.md` | The guide printed by `/how-to-use`, without a model call |
| `integrity.toml` | SHA-256 of every file above; the server refuses to start when one differs |
| `brain/` | The system brain: an Obsidian-format hub tree (`Brain Index` → domain hubs → playbooks → leaves, routes in the index), read by the server only through `use_system_brain`; not covered by the lock, read-only at run time, confidential |
| `skills/`, `vault/` | Not covered by the lock; `vault/` is decided with T148 and `skills/` with the skills task |

Changing the policy: the owner approves, `version` in `policy.toml` goes up, then `laris-server policy lock` writes
`integrity.toml` and `laris-server policy verify` checks it.
