"""Development entry point (`python -m cli`): the model block (`cli.model`).

On `laris-v2` the Python client and server are removed; the harness is in Rust. Only the model
side stays in Python.
"""

import sys
from typing import Optional, Sequence

from cli import model


def main(argv: Optional[Sequence[str]] = None) -> int:
    return model.main(argv)


if __name__ == "__main__":
    sys.exit(main())
