"""`laris` command-line entry point.

Command tree (each leaf maps to a module in `cli.commands`):

    laris data acquire             download and verify datasets, update the manifest
    laris data partition           physically split raw datasets into train/val/test
    laris data check               verify processed splits, manifest and sentencepiece
    laris train tokenizer          fit the SentencePiece tokenizer
    laris train language-encoder   train (or profile) the multi-task language encoder
    laris evaluate language-encoder   score a checkpoint on the val/test split vs baselines
    laris evaluate calibrate       ratchet acceptance thresholds up from passing val reports
    laris app ingest|index|search|ask|status|serve   local end-to-end application and web UI
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
    agent,
    app,
    calibrate,
    check,
    evaluate,
    infer,
    language_encoder,
    learn,
    model,
    partition,
    policy,
    readiness,
    skills,
    tokenizer,
    vault,
)
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
    },
    "app": {
        "ingest": ("Add documents to the local workspace", app.COMMANDS["ingest"]),
        "index": ("Embed passages with a checkpoint (inference only)", app.COMMANDS["index"]),
        "search": ("Search the workspace", app.COMMANDS["search"]),
        "ask": ("Extractive answer with source passages", app.COMMANDS["ask"]),
        "status": ("Show workspace and model status", app.COMMANDS["status"]),
        "serve": ("Serve the web UI and JSON API locally", app.COMMANDS["serve"]),
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
    "vault": {
        "init": ("Create the project vault in this codebase", vault.VAULT_COMMANDS["init"]),
        "check": ("Lint the project vault", vault.VAULT_COMMANDS["check"]),
        "status": ("Counts per folder and link health", vault.VAULT_COMMANDS["status"]),
    },
    "brain": {
        "check": ("Lint the system brain structure", vault.BRAIN_COMMANDS["check"]),
        "tree": ("Print the brain hub tree (titles only)", vault.BRAIN_COMMANDS["tree"]),
        "route": ("Show which hub a task routes to", vault.BRAIN_COMMANDS["route"]),
    },
    "model": {
        "serve": ("Serve the OpenAI-compatible model API", model.COMMANDS["serve"]),
    },
    "infer": {name: (f"Run {name} on a checkpoint", cmd) for name, cmd in infer.COMMANDS.items()},
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="laris", description="LARIS command-line interface")
    groups = parser.add_subparsers(dest="group", required=True)
    for group, commands in COMMANDS.items():
        group_parser = groups.add_parser(group, help=f"{group} commands")
        leaves = group_parser.add_subparsers(dest="command", required=True)
        for name, (help_text, module) in commands.items():
            leaf = leaves.add_parser(name, help=help_text, description=help_text)
            module.add_arguments(leaf)
            leaf.set_defaults(handler=module.run)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    handler: Handler = args.handler
    from harness.integrity import IntegrityError
    from harness.prompts import PromptError

    try:
        return handler(args)
    except (IntegrityError, PromptError) as exc:  # policy problems are reported, not traced
        print(f"[ERROR] {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
