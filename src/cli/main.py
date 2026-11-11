"""`laris` command-line entry point.

Command tree (each leaf maps to a module in `cli.commands`):

    laris data acquire             download and verify datasets, update the manifest
    laris data partition           physically split raw datasets into train/val/test
    laris data check               verify processed splits, manifest and sentencepiece
    laris train tokenizer          fit the SentencePiece tokenizer
    laris train language-encoder   train (or profile) the multi-task language encoder
    laris evaluate language-encoder   score a checkpoint on the val/test split vs baselines
    laris evaluate calibrate       ratchet acceptance thresholds up from passing val reports
    laris app ingest|index|search|ask|status   local document store and search
    laris login|logout|whoami        API key: each key opens its own private conversations
    laris [--resume [ID]]            open the terminal chat (pick a saved session with --resume)
    laris agent tools|run|chat       tool-using assistant (offline planner or model API)
    laris skills list|show|check     inspect and validate .laris/skills
    laris skills add|lint|sync       install, lint or build knowledge skills
    laris learn stats|export|purge   locally collected fine-tune data (never trains)
    laris workflows list|show|check  inspect and validate .laris/workflows
    laris vault init|check|status    project vault (Obsidian-format memory in your codebase)
    laris brain check|tree|route     inspect the protected system brain (hub tree)
    laris harness verify|lock        policy integrity (LARIS.md, prompts, rules, workflows)
    laris model serve                OpenAI-compatible model API (placeholder backend for now)
    laris infer fill-mask|nli|paraphrase|similarity|qa|embed   single-example predictions
"""

import argparse
import sys
from typing import Any, Callable, Dict, Optional, Sequence, Tuple

from cli.commands import (
    account,
    agent,
    app,
    calibrate,
    check,
    evaluate,
    infer,
    keys,
    language_encoder,
    learn,
    model,
    partition,
    policy,
    readiness,
    skills,
    suite,
    tokenizer,
    vault,
)
from cli.parser import build_parser_for, interactive_default, run  # noqa: F401
from corpus.acquisition import runner as acquisition

Handler = Callable[[argparse.Namespace], int]

