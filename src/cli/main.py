"""Development entry point (`python -m cli`): the model block's commands (`cli.model`).

On `laris-v2` the Python client and server are removed; the harness is being rewritten in Rust
(see `idea.md`). Only the model side stays in Python.
"""

import argparse
import sys
from typing import Optional, Sequence

from cli import model
from cli.parser import Table, build_parser_for, interactive_default, run  # noqa: F401

COMMANDS: Table = model.COMMANDS


def build_parser() -> argparse.ArgumentParser:
    return build_parser_for(COMMANDS, "laris")


def main(argv: Optional[Sequence[str]] = None) -> int:
    return run(COMMANDS, "laris", argv, interactive=False)


if __name__ == "__main__":
    sys.exit(main())
