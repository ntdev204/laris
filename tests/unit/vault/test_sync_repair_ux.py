import json
import random
import re
from pathlib import Path

from cli.client import COMMANDS as CLIENT_COMMANDS
from cli.main import main
from config.runtime_schemas import VaultConfig
from vault.index import VaultIndex
from vault.project import ProjectVault
from vault.repair import accept_edits, backups, find_conflicts, repair, restore
from vault.search import NoteSearch

REPO = Path(__file__).resolve().parents[3]


def edit_block(path: Path, old: str, new: str) -> None:
    path.write_text(path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")


# -- T16 ---------------------------------------------------------------------------------------
def test_interleaved_user_and_system_edits_never_lose_user_text(tmp_path):
    vault = ProjectVault(tmp_path, VaultConfig())
    rng = random.Random(3)
    path = None
    user_lines = []
    for step in range(40):
        result = vault.record_concept("Topic", f"Source {step} (source)")
        path = vault.root / result.note
        if rng.random() < 0.5:  # the person adds text outside the block, or inside it
            line = f"my note {step}"
            user_lines.append(line)
            path.write_text(path.read_text(encoding="utf-8") + f"\n{line}\n", encoding="utf-8")
        if rng.random() < 0.15:
            edit_block(path, "Mentioned in", "HAND EDIT Mentioned in")
            vault.record_concept("Topic", "Later (source)")  # conflict: must not overwrite
            assert "HAND EDIT" in path.read_text(encoding="utf-8")
            accept_edits(vault)
    text = path.read_text(encoding="utf-8")
    assert all(line in text for line in user_lines)


def test_sync_reports_conflicts_and_accept_lets_the_system_write_again(tmp_path):
    vault = ProjectVault(tmp_path, VaultConfig())
    note = vault.root / vault.record_concept("Topic", "A (source)").note
    edit_block(note, "Mentioned in", "I changed")
    assert [c.block for c in find_conflicts(vault.root)] == ["mentions"]
    assert vault.record_concept("Topic", "B (source)").status == "conflict"
    assert accept_edits(vault) == 1 and find_conflicts(vault.root) == []
    assert vault.record_concept("Topic", "B (source)").status == "updated"
    assert "I changed" in note.read_text(encoding="utf-8") or "B (source)" in note.read_text()


def test_repair_is_idempotent_and_restores_from_backup(tmp_path):
    vault = ProjectVault(tmp_path, VaultConfig())
    vault.record_concept("Topic", "A (source)")
    vault.record_concept("Topic", "B (source)")  # a backup of the first version exists
    note = vault.root / "Concepts" / "Topic.md"
    broken = note.read_text(encoding="utf-8").replace("<!-- laris:end mentions -->", "")
    note.write_text(broken, encoding="utf-8")
    (vault.root / "Concepts" / ".laris-x.tmp").write_text("junk")
    first = repair(vault)
    assert first.closed_blocks == 1 and first.temp_files == 1
    assert "<!-- laris:end mentions -->" in note.read_text(encoding="utf-8")
    snapshot = {p: p.read_bytes() for p in vault.root.rglob("*") if p.is_file()}
    second = repair(vault)
    assert (second.closed_blocks, second.temp_files) == (0, 0)
    after = {p: p.read_bytes() for p in vault.root.rglob("*") if p.is_file()}
    assert {p: b for p, b in after.items() if "backups" not in p.as_posix()} == {
        p: b for p, b in snapshot.items() if "backups" not in p.as_posix()
    }
    assert backups(vault, "Concepts/Topic.md")
    old = restore(vault, "Concepts/Topic.md", 0)
    assert old and "B (source)" not in note.read_text(encoding="utf-8")
    assert restore(vault, "Nothing.md") is None


# -- T17 ---------------------------------------------------------------------------------------
def test_search_show_graph_commands(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    vault = ProjectVault(tmp_path, VaultConfig())
    vault.record_source("Perovskite paper (source)", "p.txt", 3, ["perovskite"], "solar cells")
    vault.refresh_index()
    assert main(["vault", "search", "perovskite"]) == 0
    assert "Sources/Perovskite paper (source).md" in capsys.readouterr().out
    assert main(["vault", "show", "Perovskite paper (source)"]) == 0
    assert "Source file" in capsys.readouterr().out
    assert main(["vault", "graph", "--format", "json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert "Sources/Perovskite paper (source).md" in data["nodes"] and data["edges"]
    assert main(["vault", "sync"]) == 0 and main(["vault", "repair"]) == 0
    assert main(["vault", "check"]) == 0


def test_note_search_is_deterministic_and_ranks_titles(tmp_path):
    vault = ProjectVault(tmp_path, VaultConfig())
    vault.record_concept("Perovskite", "A (source)")
    vault.record_concept("Silicon", "B (source)")
    index = VaultIndex.build(vault.root)
    first = NoteSearch(index).search("perovskite")
    assert first == NoteSearch(index).search("perovskite")
    assert first[0].path == "Concepts/Perovskite.md"


def test_guide_lists_every_vault_command_and_chat_command():
    text = (REPO / ".laris" / "help" / "how-to-use.md").read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if ln.startswith("laris vault")]
    for name in CLIENT_COMMANDS["vault"]:
        assert any(re.search(rf"\b{re.escape(name)}\b", ln) for ln in lines), name
    assert "/vault" in text
