import hashlib
from pathlib import Path

from laris.client.application.workspace import Chunk
from laris.client.vault.hooks import record_ingest
from laris.shared.config.runtime_schemas import VaultConfig
from laris.shared.harness.runtime import HarnessRuntime
from laris.shared.vault.index import VaultIndex
from laris.shared.vault.memory import migrate, read_memory, undo_migration, write_memory
from laris.shared.vault.project import ProjectVault
from laris.shared.vault.schema import lint_schema


def snapshot(root: Path) -> dict:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and ".laris/backups" not in p.as_posix()
    }


# -- T11 ---------------------------------------------------------------------------------------
def test_init_twice_changes_nothing_and_graph_is_connected(tmp_path):
    vault = ProjectVault(tmp_path, VaultConfig())
    assert vault.ensure() is True
    vault.record_source("Paper (source)", "p.md", 2, ["term"], "text")
    vault.record_answer("sess1234", "Q?", "A.", ["Paper (source)"])
    vault.refresh_index()
    before = snapshot(vault.root)
    assert vault.ensure() is False
    vault.refresh_index()
    assert snapshot(vault.root) == before
    assert (vault.root / "_templates" / "Source.md").is_file()
    index = VaultIndex.build(vault.root)
    assert "_templates/Source.md" not in index.notes
    assert lint_schema(index) == []
    # connected: every recorded note is reachable from the index note by links, either direction
    start = "00 Index.md"
    seen, queue = {start}, [start]
    while queue:
        for other in index.neighbours(queue.pop()):
            if other not in seen:
                seen.add(other)
                queue.append(other)
    assert {p for p in index.notes if not p.startswith("Concepts/")} <= seen | {
        p for p in index.notes if p.startswith("Concepts/")
    }
    assert any(p.startswith("Sources/") for p in seen) and any(
        p.startswith("Questions/") for p in seen
    )


def test_adopting_an_existing_vault_rewrites_no_note(tmp_path):
    folder = tmp_path / "vault"
    (folder / ".obsidian").mkdir(parents=True)
    (folder / ".obsidian" / "app.json").write_text('{"mine": true}')
    (folder / "My note.md").write_text("---\ntitle: mine\n---\nHand written [[Other]]\n")
    (folder / "Other.md").write_text("other")
    before = {
        p: (folder / p).read_bytes() for p in ("My note.md", "Other.md", ".obsidian/app.json")
    }
    vault = ProjectVault(tmp_path, VaultConfig())
    vault.ensure()
    vault.refresh_index()
    for rel, data in before.items():
        assert (folder / rel).read_bytes() == data


def test_vault_inside_another_vault_is_refused(tmp_path):
    (tmp_path / ".obsidian").mkdir()
    vault = ProjectVault(tmp_path / "sub", VaultConfig())
    result = vault.record_concept("x")
    assert result.status == "skipped" and "another vault" in result.reason
    assert not (tmp_path / "sub" / "vault").exists()
    allowed = ProjectVault(tmp_path / "sub", VaultConfig(allow_nested=True))
    assert allowed.record_concept("x").status == "created"


# -- T12 ---------------------------------------------------------------------------------------
def test_source_note_has_hash_and_passage_metadata_and_reingest_updates(tmp_path, project):
    runtime = HarnessRuntime.load(project)
    chunks = [
        Chunk("c1", "d1", "docs/paper.txt", "Paper", "Perovskite cells reach 25 percent.", 0, 34),
        Chunk("c2", "d1", "docs/paper.txt", "Paper", "We used the NREL dataset.", 35, 60),
    ]
    record_ingest(runtime, chunks)
    note = VaultIndex.build(project / "vault").notes["Sources/paper (source).md"]
    expected = hashlib.sha256("\n".join(c.text for c in chunks).encode()).hexdigest()
    assert note.props["sha256"] == expected and note.props["passages"] == 2
    assert note.props["chars"] == 60 and note.props["doc_id"] == "d1"
    record_ingest(runtime, chunks)
    again = [p for p in VaultIndex.build(project / "vault").notes if p.startswith("Sources/")]
    assert again == ["Sources/paper (source).md"]


def test_ingest_never_fails_when_the_vault_refuses(tmp_path, project):
    (project.parent / ".obsidian").mkdir(exist_ok=True)  # the project sits inside a vault
    runtime = HarnessRuntime.load(project)
    out = record_ingest(runtime, [Chunk("c", "d", "a.txt", "A", "text", 0, 4)])
    assert out["vault_skipped"] == 1 and out["vault_notes"] == 0


