"""Regenerate the golden files of the vault parser and index from the generation-1 implementation.

    PYTHONPATH=src python3 tests/golden/vault/generate.py

`index.json` is the generation-1 index of `fixture/` (the form `VaultIndex::export_string` writes); `yaml_cases.json`
is what generation 1's `yaml.safe_load` gives for each snippet of `YAML_CASES`. The Rust tests (`laris-vault`) must
reproduce both. This script only reads the fixture and writes the two JSON files; it runs no model code.
"""

import datetime
import json
import re
from pathlib import Path

import yaml

from laris.shared.vault.index import VaultIndex
from laris.shared.vault.lint import lint_content, lint_format, lint_hierarchy
from laris.shared.vault.notes import _encode, note_to_dict
from laris.shared.vault.schema import Schema, lint_schema
from laris.shared.vault.writer import render_note, upsert_block, safe_title

HERE = Path(__file__).parent

YAML_CASES = [
    "a: 1",
    "a: 1\nb: two\nc: [x, y]",
    "a: 'it''s'\nb: \"tab\\there \\u00e9 \\\"q\\\"\"\nc: \"\"",
    "empty:\nnull_word: null\ntilde: ~\nn: Null\nN: NULL",
    "yes_: yes\nno_: No\ntrue_: TRUE\nfalse_: false\non_: ON\noff_: off",
    "i: 42\nn: -7\np: +3\nh: 0x1F\no: 0755\nb: 0b101\nu: 1_000\nz: 0\nbad_oct: 08\nsign_zero: -0",
    "f: 3.14\nh: .5\nn: -2.5\ns: 1e3\nse: 1.5e+3\nend: 5.\nu: 1_0.2_5\nsign_half: -.5",
    "d: 2026-11-13\nt: 2026-11-13 10:30:00\nz: 2026-11-13T10:30:00Z\no: 2026-11-13T10:30:00.5+07:00\nm: 2026-1-3 1:02:03",
    "frac: 2026-11-13T10:30:00.123456789Z\nneg: 2026-11-13T10:30:00-05:30\nspace_z: 2026-11-13 10:30:00 Z\nhour: 2026-11-13 10:30:00 +7",
    "time_like: 10:30\nurl: http://example.com/a:b\nv: 1.0.0\nver: 1.2",
    "tags: [a, \"b c\", 'd']\nmore: [ 1 , 2,3 ]\nempty_list: []\nempty_map: {}",
    "list:\n- one\n- two words\n- \"[[Note]]\"",
    "list:\n  - one\n  - two\nnext: 1",
    "items:\n- a: 1\n  b: 2\n- c: 3\n-\n  d: 4\n- - x\n  - y",
    "m: {a: 1, b: [2, 3], c: {d: e}, f}",
    "nested:\n  inner:\n    deeper: value\n  other: 1\ntop: 2",
    "lit: |\n  line one\n  line two\n\nafter: 1",
    "strip: |-\n  text\n\nkeep: |+\n  text\n\nafter: 1",
    "fold: >\n  folded text\n  continues\n\n  new paragraph\n    indented\n  back\nnext: 1",
    "fold_strip: >-\n  a\n  b",
    "wrapped: a plain scalar\n  that wraps\n\n  with a blank line\nnext: 1",
    "quoted: \"a double\n  quoted wrap\"\nsingle: 'a single\n  wrap'\nnext: 1",
    "flow: [a,\n  b,\n  c]\nnext: [d]",
    "dup: first\nother: 1\ndup: second",
    "1: int key\ntrue_key: x\nnull: null key\n2026-01-02: date key\n'quoted key': 1\n\"dq\": 2",
    "# comment first\na: 1 # trailing\n# between\nb: 'x # not a comment' # real\nc: x#y\nd: \"q\" # c",
    "url: http://a/b#frag\nhash: a #comment\nquote: \"has # hash\"",
    "key: value: with colon",
    "key: [unclosed",
    "key: 'unclosed",
    "key: \"bad \\q escape\"",
    "a: 1\n b: 2",
    "a: 1\n\tb: 2",
    "- just\n- a list",
    "just a scalar",
    "# only a comment",
    "",
    "a: 2026-02-30",
    "a: 2026-13-01",
    "a: 2026-11-13 25:00:00",
    "a: 1:30\nb: -1:02:03\nc: 1:30.5\nd: 12:60\ne: 0:30\nf: 1_0:30",
    "a: {x: 1}}",
    "a: [1, 2]]",
    "a: - b",
    "a: 'x' y",
    "a:\n- 1\n- 2\nb:\n  - 3",
    "a:\n  - 1\n b: 2",
    "a: [[1, 2], [3, {b: c}]]",
    "a: [\"x, y\", 'z]']",
    "a: [x#y, z]",
    "msg: Tom & Jerry, 50% off @home",
    "text: it's fine\nmore: say \"hi\" now",
    "k: v\n\n\nother: w\n",
    "a:\n\n  b: 1",
    "a: b\n  c: d",
    "- a\n-b",
    "a: [1, 2,]",
    "a: [,]",
    "a: {b: , c: 1}",
    "~: tilde key",
    "a: b\t",
    "a:\n  yes: tab\there",
    "a: [x,\ty]",
    "a: \"x\ty\"\nb: # c\tinside a comment",
    "a: |\n  x\ty\t\n",
    "a: }",
    "a: ,",
    "a: ]",
    "a: : x",
    "key: |\n  text",
    "key: |+\n  text\n",
    "key: |+\n  text\n\n",
    "key: |-\n  text\n",
    "key: >\n  text\n  more",
    "type: |\n # x",
    "k: |\n",
    "k: |\n\n\n",
    "k: |+\n\n\n",
    "emoji: 🙂 ok\nvi: Tiếng Việt",
]


