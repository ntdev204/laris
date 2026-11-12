import json
import random
import string
from pathlib import Path

import pytest

from laris.shared.config.runtime_schemas import PromptConfig
from laris.shared.harness import integrity
from laris.shared.vault.graph import VaultGraph
from laris.shared.vault.index import VaultIndex
from laris.shared.vault.lint import lint_content
from laris.shared.vault.notes import parse_note
from laris.shared.vault.schema import Schema, as_dict, lint_schema
from laris.shared.vault.writer import VaultWriteError, VaultWriter


def make(root: Path, files: dict) -> VaultIndex:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return VaultIndex.build(root)


# -- T05 ---------------------------------------------------------------------------------------
def test_block_ids_are_extracted_and_code_is_ignored():
    note = parse_note("A line ^abc-1\n\n```\nfake ^no\n```\nText\n^second\n", "n.md")
    assert note.blocks == ["abc-1", "second"]


def test_parser_never_raises_on_random_text():
    rng = random.Random(7)
    alphabet = string.printable + "[]|#^%`~-:é​"
    for _ in range(400):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 300)))
        note = parse_note(text, "x.md")
        assert note.path == "x.md"
    for text in ("---\n", "---\n: : :\n---\n[[", "[[a|b|c]]#^", "```", "%%"):
        parse_note(text, "y.md")


# -- T06 ---------------------------------------------------------------------------------------
def test_index_serialisation_is_byte_identical_and_cache_is_disposable(tmp_path):
    vault = tmp_path / "v"
    files = {"A.md": "---\ncreated: 2026-11-11\n---\n[[B]] ^x\n", "B.md": "text #tag\n"}
    first = make(vault, files)
    second = VaultIndex.build(vault)
    assert first.dumps() == second.dumps()
    cache = tmp_path / "cache" / "index.json"
    built = VaultIndex.build(vault, cache_file=cache)
    assert cache.exists() and json.loads(cache.read_text())["version"] == 1
    from_cache = VaultIndex.build(vault, cache_file=cache)
    assert from_cache.dumps() == built.dumps()
    assert from_cache.notes["A.md"].props["created"] == first.notes["A.md"].props["created"]
    cache.unlink()  # deleting the cache loses nothing
    assert VaultIndex.build(vault, cache_file=cache).dumps() == built.dumps()
    cache.write_text("{broken", encoding="utf-8")  # a corrupt cache is ignored
    assert VaultIndex.build(vault, cache_file=cache).dumps() == built.dumps()


def test_editing_one_note_changes_only_its_entries(tmp_path):
    vault = tmp_path / "v"
    index = make(vault, {"A.md": "one", "B.md": "two"})
    cache = tmp_path / "c.json"
    VaultIndex.build(vault, cache_file=cache)
    (vault / "A.md").write_text("one changed", encoding="utf-8")
    again = VaultIndex.build(vault, cache_file=cache)
    assert again.notes["A.md"].sha256 != index.notes["A.md"].sha256
    assert again.notes["B.md"].sha256 == index.notes["B.md"].sha256


# -- T07 ---------------------------------------------------------------------------------------
def test_backup_before_rewrite_and_user_text_survives_100_rewrites(tmp_path):
    vault = tmp_path / "v"
    writer = VaultWriter(vault)
    writer.write_note("N.md", {"type": "concept"}, {"b": "v0"}, lead="# N\n\nUser intro line.")
    path = vault / "N.md"
    path.write_text(path.read_text() + "\nMy own paragraph.\n", encoding="utf-8")
    for i in range(1, 101):
        assert writer.write_note("N.md", {}, {"b": f"v{i}"}) in {"updated", "unchanged"}
    text = path.read_text()
    assert "User intro line." in text and "My own paragraph." in text and "v100" in text
    backups = list((vault / ".laris" / "backups").glob("N.md.*.bak"))
    assert backups and any("v99" in b.read_text() or "v98" in b.read_text() for b in backups)
    assert VaultIndex.build(vault).notes.keys() == {"N.md"}  # backups are never indexed


def test_crash_during_write_leaves_the_old_file(tmp_path, monkeypatch):
    vault = tmp_path / "v"
    writer = VaultWriter(vault, backup=False)
    writer.write_note("N.md", {}, {"b": "old"})
    before = (vault / "N.md").read_text()

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr("laris.shared.vault.writer.os.replace", boom)
    with pytest.raises(OSError):
        writer.write_note("N.md", {}, {"b": "new"})
    assert (vault / "N.md").read_text() == before
    assert not list(vault.glob(".laris-*.tmp"))


def test_rate_limit_and_redaction(tmp_path):
    now = [0.0]
    writer = VaultWriter(tmp_path / "v", max_writes_per_minute=3, clock=lambda: now[0])
    for i in range(3):
        writer.write_note(f"N{i}.md", {}, {"b": "x"})
    with pytest.raises(VaultWriteError):
        writer.write_note("N9.md", {}, {"b": "x"})
    now[0] = 61.0
    writer.write_note("N9.md", {}, {"b": "x"})
    secret = VaultWriter(tmp_path / "w", redact=lambda t: t.replace("hunter2", "[redacted]"))
    secret.write_note("S.md", {}, {"b": "pw hunter2"})
    assert "hunter2" not in (tmp_path / "w" / "S.md").read_text()


