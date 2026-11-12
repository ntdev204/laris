"""`laris-server`: operator commands (policy and brain checks, keys, usage, TLS, the server process,
and the owner-only data, training and evaluation tooling). Never part of the client package."""

import sys
from typing import Optional, Sequence

from cli.commands import (
    calibrate,
    check,
    db,
    evaluate,
    keys,
    language_encoder,
    model,
    partition,
    policy,
    readiness,
    suite,
    tokenizer,
    vault,
)
from cli.parser import Table, run
from laris.research.corpus.acquisition import runner as acquisition

COMMANDS: Table = {
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
    "db": {"migrate": ("Create or update the server database schema", db.COMMANDS["migrate"])},
    "model": {
        "serve": ("Serve the OpenAI-compatible model API", model.COMMANDS["serve"]),
    },
}


def main(argv: Optional[Sequence[str]] = None) -> int:
    return run(COMMANDS, "laris-server", argv, interactive=False)


if __name__ == "__main__":
    sys.exit(main())
