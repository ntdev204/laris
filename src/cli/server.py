"""`laris-server`: operator commands (model server, policy and brain checks, data, evaluation)."""

import sys
from typing import Optional, Sequence

from cli.main import main as _main


def main(argv: Optional[Sequence[str]] = None) -> int:
    return _main(argv, role="server")


if __name__ == "__main__":
    sys.exit(main())
