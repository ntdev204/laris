"""OpenStax CNXML modules as Source text and the statements a Claim may quote (T277).

A module becomes one Source: its title, paragraphs, lists, tables, equations, notes, worked
examples' prose and glossary, written as plain text blocks. Exercises, review and practice
sections, teacher notes, learning objectives and media are left out (the classes come from the
configuration): they are questions, not knowledge, and they are what a benchmark could share.

The statements are read from the book's own markup, never written by a model:

* `definition`: a glossary entry, `term: meaning`;
* `key-concept`: an item (or a sentence) of a key-concepts or summary section;
* `key-equation`: a row of a key-equations or formula-review table;
* `law`: a boxed statement with its formula (`note class="equation-callout"`).

Each statement is a line of the Source text, so its quote is exact and its span resolves.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence, Set

from laris.research.knowledge import mathml

CNXML = "{http://cnx.rice.edu/cnxml}"
MATH = mathml.MATHML + "math"
_SUMMARY = {"key-concepts", "summary", "section-summary"}
_EQUATIONS = {"key-equations", "formula-review"}
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])")
_WORD = re.compile(r"[A-Za-z]{2,}")
_ABBREV = re.compile(r"\b(?:e\.g|i\.e|etc|vs|Fig|Eq|approx|ca|cf|al|No|Dr|Mr|Mrs|St)\.\Z")


@dataclass
class Statement:
    kind: str
    text: str
    formula: Optional[str] = None  # solver form of the statement's one formula, when it has one


@dataclass
class Module:
    module_id: str
    title: str
    text: str
    statements: List[Statement] = field(default_factory=list)


def _local(tag: object) -> str:
    if not isinstance(tag, str):
        return ""
    return tag.split("}", 1)[-1]


def _classes(node: ET.Element) -> Set[str]:
    return set((node.get("class") or "").split())


def _fold(text: str) -> str:
    return " ".join(text.split())


class Reader:
    """Renders modules with a fixed set of dropped element names and class tokens."""

    def __init__(self, dropped_elements: Sequence[str], dropped_classes: Sequence[str]) -> None:
        self.dropped_elements = set(dropped_elements)
        self.dropped_classes = set(dropped_classes)

    def dropped(self, node: ET.Element) -> bool:
        name = _local(node.tag)
        if name in self.dropped_elements or name in ("metadata", "figure", "media", "footnote"):
            return True
        return bool(_classes(node) & self.dropped_classes)

    # -- inline text ----------------------------------------------------------------------------

    def inline(self, node: ET.Element) -> str:
        parts: List[str] = [node.text or ""]
        for child in node:
            name = _local(child.tag)
            if child.tag == MATH:
                parts.append(" " + mathml.as_text(child) + " ")
            elif self.dropped(child):
                pass
            elif name == "sub":
                parts.append("_" + self.inline(child).strip())
            elif name == "sup":
                parts.append("^" + self.inline(child).strip())
            elif name in ("newline", "space"):
                parts.append(" ")
            elif name in ("list", "table"):
                parts.append(" " + " ".join(self.blocks(child)) + " ")
            else:
                parts.append(self.inline(child))
            parts.append(child.tail or "")
        return "".join(parts)

    # -- blocks ----------------------------------------------------------------------------------

    def blocks(self, node: ET.Element) -> List[str]:
        """Text blocks of an element, in reading order."""
        out: List[str] = []
        for child in node:
            if not isinstance(child.tag, str) or self.dropped(child):
                continue
            name = _local(child.tag)
            if name == "title":
                line = _fold(self.inline(child))
                if line:
                    out.append(line)
            elif name in ("para", "quote", "preformat", "code") or child.tag == MATH:
                line = _fold(self.inline(child)) if child.tag != MATH else mathml.as_text(child)
                if line:
                    out.append(line)
            elif name == "equation":
                maths = child.findall(f".//{MATH}")
                line = _fold(" ".join(mathml.as_text(m) for m in maths)) or _fold(
                    self.inline(child)
                )
                if line:
                    out.append(line)
            elif name == "list":
                for item in child:
                    if _local(item.tag) == "item" and not self.dropped(item):
                        line = _fold(self.inline(item))
                        if line:
                            out.append(line)
            elif name == "table":
                for row in child.iter(f"{CNXML}row"):
                    cells = [_fold(self.inline(e)) for e in row if _local(e.tag) == "entry"]
                    cells = [c for c in cells if c]
                    if cells:
                        out.append(" | ".join(cells))
            elif name == "definition":
                line = self.definition(child)
                if line:
                    out.append(line)
            elif name == "term":
                line = _fold(self.inline(child))
                if line:
                    out.append(line)
            else:  # section, note, example, glossary, content, div ...
                out.extend(self.blocks(child))
        return out

    def definition(self, node: ET.Element) -> Optional[str]:
        term = node.find(f"{CNXML}term")
        meaning = node.find(f"{CNXML}meaning")
        if term is None or meaning is None:
            return None
        t, m = _fold(self.inline(term)), _fold(self.inline(meaning))
        return f"{t}: {m}" if t and m else None

    # -- module ----------------------------------------------------------------------------------

    def module(self, module_id: str, xml_text: str, max_statement_bytes: int) -> Module:
        root = ET.fromstring(xml_text)
        title_node = root.find(f"{CNXML}title")
        title = _fold(self.inline(title_node)) if title_node is not None else module_id
        lines = [title]
        for part in ("content", "glossary"):
            node = root.find(f"{CNXML}{part}")
            if node is not None:
                lines.extend(self.blocks(node))
        text = "\n\n".join(lines) + "\n"
        folded = _fold(text)
        statements = [
            s
            for s in self.statements(root)
            if len(s.text.encode("utf-8")) <= max_statement_bytes and s.text in folded
        ]
        return Module(module_id, title, text, _unique(statements))

    def statements(self, root: ET.Element) -> Iterable[Statement]:
        # everything below a dropped element is dropped too
        hidden = {
            id(e)
            for d in root.iter()
            if isinstance(d.tag, str) and self.dropped(d)
            for e in d.iter()
        }
        for node in root.iter(f"{CNXML}definition"):
            if id(node) not in hidden:
                line = self.definition(node)
                if line:
                    yield Statement("definition", line)
        for section in root.iter(f"{CNXML}section"):
            classes = _classes(section)
            if id(section) in hidden:
                continue
            if classes & _SUMMARY:
                yield from self._summary(section)
            if classes & _EQUATIONS:
                yield from self._equations(section)
        for parent in root.iter():
            kids = list(parent)
            for at, note in enumerate(kids):
                if _local(note.tag) != "note" or id(note) in hidden:
                    continue
                titled = note.find(f"{CNXML}title") is not None
                callout = "equation-callout" in _classes(note)
                if not (callout or titled) or note.find(f".//{MATH}") is None:
                    continue
                text = _fold(" ".join(self.blocks(note)))
                if callout and not titled and at > 0 and _local(kids[at - 1].tag) == "para":
                    # an untitled boxed formula states the law of the paragraph before it
                    text = _fold(self.inline(kids[at - 1])) + " " + text
                if len(_WORD.findall(text)) >= 4:
                    yield Statement("law", text, _one_formula(note))

    def _summary(self, section: ET.Element) -> Iterable[Statement]:
        for child in section:
            name = _local(child.tag)
            if name == "list":
                for item in child:
                    line = _fold(self.inline(item))
                    if line:
                        yield Statement("key-concept", line)
            elif name == "para":
                for sentence in sentences(_fold(self.inline(child))):
                    yield Statement("key-concept", sentence)

    def _equations(self, section: ET.Element) -> Iterable[Statement]:
        for row in section.iter(f"{CNXML}row"):
            cells = [_fold(self.inline(e)) for e in row if _local(e.tag) == "entry"]
            cells = [c for c in cells if c]
            if len(cells) >= 2:
                yield Statement("key-equation", " | ".join(cells), _one_formula(row))
        for child in section:
            name = _local(child.tag)
            if name in ("para", "equation"):
                block = self.blocks(_wrap(child))
                if block and child.findall(f".//{MATH}"):
                    yield Statement("key-equation", _fold(" ".join(block)), _one_formula(child))
            elif name == "list":
                for item in child:
                    if item.findall(f".//{MATH}"):
                        yield Statement(
                            "key-equation", _fold(self.inline(item)), _one_formula(item)
                        )


def _wrap(node: ET.Element) -> ET.Element:
    holder = ET.Element("holder")
    holder.append(node)
    return holder


def _one_formula(node: ET.Element) -> Optional[str]:
    """The solver form of the node's formula when it has exactly one that reads as an equation."""
    forms = [f for f in (mathml.solver_form(m) for m in node.iter(MATH)) if f]
    return forms[0] if len(forms) == 1 else None


def sentences(text: str) -> List[str]:
    """Sentences of a paragraph; a split after a common abbreviation is undone."""
    out: List[str] = []
    for piece in _SENTENCE.split(text):
        if out and _ABBREV.search(out[-1]):
            out[-1] = out[-1] + " " + piece
        else:
            out.append(piece)
    return [s for s in (p.strip() for p in out) if len(s.split()) >= 4]


def _unique(statements: List[Statement]) -> List[Statement]:
    seen: Set[str] = set()
    out = []
    for s in statements:
        if s.text not in seen:
            seen.add(s.text)
            out.append(s)
    return out
