#!/usr/bin/env python3
"""Thin wrapper kept for compatibility; use `laris data acquire`."""

import sys

from laris.cli.main import main

if __name__ == "__main__":
    sys.exit(main(["data", "acquire", *sys.argv[1:]]))
