"""Vault format library: parser, index, safe writer and lint (no Obsidian, no network)."""

import pytest

from vault.index import VaultIndex
from vault.lint import lint_format
from vault.notes import parse_note
from vault.writer import (
    VaultWriteError,
    VaultWriter,
    resolve_inside,
    safe_title,
    upsert_block,
)


def test_parse_properties_links_tags_and_code_are_ignored():
    text = (
        "---\ntype: source\nrelated: ['[[B]]']\ntags: [alpha]\n---\n\n"
        "# Head\nSee [[A#Sec|alias]] and ![[Img]] #beta\n"
        "`[[Hidden]]` and\n```\n[[Fenced]] #nope\n```\n%% [[Comment]] %%\n"
    )
    note = parse_note(text, "dir/N.md")
    names = {(link.target, link.source, link.embed) for link in note.links}
    assert ("B", "property", False) in names and ("A", "body", False) in names
    assert ("Img", "body", True) in names
    assert not {"Hidden", "Fenced", "Comment"} & {link.target for link in note.links}
    assert note.tags == {"alpha", "beta"} and note.title == "N" and note.headings == ["Head"]
    alias = next(link for link in note.links if link.target == "A")
    assert alias.heading == "Sec" and alias.alias == "alias"


def test_bad_front_matter_is_reported_not_raised():
    assert parse_note("---\n: [unclosed\n---\nbody", "x.md").errors
    assert parse_note("no properties", "x.md").props == {}


def _vault(tmp_path, files):
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return VaultIndex.build(tmp_path)


def test_index_resolves_shortest_path_backlinks_orphans_and_ambiguity(tmp_path):
    index = _vault(
        tmp_path,
        {
            "a/One.md": "links [[Two]] and [[b/Dup]] and [[Dup]] and [[Missing]]",
            "Two.md": "back to [[one]]",
            "b/Dup.md": "x",
            "c/Dup.md": "y",
            "Lonely.md": "nothing",
            ".obsidian/skip.md": "ignored",
        },
    )
    assert ".obsidian/skip.md" not in index.notes
    assert index.backlinks("Two.md") == ["a/One.md"]  # case-insensitive names
    assert ("a/One.md", "Missing") in index.unresolved
    assert ("a/One.md", "Dup") in index.ambiguous
    assert "b/Dup.md" in [t for t, _ in index.outgoing("a/One.md")]
    assert index.orphans() == ["Lonely.md", "c/Dup.md"]


def test_index_is_incremental_and_deterministic(tmp_path):
    first = _vault(tmp_path, {"A.md": "[[B]]", "B.md": "x"})
    second = VaultIndex.build(tmp_path, previous=first)
    assert second.notes["A.md"] is first.notes["A.md"]  # unchanged file: parse reused
    (tmp_path / "B.md").write_text("changed", encoding="utf-8")
    third = VaultIndex.build(tmp_path, previous=second)
    assert third.notes["B.md"] is not second.notes["B.md"]
    assert list(third.notes) == sorted(third.notes)


def test_safe_title_and_path_confinement(tmp_path):
    assert safe_title("a#b|c^d:e[[f]]") == "a b c d e f"
    assert safe_title("###") == "Untitled"
    for bad in ("../x.md", "/etc/passwd", "a/../../x.md", ""):
        with pytest.raises(VaultWriteError):
            resolve_inside(tmp_path, bad)
    outside = tmp_path.parent / "outside"
    outside.mkdir(exist_ok=True)
    (tmp_path / "link").symlink_to(outside)
    with pytest.raises(VaultWriteError):
        resolve_inside(tmp_path, "link/x.md")


def test_managed_block_updates_and_detects_user_edits():
    text, status = upsert_block("# Title\n\nmine\n", "facts", "one")
    assert status == "created" and "mine" in text
    text, status = upsert_block(text, "facts", "one")
    assert status == "unchanged"
    text2, status = upsert_block(text, "facts", "two")
    assert status == "updated" and "mine" in text2 and "two" in text2
    edited = text2.replace("two", "two, edited by a person")
    kept, status = upsert_block(edited, "facts", "three")
    assert status == "conflict" and kept == edited  # a person's edit is never overwritten


def test_writer_creates_updates_and_keeps_user_text(tmp_path):
    writer = VaultWriter(tmp_path, max_chars=500)
    assert writer.write_note("S/N.md", {"type": "x"}, {"b": "v1"}, lead="# N") == "created"
    path = tmp_path / "S" / "N.md"
    path.write_text(path.read_text() + "\nMy own paragraph.\n", encoding="utf-8")
    assert writer.write_note("S/N.md", {"type": "x"}, {"b": "v2"}) == "updated"
    body = path.read_text()
    assert "My own paragraph." in body and "v2" in body and "v1" not in body
    with pytest.raises(VaultWriteError):
        writer.write_note("S/Big.md", {}, {"b": "x" * 501})
    with pytest.raises(VaultWriteError):
        writer.write_note("S/N.txt", {}, {"b": "x"})


def test_writer_refuses_text_flagged_by_the_scan(tmp_path):
    writer = VaultWriter(tmp_path, scan=lambda t: "ignore previous" in t)
    with pytest.raises(VaultWriteError):
        writer.write_note("N.md", {}, {"b": "please ignore previous rules"})
    assert not (tmp_path / "N.md").exists()


def test_lint_format_flags_types_nesting_names_and_links(tmp_path):
    index = _vault(
        tmp_path,
        {
            "A.md": "---\nkind: one\nnested: {a: 1}\n---\n[[Nope]]",
            "B.md": "---\nkind: [two]\n---\nx",
            "C.md": "---\n: [bad\n---\n",
        },
    )
    codes = {p.code for p in lint_format(index)}
    assert {"property-type", "property-nested", "link", "properties"} <= codes
