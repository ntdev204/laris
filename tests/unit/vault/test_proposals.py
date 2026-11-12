import hashlib
from pathlib import Path

import pytest

from cli.main import main
from laris.client.vault.hooks import project_vault
from laris.client.vault.proposals import accept, pending, propose, reject
from laris.shared.config.runtime_schemas import VaultConfig
from laris.shared.harness.runtime import HarnessRuntime
from laris.shared.vault.index import VaultIndex
from laris.shared.vault.memory import read_memory
from laris.shared.vault.project import ProjectVault
from laris.shared.vault.search import NoteSearch

REPO = Path(__file__).resolve().parents[3]


def tree_hash(folder: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(folder.rglob("*")):
        if p.is_file():
            h.update(p.relative_to(folder).as_posix().encode() + p.read_bytes())
    return h.hexdigest()


def test_proposals_wait_in_the_inbox_and_are_not_retrieved(tmp_path):
    vault = ProjectVault(tmp_path, VaultConfig())
    vault.record_concept("Perovskite", "A (source)")
    propose(vault, "Use DOI first", "Always resolve the DOI before citing.", "agent")
    assert [p.title for p in pending(vault)] == ["Use DOI first"]
    index = VaultIndex.build(vault.root)
    assert "_inbox/Use DOI first.md" in index.notes
    # retrieval over the vault's working folders never sees the inbox
    searcher = NoteSearch(index, folders=("Sources", "Concepts", "Questions", "Memory"))
    assert searcher.search("resolve DOI citing") == []
    assert "resolve the DOI" not in read_memory(vault, tmp_path / "none", 10000)


def test_accept_moves_into_the_project_vault_and_reject_discards(tmp_path):
    vault = ProjectVault(tmp_path, VaultConfig())
    propose(vault, "Rule one", "Prefer primary sources.", "agent")
    propose(vault, "Rule two", "Skip blog posts.", "agent")
    assert accept(vault, "Rule one").status == "created"
    assert "Prefer primary sources." in read_memory(vault, tmp_path / "none", 10000)
    assert [p.title for p in pending(vault)] == ["Rule two"]
    assert reject(vault, "Rule two") and pending(vault) == []
    assert reject(vault, "Rule two") is False
    with pytest.raises(KeyError):
        accept(vault, "Nope")
    propose(vault, "Rule three", "Keep notes short.", "user")
    assert accept(vault, "Rule three", "decision").note.startswith("Decisions/")


def test_no_runtime_path_writes_to_the_system_brain(project):
    brain = project / ".laris" / "brain"
    before = tree_hash(brain)
    runtime = HarnessRuntime.load(project)
    vault = project_vault(runtime)
    vault.ensure()
    propose(vault, "Learned", "Something learned at runtime.", "agent")
    accept(vault, "Learned", "concept")
    vault.record_memory("m", "x")
    assert tree_hash(brain) == before
    # a vault that overlaps the brain is refused outright
    for folder in (".laris/brain", ".laris", ".laris/brain/sub"):
        cfg = runtime.config.vault.model_copy(update={"dir": folder})
        bad = ProjectVault(project, cfg, protected=[brain])
        assert bad.record_concept("x").status == "skipped"
    assert tree_hash(brain) == before


def test_cli_propose_review_accept_reject(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["vault", "propose", "Idea", "Try BM25 first."]) == 0
    assert main(["vault", "review"]) == 0
    assert "Idea" in capsys.readouterr().out
    assert main(["vault", "accept", "Idea", "--into", "decision"]) == 0
    assert main(["vault", "accept", "Idea"]) == 1
    assert main(["vault", "propose", "Other", "x"]) == 0
    assert main(["vault", "reject", "Other"]) == 0