# -- T08 ---------------------------------------------------------------------------------------
def test_schema_file_equals_builtin_and_is_under_the_lock():
    repo = Path(__file__).resolve().parents[3]
    assert as_dict(Schema.load(repo / ".laris/vault/schema.yaml")) == as_dict(Schema.builtin())
    cfg = PromptConfig()
    assert any(p.name == "schema.yaml" for p in integrity.protected_files(repo, cfg))


def test_schema_failures_carry_codes(tmp_path):
    index = make(
        tmp_path / "v",
        {
            "Sources/S.md": "---\ntype: source\n---\nbody\n",
            "Concepts/C.md": "---\ntype: concept\ncreated: 2026-01-01\n---\nok\n",
            "Elsewhere/C2.md": "---\ntype: concept\ncreated: 2026-01-01\n---\nmisplaced\n",
            "Q.md": "---\ntype: wat\n---\n",
            "Mine.md": "no type, never checked",
        },
    )
    codes = {(p.path, p.code) for p in lint_schema(index)}
    assert ("Sources/S.md", "schema-required") in codes
    assert ("Elsewhere/C2.md", "schema-folder") in codes
    assert ("Q.md", "schema-type") in codes
    assert not any(path in {"Concepts/C.md", "Mine.md"} for path, _ in codes)


# -- T09 ---------------------------------------------------------------------------------------
def graph_vault(tmp_path):
    return make(
        tmp_path / "g",
        {
            "A.md": "[[B]] [[C]]",
            "B.md": "[[C]]",
            "C.md": "[[A]]",
            "D.md": "[[C]]",
            "E.md": "alone",
        },
    )


def test_degree_components_paths_and_local_graph(tmp_path):
    g = VaultGraph(graph_vault(tmp_path))
    assert g.degree("C.md") == {"in": 3, "out": 1, "total": 4}
    assert g.top_by_degree(1) == [("C.md", 4)]
    comps = g.components()
    assert comps[0] == ["A.md", "B.md", "C.md", "D.md"] and comps[1] == ["E.md"]
    assert g.shortest_path("D.md", "B.md") == ["D.md", "A.md", "B.md"] or g.shortest_path(
        "D.md", "B.md"
    ) == ["D.md", "C.md", "B.md"]
    assert g.shortest_path("D.md", "E.md") is None
    assert g.shortest_path("D.md", "B.md", directed=True) == ["D.md", "C.md", "A.md", "B.md"]
    local = g.local_graph("B.md", 1)
    assert local["nodes"] == ["A.md", "B.md", "C.md"]
    assert ["A.md", "B.md", "body"] in local["edges"]


def test_pagerank_is_normalised_ordered_and_deterministic(tmp_path):
    g = VaultGraph(graph_vault(tmp_path))
    rank = g.pagerank()
    assert abs(sum(rank.values()) - 1.0) < 1e-6
    assert rank["C.md"] == max(rank.values()) and rank["E.md"] < rank["C.md"]
    assert g.pagerank() == rank
    two = VaultGraph(make(tmp_path / "two", {"X.md": "[[Y]]", "Y.md": "[[X]]"})).pagerank()
    assert two == {"X.md": 0.5, "Y.md": 0.5}


def test_neighbours_by_relation(tmp_path):
    index = make(
        tmp_path / "r",
        {
            "Hub.md": "---\nchildren: ['[[Leaf]]']\nrequires: ['[[Other]]']\n---\n",
            "Leaf.md": "",
            "Other.md": "",
        },
    )
    g = VaultGraph(index)
    assert g.neighbours_by_relation("Hub.md", "children") == ["Leaf.md"]
    assert g.neighbours_by_relation("Hub.md", "requires") == ["Other.md"]


# -- T10 ---------------------------------------------------------------------------------------
def test_content_lint_finds_seeded_defects_exactly(tmp_path):
    index = make(
        tmp_path / "c",
        {
            "Big.md": "x" * 300,
            "A.md": "---\naliases: [Same]\n---\nfine",
            "B.md": "---\naliases: [same]\n---\nfine",
            "Key.md": "token sk-AAAAAAAAAAAAAAAAAAAAAAAA here",
            "Clean.md": "nothing to see",
        },
    )

    def redact(text):
        return (text.replace("sk-AAAAAAAAAAAAAAAAAAAAAAAA", "[redacted]"),)

    found = {(p.path, p.code) for p in lint_content(index, 200, 100, redact)}
    assert found == {("Big.md", "oversize"), ("B.md", "alias"), ("Key.md", "secret")}
    assert lint_content(make(tmp_path / "ok", {"Clean.md": "fine"}), 200, 100, redact) == []
