"""`laris`: the user's terminal client. Server and operator commands are not part of it."""

import sys
from typing import Optional, Sequence

from cli.main import main as _main


def main(argv: Optional[Sequence[str]] = None) -> int:
    return _main(argv, role="client")


if __name__ == "__main__":
    sys.exit(main())
