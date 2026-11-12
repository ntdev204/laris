"""The golden fixture vault: one fixed expectation for every link form (spec: vault format 7)."""

from laris.shared.vault.index import VaultIndex
from tests.unit.conftest import REPO

FIXTURE = REPO / "tests" / "fixtures" / "vault"


def test_golden_fixture_index():
    index = VaultIndex.build(FIXTURE)
    assert sorted(index.notes) == [
        "Alt/Twin.md",
        "Code/Fenced.md",
        "Lonely.md",
        "Notes/Alpha.md",
        "Notes/Beta.md",
        "Notes/Gamma.md",
        "Notes/Twin.md",
    ]  # `.obsidian` is ignored
    alpha = index.notes["Notes/Alpha.md"]
    forms = {
        (link.target, link.heading, link.alias, link.embed, link.source) for link in alpha.links
    }
    assert ("Beta", "", "", False, "property") in forms
    assert ("Gamma", "Results", "", False, "body") in forms
    assert ("Gamma", "^key", "", False, "body") in forms
    assert ("Beta", "", "the second note", False, "body") in forms
    assert ("Beta", "", "", True, "body") in forms
    assert ("Gamma", "", "", False, "body") in forms  # the Markdown link form
    assert alpha.tags == {"physics", "review/2026", "inline", "topic/sub-topic"}
    assert sorted(index.unresolved) == [("Notes/Alpha.md", "Missing Note")]
    assert index.ambiguous == [("Notes/Alpha.md", "Twin")]
    assert [t for t, _ in index.outgoing("Notes/Alpha.md")] == ["Notes/Beta.md", "Notes/Gamma.md"]
    assert index.backlinks("Notes/Gamma.md") == ["Notes/Alpha.md"]


def test_code_and_comments_are_not_links_and_orphans_are_found():
    index = VaultIndex.build(FIXTURE)
    fenced = index.notes["Code/Fenced.md"]
    assert [link.target for link in fenced.links] == ["Alpha"]
    assert fenced.tags == set()
    assert index.orphans() == ["Alt/Twin.md", "Lonely.md", "Notes/Twin.md"]
