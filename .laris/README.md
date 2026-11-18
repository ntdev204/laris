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
| `skills/`, `brain/`, `vault/` | Not covered by the lock; their format and content are decided with T147 and the skills task |

Changing the policy: the owner approves, `version` in `policy.toml` goes up, then `laris-server policy lock` writes
`integrity.toml` and `laris-server policy verify` checks it.
