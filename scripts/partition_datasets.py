#!/usr/bin/env python3
"""Thin wrapper kept for compatibility; use `laris data partition`."""

import sys

from laris.cli.main import main

if __name__ == "__main__":
    sys.exit(main(["data", "partition", *sys.argv[1:]]))
