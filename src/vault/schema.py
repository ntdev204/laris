"""Note schema registry: which properties each note type must carry, and where it lives.

The registry is read from `.laris/vault/schema.yaml` (under the integrity lock). A project without
that file (a thin client, an adopted vault) uses the same table built into this module; a test keeps
the two identical. Notes without a `type` belong to the user and are never checked.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from vault.index import VaultIndex
from vault.lint import Problem
from vault.notes import Note, link_name

_BUILTIN_YAML = """
version: 1
types:
  index: {required: [type], folder: ""}
  source: {required: [type, trust, source, created], links: [concepts], folder: Sources}
  concept: {required: [type, created], folder: Concepts}
  claim: {required: [type, created, source_ref], links: [source_ref], folder: Claims}
  method: {required: [type, created], folder: Concepts}
  dataset: {required: [type, created], folder: Concepts}
  metric: {required: [type, created], folder: Concepts}
  limitation: {required: [type, created, source_ref], links: [source_ref], folder: Claims}
  answer:
    required: [type, trust, session, created]
    links: [session, sources, notes_used]
    folder: Questions
  session: {required: [type, created], folder: Sessions}
  memory: {required: [type, created], folder: Memory}
  decision: {required: [type, created], folder: Decisions}
  analysis: {required: [type, created, scope], folder: Analyses}
  proposal: {required: [type, status, origin, created], folder: _inbox}
  knowledge: {required: [type], folder: Knowledge}
  knowledge-hub: {required: [type, domain], folder: Knowledge}
"""


@dataclass(frozen=True)
class TypeRule:
    required: tuple
    links: tuple
    folder: str


class Schema:
    def __init__(self, types: Dict[str, TypeRule]) -> None:
        self.types = types

    @classmethod
    def from_text(cls, text: str) -> "Schema":
        data = yaml.safe_load(text) or {}
        raw = data.get("types", {}) if isinstance(data, dict) else {}
        types = {
            str(name): TypeRule(
                tuple(rule.get("required", [])),
                tuple(rule.get("links", [])),
                str(rule.get("folder", "")),
            )
            for name, rule in raw.items()
            if isinstance(rule, dict)
        }
        return cls(types)

    @classmethod
    def builtin(cls) -> "Schema":
        return cls.from_text(_BUILTIN_YAML)

    @classmethod
    def load(cls, path: Optional[Path]) -> "Schema":
        if path is not None and Path(path).is_file():
            return cls.from_text(Path(path).read_text(encoding="utf-8"))
        return cls.builtin()

    def folder_of(self, kind: str) -> str:
        rule = self.types.get(kind)
        return rule.folder if rule else ""


def _folder_ok(path: str, folder: str) -> bool:
    return not folder or path.startswith(folder + "/")


def validate_note(note: Note, index: VaultIndex, schema: Schema) -> List[Problem]:
    kind = note.props.get("type")
    if kind is None:
        return []  # the user's own note
    rule = schema.types.get(str(kind))
    if rule is None:
        return [Problem(note.path, "schema-type", f"unknown note type: {kind}")]
    problems: List[Problem] = []
    for prop in rule.required:
        if note.props.get(prop) in (None, "", []):
            problems.append(Problem(note.path, "schema-required", f"{kind} needs property {prop}"))
    for prop in rule.links:
        for value in note.prop_list(prop):
            if index.find(link_name(value)) is None:
                problems.append(
                    Problem(note.path, "schema-link", f"{prop} does not resolve: {value}")
                )
    if kind != "proposal" and not _folder_ok(note.path, rule.folder):
        problems.append(Problem(note.path, "schema-folder", f"{kind} notes live in {rule.folder}/"))
    return problems


def lint_schema(index: VaultIndex, schema: Optional[Schema] = None) -> List[Problem]:
    schema = schema or Schema.builtin()
    found: List[Problem] = []
    for _, note in sorted(index.notes.items()):
        found += validate_note(note, index, schema)
    return found


def as_dict(schema: Schema) -> Dict[str, Any]:
    return {
        k: {"required": list(v.required), "links": list(v.links), "folder": v.folder}
        for k, v in sorted(schema.types.items())
    }
