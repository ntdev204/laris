"""Vault lint: format problems and the hub-tree structure rules for the system brain."""

import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from vault.index import VaultIndex
from vault.notes import FORBIDDEN_NAME_CHARS, link_name
from vault.writer import MAX_TITLE_CHARS

_PROP_NAME = re.compile(r"^[A-Za-z][\w-]*$")


@dataclass(frozen=True)
class Problem:
    path: str
    code: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: [{self.code}] {self.message}"


def lint_format(index: VaultIndex) -> List[Problem]:
    """Rules that apply to every vault: names, properties, links."""
    problems: List[Problem] = []
    types: Dict[str, str] = {}
    for path, note in sorted(index.notes.items()):
        for err in note.errors:
            problems.append(Problem(path, "properties", err))
        if any(c in note.title for c in FORBIDDEN_NAME_CHARS) or len(note.title) > MAX_TITLE_CHARS:
            problems.append(Problem(path, "name", "note name has characters that break links"))
        for name, value in note.props.items():
            if not _PROP_NAME.match(name):
                problems.append(Problem(path, "property-name", f"unsafe property name: {name}"))
            kind = type(value).__name__ if not isinstance(value, list) else "list"
            if value is not None and types.setdefault(name, kind) != kind:
                problems.append(
                    Problem(
                        path, "property-type", f"{name} is {kind} here, {types[name]} elsewhere"
                    )
                )
            if isinstance(value, dict):
                problems.append(Problem(path, "property-nested", f"{name} must not be nested"))
    for path, target in index.unresolved:
        problems.append(Problem(path, "link", f"unresolved link: [[{target}]]"))
    for path, target in index.ambiguous:
        problems.append(Problem(path, "link", f"ambiguous link: [[{target}]]"))
    return problems


def lint_hierarchy(
    index: VaultIndex,
    root_title: str,
    max_depth: int,
    max_children: int,
    required: Sequence[str],
    summary_max_chars: int,
    relations: Optional[Sequence[str]] = None,
) -> List[Problem]:
    """The hub-tree rules of the system brain (spec SR-B6)."""
    problems: List[Problem] = []
    root = index.find(root_title)
    if root is None:
        return [Problem(root_title, "root", "root note is missing")]
    for path, note in sorted(index.notes.items()):
        for prop in required:
            if note.props.get(prop) in (None, "", []):
                problems.append(Problem(path, "property", f"missing property: {prop}"))
        summary = str(note.props.get("summary", ""))
        if len(summary) > summary_max_chars:
            problems.append(Problem(path, "summary", "summary is too long"))
    parent_of: Dict[str, str] = {}
    for path in sorted(index.notes):
        note = index.notes[path]
        children = index.targets(path, "children")
        if len(children) > max_children:
            problems.append(
                Problem(path, "wide-hub", f"{len(children)} children (max {max_children})")
            )
        for child in children:
            if child in parent_of and parent_of[child] != path:
                problems.append(Problem(child, "parents", "more than one parent lists this note"))
            parent_of[child] = path
        declared = {link_name(c) for c in note.prop_list("children")}
        body_links = {link.target for link in note.links if link.source == "body"}
        for name in sorted(declared - body_links):
            problems.append(
                Problem(path, "hub-body", f"child [[{name}]] is not described in the body")
            )
        for relation in relations or ():
            for target in note.prop_list(relation):
                if index.find(link_name(target)) is None:
                    problems.append(
                        Problem(path, "relation", f"{relation} target missing: {target}")
                    )
    depth: Dict[str, int] = {}
    queue = [(next(p for p, n in index.notes.items() if n is root), 0)]
    while queue:
        path, d = queue.pop(0)
        if path in depth:
            continue
        depth[path] = d
        queue += [(c, d + 1) for c in index.targets(path, "children")]
    for path, note in sorted(index.notes.items()):
        if path not in depth:
            problems.append(Problem(path, "orphan", "not reachable from the root through children"))
            continue
        if depth[path] > max_depth:
            problems.append(Problem(path, "depth", f"depth {depth[path]} exceeds {max_depth}"))
        if path != next(p for p, n in index.notes.items() if n is root):
            expected = parent_of.get(path)
            declared_parent = index.targets(path, "parent")
            if not declared_parent or declared_parent[0] != expected:
                problems.append(Problem(path, "parent", "parent does not match the listing hub"))
        if str(note.props.get("level", "")) != str(depth[path]):
            problems.append(Problem(path, "level", f"level should be {depth[path]}"))
    return problems


def lint_content(
    index: VaultIndex,
    max_note_chars: int,
    max_property_chars: int,
    redact: Optional[Callable[[str], Tuple[Any, ...]]] = None,
) -> List[Problem]:
    """Rules about what a note contains: oversize, duplicate aliases, stored secrets."""
    problems: List[Problem] = []
    aliases: Dict[str, str] = {}
    for path, note in sorted(index.notes.items()):
        if len(note.body) > max_note_chars:
            problems.append(
                Problem(path, "oversize", f"note is longer than {max_note_chars} chars")
            )
        for name, value in note.props.items():
            if len(str(value)) > max_property_chars:
                problems.append(Problem(path, "oversize", f"property {name} is very long"))
        for alias in note.prop_list("aliases"):
            key = alias.strip().lower()
            if key in aliases and aliases[key] != path:
                problems.append(
                    Problem(path, "alias", f"alias '{alias}' is also used by {aliases[key]}")
                )
            aliases.setdefault(key, path)
        if redact is not None:
            text = note.body + "\n" + "\n".join(str(v) for v in note.props.values())
            if redact(text)[0] != text:
                problems.append(Problem(path, "secret", "the note appears to contain a secret"))
    return problems