COMMANDS: Dict[str, Dict[str, Tuple[str, Any]]] = {
    "data": {
        "acquire": ("Download and verify datasets", acquisition),
        "partition": ("Physically partition raw datasets (zero training)", partition),
        "check": ("Verify processed data and tooling before training", check),
    },
    "train": {
        "tokenizer": ("Fit the SentencePiece tokenizer", tokenizer),
        "language-encoder": ("Train or profile the language encoder", language_encoder),
    },
    "evaluate": {
        "readiness": ("Audit existing reports against formal stage gates (no model)", readiness),
        "language-encoder": ("Score a checkpoint on the val/test split", evaluate),
        "calibrate": ("Tighten thresholds from measured val reports", calibrate),
        "suite": ("Model-free suites (retrieval, citation, extraction, leak, ...)", suite),
    },
    "app": {
        "ingest": ("Add documents to the local workspace", app.COMMANDS["ingest"]),
        "index": ("Embed passages with a checkpoint (inference only)", app.COMMANDS["index"]),
        "search": ("Search the workspace", app.COMMANDS["search"]),
        "ask": ("Extractive answer with source passages", app.COMMANDS["ask"]),
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
    "workflows": {
        "list": ("List workflows", policy.WORKFLOW_COMMANDS["list"]),
        "show": ("Print one workflow's phases and limits", policy.WORKFLOW_COMMANDS["show"]),
        "check": ("Validate workflows against tools and limits", policy.WORKFLOW_COMMANDS["check"]),
    },
    "harness": {
        "verify": (
            "Verify policy integrity, prompts and workflows",
            policy.HARNESS_COMMANDS["verify"],
        ),
        "lock": (
            "Refresh integrity.lock after an approved policy change",
            policy.HARNESS_COMMANDS["lock"],
        ),
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
    "brain": {
        "check": ("Lint the system brain structure", vault.BRAIN_COMMANDS["check"]),
        "tree": ("Print the brain hub tree (titles only)", vault.BRAIN_COMMANDS["tree"]),
        "route": ("Show which hub a task routes to", vault.BRAIN_COMMANDS["route"]),
        "propose": ("Queue a learning for review", vault.PROPOSAL_COMMANDS["propose"]),
        "review": ("List pending proposals", vault.PROPOSAL_COMMANDS["review"]),
        "accept": ("Accept a proposal into the project vault", vault.PROPOSAL_COMMANDS["accept"]),
        "reject": ("Reject a proposal", vault.PROPOSAL_COMMANDS["reject"]),
    },
    "keys": {
        "create": (
            "Create an API key (role, token quota or unlimited)",
            keys.KEYS_COMMANDS["create"],
        ),
        "list": ("List keys with status and token use", keys.KEYS_COMMANDS["list"]),
        "show": ("Show one key", keys.KEYS_COMMANDS["show"]),
        "revoke": ("Revoke a key", keys.KEYS_COMMANDS["revoke"]),
        "limit": ("Change or add to a key's token quota", keys.KEYS_COMMANDS["limit"]),
        "roles": ("List roles and their permissions", keys.KEYS_COMMANDS["roles"]),
        "reveal": ("Decrypt and print a stored key (or `default`)", keys.KEYS_COMMANDS["reveal"]),
        "ip": ("Restrict which addresses may use a key", keys.KEYS_COMMANDS["ip"]),
    },
    "tls": {
        "init": ("Create a self-signed TLS certificate for the server", keys.TLS_COMMANDS["init"])
    },
    "usage": {"summary": ("Token use per key", keys.USAGE_COMMANDS["summary"])},
    "reasoning": {
        "list": ("List stored model reasoning (operator only)", keys.REASONING_COMMANDS["list"]),
        "show": ("Print one reasoning trace", keys.REASONING_COMMANDS["show"]),
        "purge": ("Delete old reasoning traces", keys.REASONING_COMMANDS["purge"]),
    },
    "model": {
        "serve": ("Serve the OpenAI-compatible model API", model.COMMANDS["serve"]),
    },
    "infer": {name: (f"Run {name} on a checkpoint", cmd) for name, cmd in infer.COMMANDS.items()},
}


# What the downloadable client contains. Everything else (model serving, policy and brain tools,
# data, training, evaluation) belongs to the server/operator side and is not in the client.
CLIENT_COMMANDS: Dict[str, Optional[frozenset]] = {
    "agent": None,
    "account": None,
    "vault": None,
    "skills": None,
    "learn": None,
    "app": frozenset({"ingest", "search", "status"}),
}


def commands_for(role: str) -> Dict[str, Dict[str, Tuple[str, Any]]]:
    """`client`: the user tool; `server`: operator tools; `all`: both (development)."""
    if role == "all":
        return COMMANDS
    chosen: Dict[str, Dict[str, Tuple[str, Any]]] = {}
    for group, commands in COMMANDS.items():
        in_client = group in CLIENT_COMMANDS
        allowed = CLIENT_COMMANDS.get(group)  # None = the whole group
        if role == "client" and in_client:
            chosen[group] = (
                commands if allowed is None else {n: c for n, c in commands.items() if n in allowed}
            )
        elif role == "server":
            rest = (
                commands
                if not in_client
                else (
                    {}
                    if allowed is None
                    else {n: c for n, c in commands.items() if n not in allowed}
                )
            )
            if rest:
                chosen[group] = rest
    return chosen


def build_parser(role: str = "all") -> argparse.ArgumentParser:
    prog = "laris-server" if role == "server" else "laris"
    return build_parser_for(commands_for(role), prog)


def main(argv: Optional[Sequence[str]] = None, role: str = "all") -> int:
    prog = "laris-server" if role == "server" else "laris"
    return run(commands_for(role), prog, argv, interactive=role != "server")


if __name__ == "__main__":
    sys.exit(main())
