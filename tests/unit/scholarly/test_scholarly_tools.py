import pytest

from laris.client.agent.builtin_tools import build_registry
from laris.client.agent.tools import Sandbox, ToolExecutionError
from laris.client.application.service import SearchService
from laris.client.application.workspace import Workspace, chunks_from_text
from laris.shared.harness.runtime import HarnessRuntime
from laris.shared.policy.workflows import WorkflowLibrary
from laris.shared.vault.index import VaultIndex

PAPER_A = (
    "Efficient Perovskite Solar Cells with Passivated Interfaces\nMaria Curie\n"
    "Published: 1 May 2019\nWe study perovskite solar cell passivation and moisture stability. "
    "Annealing improves crystallinity in perovskite films. " * 3
)
PAPER_B = (
    "Lithium Electrolytes and Interphase Growth in Batteries\nNiels Bohr\n"
    "Published: 3 June 2020\nWe study lithium electrolyte interphase growth during charging. "
    "Cycling degrades the anode in lithium cells. " * 3
)


@pytest.fixture
def tools(project, tmp_path):
    rt = HarnessRuntime.load(project)
    service = SearchService(Workspace(tmp_path / "ws"))
    registry = build_registry(service, Sandbox(project, tmp_path / "out"), rt)
    return rt, service, registry


def test_tools_report_scope_and_fail_clearly_on_an_empty_corpus(tools):
    _, service, registry = tools
    with pytest.raises(ToolExecutionError):
        registry.call("corpus_overview", {})
    service.ingest(chunks_from_text("p/a.txt", PAPER_A, "A"))
    service.ingest(chunks_from_text("p/b.txt", PAPER_B, "B"))
    over = registry.call("corpus_overview", {})
    assert over["scope"]["documents"] == 2 and over["scope"]["year_range"] == [2019, 2020]
    trends = registry.call("term_trends", {"top": 3, "min_docs": 1})
    assert trends["scope"]["documents_with_year"] == 2 and len(trends["terms"]) == 3
    assert registry.call("find_duplicates", {})["pairs"] == []
    groups = registry.call("group_documents", {"threshold": 0.3})
    assert len(groups["groups"]) == 2


def test_save_analysis_writes_a_linked_note_with_its_scope(tools):
    rt, service, registry = tools
    service.ingest(chunks_from_text("p/a.txt", PAPER_A, "A"))
    out = registry.call("save_analysis", {"kind": "overview", "name": "First look"})
    assert out["status"] == "created" and out["note"] == "Analyses/First look.md"
    note = VaultIndex.build(rt.root / "vault").notes[out["note"]]
    assert note.props["type"] == "analysis" and "documents=1" in note.props["scope"]
    assert "Scope: documents: 1" in note.body
    assert registry.tools["save_analysis"].writes is True  # asks for approval
    with pytest.raises(ToolExecutionError):
        registry.call("save_analysis", {"kind": "nonsense"})


def test_literature_map_workflow_is_valid_and_uses_real_tools(tools):
    rt, _, registry = tools
    library = WorkflowLibrary(rt.root / ".laris" / "workflows")
    spec = library.get("literature-map")
    assert set(spec.allowed_tools) <= set(registry.tools) | {"brain_consult"}


def test_citation_graph_tool_and_workflow(tools):
    from tests.unit.scholarly.test_citations import D2, D3

    rt, service, registry = tools
    service.ingest(chunks_from_text("p/d2.txt", D2, "D2"))
    service.ingest(chunks_from_text("p/d3.txt", D3, "D3"))
    summary = registry.call("citation_graph", {})
    assert summary["scope"]["documents"] == 2 and summary["summary"]["edges"] == 1
    edges = registry.call("citation_graph", {"kind": "edges"})["edges"]
    assert len(edges) == 1 and edges[0]["cited"] != edges[0]["citing"]
    assert registry.call("citation_graph", {"kind": "unresolved"})["unresolved"]
    with pytest.raises(ToolExecutionError):
        registry.call("citation_graph", {"kind": "nope"})
    spec = WorkflowLibrary(rt.root / ".laris" / "workflows").get("citation-analysis")
    assert set(spec.allowed_tools) <= set(registry.tools)
