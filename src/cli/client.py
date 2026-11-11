"""`laris`: the user's terminal client. It contains no server, policy or training command and
imports none of that code, so the downloadable package can leave it out."""

import sys
from typing import Optional, Sequence

from cli.commands import account, agent, app, learn, skills, vault
from cli.parser import Table, run

COMMANDS: Table = {
    "app": {
        "ingest": ("Add documents to the local workspace", app.COMMANDS["ingest"]),
        "search": ("Search the workspace", app.COMMANDS["search"]),
        "status": ("Show workspace and model status", app.COMMANDS["status"]),
    },
    "agent": {
        "tools": ("List the agent's tools", agent.COMMANDS["tools"]),
        "run": ("Run one task with the agent and print the steps", agent.COMMANDS["run"]),
        "chat": ("Interactive agent session", agent.COMMANDS["chat"]),
        "guide": ("Print the prepared user guide (same as /how-to-use)", agent.COMMANDS["guide"]),
    },
    "skills": {
        "list": ("List available skills", skills.COMMANDS["list"]),
        "show": ("Print one skill's instructions", skills.COMMANDS["show"]),
        "check": ("Validate every SKILL.md", skills.COMMANDS["check"]),
        "lint": ("Completeness and safety lint of one skill", skills.COMMANDS["lint"]),
        "add": ("Install a hand-written skill after lint", skills.COMMANDS["add"]),
        "sync": ("Build knowledge skills for the whole corpus", skills.COMMANDS["sync"]),
    },
    "learn": {
        "stats": ("Show collected fine-tune data counts", learn.COMMANDS["stats"]),
        "export": ("Export collected data as JSONL (no training)", learn.COMMANDS["export"]),
        "purge": ("Delete collected data", learn.COMMANDS["purge"]),
    },
    "account": {
        "login": ("Enter and save your API key", account.COMMANDS["login"]),
        "logout": ("Forget the saved API key", account.COMMANDS["logout"]),
        "whoami": ("Show which private space the key opens", account.COMMANDS["whoami"]),
        "init": ("Create this project's .laris/ folder", account.COMMANDS["init"]),
    },
    "vault": {
        "init": ("Create the project vault in this codebase", vault.VAULT_COMMANDS["init"]),
        "check": ("Lint the project vault", vault.VAULT_COMMANDS["check"]),
        "status": ("Counts per folder and link health", vault.VAULT_COMMANDS["status"]),
        "search": ("Search the notes of the vault (BM25)", vault.VAULT_COMMANDS["search"]),
        "show": ("Print one note with its links", vault.VAULT_COMMANDS["show"]),
        "graph": ("Link graph: statistics or JSON export", vault.VAULT_COMMANDS["graph"]),
        "sync": ("List and adopt hand edits in managed blocks", vault.VAULT_COMMANDS["sync"]),
        "repair": ("Repair the vault, or restore a note", vault.VAULT_COMMANDS["repair"]),
        "propose": ("Queue a learning for review", vault.PROPOSAL_COMMANDS["propose"]),
        "review": ("List pending proposals", vault.PROPOSAL_COMMANDS["review"]),
        "accept": ("Accept a proposal into the vault", vault.PROPOSAL_COMMANDS["accept"]),
        "reject": ("Reject a proposal", vault.PROPOSAL_COMMANDS["reject"]),
        "migrate-memory": (
            "Copy .laris/memory into the vault (reversible)",
            vault.VAULT_COMMANDS["migrate-memory"],
        ),
    },
}


def _version() -> str:
    from importlib import metadata

    try:
        return metadata.version("laris")
    except metadata.PackageNotFoundError:
        return "unknown"


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args in (["--version"], ["-V"]):
        print(f"laris {_version()}")
        return 0

    from cli.bootstrap import ensure_global_home

    ensure_global_home()
    return run(COMMANDS, "laris", argv, interactive=True)


if __name__ == "__main__":
    sys.exit(main())
