---
document_id: "DOC-GUIDE-CLIENT-001"
title: "Using the laris terminal interface"
document_type: "architecture"
status: "DRAFT"
version: "0.1.0"
created_at: "2026-11-19"
updated_at: "2026-11-19"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/development/DOCUMENTATION.md"
decision_references:
  - "ADR-021"
change_summary: "Guide entries for the commands, input forms, approvals and login of the interface (T158)."
---

# The `laris` terminal interface

Installing `laris` (one command per platform) and making a release are described in `DISTRIBUTION.md`.

Run `laris` with no arguments in a terminal. For scripts and pipes use `laris -p` (see `laris -p --help` through the
usage text of the binary). The foundation model behind the system is NOT QUALIFIED: treat answers as leads to check.

## Signing in

On the first start the interface asks for your API key inside a masked form: nothing you type is shown, logged or kept
after it is sent. The key is saved (file mode 0600) only after the server accepts it. A refused key opens the form again
with the reason. `LARIS_API_KEY` in the environment wins over the saved key.

## Keys

| Key | What it does |
| :--- | :--- |
| Enter | Send the message. |
| Shift+Enter, Alt+Enter, Ctrl+J, or `\` then Enter | New line in the input box. |
| Esc | Interrupt the running turn (the turn ends before its next step). |
| Ctrl+C | Clear the box; on an empty box press it twice to leave. |
| Ctrl+D | Leave, when the box is empty. |
| Ctrl+R | Search the history; Ctrl+R again for an older match; Enter uses it; Esc cancels. |
| Tab | Complete `/command` (first word) or `@path`. Suggestions also appear as you type: `/` opens the list of commands and each character narrows it (names that start with the text first, then names that contain it); Tab or the arrows move in the menu, Enter chooses, Esc closes. |
| Shift+Tab | Next permission mode. |
| Ctrl+U, Ctrl+K, Ctrl+W | Delete to the start of the line, to its end, the word before the cursor. |

Typing while the agent works is allowed: the message waits below the conversation, marked `(queued)`, and starts when
the turn before it ends.

## Approvals

A call that changes a file or runs a command asks first. The request shows the tool, its arguments, the reason, the
rule an "always" answer would save and, for a file change, the diff. Choose with the arrows and Enter, or press `y`
(once), `n` or Esc (no), or a number: this once, this session, this project, everywhere. A refusal is final for that
call and the model is told.

## Commands

Type `/` to list them; each character narrows the list. These are built in:

| Command | What it does |
| :--- | :--- |
| `/help` | Show the commands. |
| `/clear` | Clear the screen (the session goes on). |
| `/exit` | Leave. |
| `/mode [auto\|default\|acceptEdits\|plan\|bypass]` | Show or change the permission mode. `auto` (the default) runs changes and commands without asking, except those that fit `permissions.autoAsk` (by default: `sudo`, recursive deletion of `/`, `~` or a parent, `git push`, `git reset --hard`, `git clean`, disk and power commands). `bypass` is refused unless the installation's policy allows it. |
| `/status` | Show the session, server and project. |
| `/usage` | Tokens this session used (prompt, answer, requests), and the key's used, limit and left from the server. |
| `/context` | How full the context window is, with the point where compaction starts. Empty until the first answer. |
| `/model` | The models the server offers. |
| `/config` | The session's server, project, mode, sandbox, context window and session id. |
| `/export [file]` | Save the conversation as Markdown, by default to `.laris/exports/<session>.md` in the project. |
| `/rewind [steps]` | Undo the last file changes the session made (one step by default). |
| `/login` | Enter an API key. |
| `/logout` | Remove the saved API key and sign in again. |

### Custom commands

A Markdown file `commands/<name>.md` in `~/.laris/` or in the project's `.laris/` is the command `/<name>`; a folder
makes a prefix (`review/pr.md` is `/review:pr`). The project's file wins over the home's, and a custom command never
replaces a built-in one. An optional header says `description:`. The body is sent as your message with `$ARGUMENTS`
replaced by everything typed after the name and `$1` to `$9` by its words; a body without a placeholder gets the
arguments added at the end. Files larger than 64 KiB and links are ignored.

## Input forms

| Form | What it does |
| :--- | :--- |
| `@path` | Adds the file (up to 64 KiB, at most 8 per message) or the folder listing to the message. Only what the tools may read: a path outside the project folders and files that hold secrets (`.env` and the like) are left as written. |
| `!command` | Runs the shell command now, shows it as a tool block, and tells the model about it with your next message. It runs the way the `Bash` tool does, in the sandbox when the machine has one. |
| `# note` | Adds `- note` to the project's `.laris/LARIS.md`. |

## Review by the owner

`laris replay FILE` shows a recorded scenario through the interface without a server or a key. The snapshots reviewed
at 60 and 100 columns are under `crates/laris-tui/tests/snapshots/`. The screenshot review on Linux and on Windows is
done by the owner in a real terminal.
