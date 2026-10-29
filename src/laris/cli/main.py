"""`laris` command-line entry point.

Command tree (each leaf maps to a module in `laris.cli.commands`):

    laris data acquire             download and verify datasets, update the manifest
    laris data partition           physically split raw datasets into train/val/test
    laris train tokenizer          fit the SentencePiece tokenizer
    laris train language-encoder   train (or profile) the multi-task language encoder
"""

import argparse
import sys
from typing import Callable, Optional, Sequence

from laris.cli.commands import language_encoder, partition, tokenizer
from laris.corpus.acquisition import runner as acquisition

Handler = Callable[[argparse.Namespace], int]

COMMANDS = {
    "data": {
        "acquire": ("Download and verify datasets", acquisition),
        "partition": ("Physically partition raw datasets (zero training)", partition),
    },
    "train": {
        "tokenizer": ("Fit the SentencePiece tokenizer", tokenizer),
        "language-encoder": ("Train or profile the language encoder", language_encoder),
    },
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
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
