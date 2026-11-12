"""Development entry point: the commands of all three blocks in one parser (`python -m cli`).

The shipped programs are `laris` (`cli.client`), `laris-server` (`cli.server`) and `laris-model`
(`cli.model`); this module only merges their tables for tests and local work. There is no role
switch: each entry point owns its own table.

Command tree: see `cli.client`, `cli.server` and `cli.model`.
"""

import argparse
import sys
from typing import Optional, Sequence

from cli import client, model, server
from cli.parser import Table, build_parser_for, interactive_default, run  # noqa: F401


def merged() -> Table:
    table: Table = {}
    for part in (client.COMMANDS, server.COMMANDS, model.COMMANDS):
        for group, commands in part.items():
            table.setdefault(group, {}).update(commands)
    return table


COMMANDS = merged()


def build_parser() -> argparse.ArgumentParser:
    return build_parser_for(COMMANDS, "laris")


def main(argv: Optional[Sequence[str]] = None) -> int:
    return run(COMMANDS, "laris", argv, interactive=True)


if __name__ == "__main__":
    sys.exit(main())
