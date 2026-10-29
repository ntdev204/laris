#!/usr/bin/env python3
"""Thin wrapper kept for compatibility; use `laris train language-encoder`."""

import sys

from laris.cli.main import main

if __name__ == "__main__":
    sys.exit(main(["train", "language-encoder", *sys.argv[1:]]))