# -- T13 ---------------------------------------------------------------------------------------
def test_per_user_opt_out_in_settings(project, tmp_path):
    from laris.shared.harness.prefs import UserPrefs

    prefs = UserPrefs(tmp_path / "settings.json")
    prefs.update({"vault_record": False})
    runtime = HarnessRuntime.load(project, user_layer=prefs.layer())
    assert runtime.config.vault.auto_record is False
    assert record_ingest(runtime, [Chunk("c", "d", "a.txt", "A", "text", 0, 4)]) == {}
    assert not (project / "vault" / "Sources").exists()


# -- T14 ---------------------------------------------------------------------------------------
def test_memory_lives_in_the_vault_and_prompt_stays_within_its_limit(tmp_path):
    vault = ProjectVault(tmp_path, VaultConfig())
    assert write_memory(vault, "decisions", "chose X")[0] == "created"
    assert write_memory(vault, "decisions", "then Y")[0] == "appended"
    note = (tmp_path / "vault" / "Memory" / "decisions (memory).md").read_text()
    assert "chose X" in note and "then Y" in note
    assert write_memory(vault, "decisions", "fresh", append=False)[0] == "created"
    for i in range(30):
        write_memory(vault, f"topic-{i}", "x" * 300)
    assert len(read_memory(vault, tmp_path / "none", 500)) <= 500
    assert "decisions: fresh" in read_memory(vault, tmp_path / "none", 100000)


def test_memory_migration_is_idempotent_lossless_and_reversible(tmp_path):
    legacy = tmp_path / ".laris" / "memory"
    legacy.mkdir(parents=True)
    (legacy / "a.md").write_text("alpha text")
    (legacy / "b.md").write_text("beta text")
    (legacy / "MEMORY.md").write_text("- index line")
    vault = ProjectVault(tmp_path, VaultConfig())
    first = migrate(vault, legacy)
    assert set(first) == {"a", "b"} and migrate(vault, legacy) == first
    text = read_memory(vault, legacy, 10000)
    assert "alpha text" in text and "beta text" in text and "- index line" in text
    assert (legacy / "a.md").read_text() == "alpha text"  # originals untouched
    assert "a.md" not in text  # migrated files are not listed twice
    assert undo_migration(vault, legacy) == 2
    assert not list((tmp_path / "vault" / "Memory").glob("*.md"))
    assert "Files: a.md, b.md" in read_memory(vault, legacy, 10000)


# -- T26 ---------------------------------------------------------------------------------------
def test_answer_note_stores_the_brain_path_and_links_only_notes_that_exist(project):
    from laris.client.vault.hooks import record_turn

    runtime = HarnessRuntime.load(project)
    vault = ProjectVault(project, runtime.config.vault)
    vault.record_source("A (source)", "a.txt", 1, ["Perovskite"], "text")
    history = [
        {"role": "user", "content": "What is perovskite?"},
        {"role": "assistant", "content": "A crystal structure. [nguồn #1]"},
    ]
    turn = {
        "status": "completed",
        "brain_trace": ["Brain Index", "Research Hub", "Verify playbook"],
        "vault_notes": ["Perovskite", "A note that does not exist"],
    }
    out = record_turn(runtime, "sess-0001", history, turn)
    assert out["vault_status"] == "created"
    index = VaultIndex.build(project / "vault")
    note = next(n for n in index.notes.values() if n.props.get("type") == "answer")
    assert "Brain path: Brain Index → Research Hub → Verify playbook" in note.body
    assert "[[Perovskite]]" in note.body and "does not exist" not in note.body
    assert note.props["notes_used"] == ["[[Perovskite]]"]
    assert lint_schema(index) == [] and index.unresolved == []
    assert "Verify playbook" in note.body and "Brain Index.md" not in "".join(index.notes)


# -- T27 (hook) ----------------------------------------------------------------------------------
def test_source_note_gets_bibliography_from_the_text(project):
    runtime = HarnessRuntime.load(project)
    text = (
        "Efficient Perovskite Solar Cells with Passivated Interfaces\nMaria Curie; Niels Bohr\n"
        "Published: 12 May 2019\nDOI: 10.1000/jap.2019.0042\nAbstract text follows.\n"
    )
    record_ingest(runtime, [Chunk("c1", "d9", "docs/p.txt", "P", text, 0, len(text))])
    note = VaultIndex.build(project / "vault").notes["Sources/p (source).md"]
    assert note.props["doi"] == "10.1000/jap.2019.0042" and note.props["year"] == 2019
    assert note.props["authors"] == ["Maria Curie", "Niels Bohr"]
    plain = "we measured the films.\n"
    record_ingest(runtime, [Chunk("c2", "d10", "docs/q.txt", "Q", plain, 0, len(plain))])
    other = VaultIndex.build(project / "vault").notes["Sources/q (source).md"]
    assert not {"doi", "year", "authors", "arxiv", "bib_title"} & set(other.props)