D = datetime.date
DT = datetime.datetime

WRITER_PROPS = [
    {},
    {"type": "source", "trust": "untrusted", "created": D(2026, 11, 18), "source": "paper.pdf"},
    {"type": "answer", "sources": ["[[Paper (source)]]", "[[Other]]"], "session": "[[sess-0001]]"},
    {"a": "true", "b": "null", "c": "123", "d": "1.5", "e": "2026-01-02", "f": "yes", "g": "~", "h": ""},
    {"a": True, "b": False, "c": None, "d": 0, "e": -7, "f": 3.5, "g": 1e20, "h": 1e-5, "i": 0.1, "j": 100.0},
    {"when": DT(2026, 11, 18, 10, 30, 0), "tz": DT(2026, 11, 18, 10, 30, 0, tzinfo=datetime.timezone.utc)},
    {"a": "x: y", "b": "x #y", "c": "#x", "d": "- x", "e": "-x", "f": "? x", "g": "a, b", "h": "[x]"},
    {"a": " lead", "b": "trail ", "c": "two  spaces", "d": "it's", "e": 'say "hi"', "f": "100%", "g": "@at"},
    {"a": "line one\nline two", "b": "a\n\nb", "c": "trail\n", "d": "\nlead", "e": "a \nb", "f": "a\n b"},
    {"a": "tab\there", "b": "bell\x07", "c": "nul\x00", "d": "quote's\ttab"},
    {"vi": "Tiếng Việt", "emoji": "🙂 ok", "mixed": "Ghi chú: một", "cjk": "漢字"},
    {"empty": [], "one": ["x"], "many": ["a b", "true", "1", "", "- x", "[[Note]]", "x: y"]},
    {"---": 1, "<<": 2, "=": 3, "a b": 4, "yes": 5, "1": 6, "x-y_z": 7, "é": 8},
    {"long": "word " * 100, "n": "9" * 30, "hex": "0x1F", "oct": "0755", "sex": "1:30", "inf": ".inf", "nan": ".nan"},
    {"dash": "-", "dots": "...", "ddd": "--- x", "colon": ":", "q": "?", "star": "*a", "amp": "&a", "bang": "!a"},
]

