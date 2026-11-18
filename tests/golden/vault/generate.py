"""Regenerate the golden files of the vault parser and index from the generation-1 implementation.

    PYTHONPATH=src python3 tests/golden/vault/generate.py

`index.json` is the generation-1 index of `fixture/` (the form `VaultIndex::export_string` writes); `yaml_cases.json`
is what generation 1's `yaml.safe_load` gives for each snippet of `YAML_CASES`. The Rust tests (`laris-vault`) must
reproduce both. This script only reads the fixture and writes the two JSON files; it runs no model code.
"""

import json
from pathlib import Path

import yaml

from laris.shared.vault.index import VaultIndex
from laris.shared.vault.notes import _encode, note_to_dict

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
    print(f"{len(index.notes)} notes, {len(cases)} yaml cases")


if __name__ == "__main__":
    main()
