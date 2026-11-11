"""Shared command-line plumbing: build a parser from a command table and run the handler."""

import argparse
import sys
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

Handler = Callable[[argparse.Namespace], int]
Table = Dict[str, Dict[str, Tuple[str, Any]]]


def build_parser_for(table: Table, prog: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog, description=f"{prog} command-line interface")
    groups = parser.add_subparsers(dest="group", required=True)
    for group, commands in table.items():
        group_parser = groups.add_parser(group, help=f"{group} commands")
        leaves = group_parser.add_subparsers(dest="command", required=True)
        for name, (help_text, module) in commands.items():
            leaf = leaves.add_parser(name, help=help_text, description=help_text)
            module.add_arguments(leaf)
            leaf.set_defaults(handler=module.run)
    return parser


def interactive_default(argv: Sequence[str]) -> List[str]:
    """`laris` and `laris --resume [id]` open the terminal chat; named commands are unchanged."""
    items = list(argv)
    if items and items[0] in ("-h", "--help"):
        return items
    if items and items[0] in ("login", "logout", "whoami", "init"):
        return ["account", *items]
    if not items or items[0].startswith("-"):
        return ["agent", "chat", *items]
    return items


def run(table: Table, prog: str, argv: Optional[Sequence[str]], interactive: bool) -> int:
    items = sys.argv[1:] if argv is None else argv
    if interactive:
        items = interactive_default(items)
    args = build_parser_for(table, prog).parse_args(items)
    handler: Handler = args.handler
    from cli.credentials import CredentialError
    from harness.integrity import IntegrityError
    from harness.prompts import PromptError

    try:
        return handler(args)
    except (IntegrityError, PromptError, CredentialError) as exc:  # reported, not traced
        print(f"[ERROR] {exc}")
        return 2
