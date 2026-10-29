#!/usr/bin/env python3
"""Thin wrapper kept for backward compatibility; use `laris data acquire`."""

import sys

from laris.corpus.acquisition.runner import main

if __name__ == "__main__":
    sys.exit(main())