BLOCK_STEPS = [
    ("# Title\n\nmine\n", "facts", "one"),
    ("", "facts", "one"),
    ("\n\n", "facts", "one\n"),
    ("text\n<!-- laris:begin a sha=0000000000000000 -->\nx\n<!-- laris:end a -->\n", "a", "y"),
    ("text\n<!-- laris:begin a sha=0000000000000000 -->\nx\n<!-- laris:end b -->\n", "a", "y"),
]


def block_cases():
    out = []
    for text, name, content in BLOCK_STEPS:
        new, status = upsert_block(text, name, content)
        again, status2 = upsert_block(new, name, content)
        changed, status3 = upsert_block(new, name, content + " more")
        out.append({"text": text, "name": name, "content": content, "new": new, "status": status,
                    "again": again, "status2": status2, "changed": changed, "status3": status3})
    return out


def lint_cases():
    index = VaultIndex.build(HERE / "fixture")
    brain = VaultIndex.build(HERE / "brain")
    redact = lambda text: (re.sub(r"[A-Za-z]+\[\[", "<secret>[[", text),)  # noqa: E731
    problems = lambda ps: [[p.path, p.code, p.message] for p in ps]  # noqa: E731
    return {
        "format": problems(lint_format(index)),
        "schema": problems(lint_schema(index, Schema.builtin())),
        "content": problems(lint_content(index, 120, 25, redact)),
        "content_plain": problems(lint_content(index, 120, 25)),
        "hierarchy": problems(
            lint_hierarchy(brain, "Root", 2, 2, ["summary", "level"], 60, ["requires", "uses"])
        ),
        "hierarchy_no_root": problems(lint_hierarchy(brain, "Missing", 2, 2, [], 60)),
        "brain_format": problems(lint_format(brain)),
    }


def main() -> None:
    index = VaultIndex.build(HERE / "fixture")
    export = {
        "notes": {p: note_to_dict(n) for p, n in sorted(index.notes.items())},
        "outgoing": {p: [list(x) for x in index.outgoing(p)] for p in sorted(index.notes)},
        "backlinks": {p: index.backlinks(p) for p in sorted(index.notes)},
        "neighbours": {p: index.neighbours(p) for p in sorted(index.notes)},
        "unresolved": [list(x) for x in index.unresolved],
        "ambiguous": [list(x) for x in index.ambiguous],
        "orphans": index.orphans(),
        "unlinked": index.unlinked(),
    }
    text = json.dumps(export, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
    (HERE / "index.json").write_text(text, encoding="utf-8")

    cases = []
    for source in YAML_CASES:
        try:
            loaded = yaml.safe_load(source)
            cases.append({"yaml": source, "value": _encode(loaded), "dict": isinstance(loaded, dict)})
        except yaml.YAMLError:
            cases.append({"yaml": source, "error": True})
        except Exception as exc:  # generation 1 would crash on these (for example an impossible date)
            cases.append({"yaml": source, "error": True, "crash": type(exc).__name__})
    text = json.dumps(cases, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
    (HERE / "yaml_cases.json").write_text(text, encoding="utf-8")

    writer = [
        {"props": [[k, _encode(v)] for k, v in props.items()], "text": render_note(props, "Body text.")}
        for props in WRITER_PROPS
    ]
    titles = ["a/b:c", "  x.  ", "", "..", "x" * 150, "Tiếng #Việt|x", "tab\there", "a\n b"]
    out = {
        "render": writer,
        "blocks": block_cases(),
        "titles": [[t, safe_title(t)] for t in titles],
        "lint": lint_cases(),
    }
    text = json.dumps(out, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
    (HERE / "writer_lint.json").write_text(text, encoding="utf-8")
    print(f"{len(index.notes)} notes, {len(cases)} yaml cases, {len(writer)} writer cases")


if __name__ == "__main__":
    main()
