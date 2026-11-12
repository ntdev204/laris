"""Obsidian-format vaults: plain Markdown folders with properties, wikilinks and tags.

The library implements the file format itself (no Obsidian, no network), so a vault works for
people with or without the app. See docs/specifications/OBSIDIAN_VAULT_FORMAT.md.
"""

from laris.shared.vault.index import VaultIndex
from laris.shared.vault.notes import Link, Note, parse_note

__all__ = ["Link", "Note", "VaultIndex", "parse_note"]
