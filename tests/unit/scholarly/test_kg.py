import json
import xml.etree.ElementTree as ET

import pytest

from cli.main import main
from laris.client.agent.builtin_tools import build_registry
from laris.client.agent.tools import Sandbox, ToolExecutionError
from laris.client.application.service import SearchService
from laris.client.application.workspace import Workspace, chunks_from_text
from laris.client.vault.hooks import record_ingest
from laris.shared.harness.runtime import HarnessRuntime
from laris.shared.policy.workflows import WorkflowLibrary
from laris.shared.scholarly import kg
from laris.shared.scholarly.kg import Graph
from laris.shared.vault.index import VaultIndex
from tests.unit.scholarly.test_citations import D1, D2, D3
from tests.unit.vault.test_entities import DOC1


def populated(project, tmp_path):
    rt = HarnessRuntime.load(project)
    service = SearchService(Workspace(tmp_path / "ws"))
    registry = build_registry(service, Sandbox(project, tmp_path / "out"), rt)
    for name, text in (("d1", D1), ("d2", D2), ("d3", D3), ("one", DOC1)):
        chunks = chunks_from_text(f"p/{name}.txt", text, name)
        service.ingest(chunks)
        record_ingest(rt, chunks)
    return rt, service, registry


def test_every_edge_has_provenance_and_the_graph_is_consistent(project, tmp_path):
    _, _, registry = populated(project, tmp_path)
    stats = registry.call("kg_query", {"action": "stats"})
    assert stats["nodes"] > 10 and stats["edges"] > 10
    assert {"cites", "stated_in", "mentioned_in"} <= set(stats["relations"])
    rt = HarnessRuntime.load(project)
    index = VaultIndex.build(project / "vault")
    graph = kg.build(index)
    assert graph.problems() == []
    assert all(e.provenance for e in graph.edges)
    with pytest.raises(ValueError):
        graph.add_edge(next(iter(graph.nodes)), list(graph.nodes)[1], "x")  # no provenance
    claim_edges = [e for e in graph.edges if e.relation == "stated_in"]
    assert claim_edges and {"char_start", "char_end", "doc_id"} <= set(claim_edges[0].prov())
    assert rt.config.vault.dir == "vault"


def test_queries_are_deterministic_and_show_provenance(project, tmp_path):
    _, _, registry = populated(project, tmp_path)
    cites = registry.call("kg_query", {"action": "neighbours", "node": "d1 (source)"})
    rows = [r for r in cites["neighbours"] if r["relation"] == "cites"]
    assert (
        rows
        and rows[0]["provenance"]["origin"] == "citation"
        and "Curie" in rows[0]["provenance"]["reference"]
    )
    path = registry.call(
        "kg_query", {"action": "path", "node": "d1 (source)", "target": "d2 (source)"}
    )["path"]
    assert path and path[0].endswith("d1 (source).md") and path[-1].endswith("d2 (source).md")
    assert (
        registry.call(
            "kg_query", {"action": "path", "node": "d1 (source)", "target": "nothing-here"}
        )["path"]
        is None
    )
    sub = registry.call("kg_query", {"action": "subgraph", "node": "d3 (source)", "depth": 1})
    assert len(sub["nodes"]) >= 2 and all(e["provenance"] for e in sub["edges"])
    again = registry.call("kg_query", {"action": "subgraph", "node": "d3 (source)", "depth": 1})
    assert sub == again
    with pytest.raises(ToolExecutionError):
        registry.call("kg_query", {"action": "bogus"})


def test_exports_validate_against_their_formats(project, tmp_path):
    _, _, registry = populated(project, tmp_path)
    graph = kg.build(VaultIndex.build(project / "vault"))
    data = json.loads(graph.to_json())
    assert {n["id"] for n in data["nodes"]} >= {e["source"] for e in data["edges"]}
    root = ET.fromstring(graph.to_graphml())
    ns = {"g": kg.GRAPHML_NS}
    assert root.tag == f"{{{kg.GRAPHML_NS}}}graphml"
    keys = {k.get("id") for k in root.findall("g:key", ns)}
    assert {"label", "kind", "relation", "provenance"} <= keys
    ids = {n.get("id") for n in root.findall("g:graph/g:node", ns)}
    edges = root.findall("g:graph/g:edge", ns)
    assert len(ids) == len(graph.nodes) and len(edges) == len(graph.edges)
    assert all(e.get("source") in ids and e.get("target") in ids for e in edges)
    canvas = json.loads(graph.to_canvas())  # JSON Canvas 1.0
    cids = {n["id"] for n in canvas["nodes"]}
    assert all(
        n["type"] == "text" and {"x", "y", "width", "height", "text"} <= set(n)
        for n in canvas["nodes"]
    )
    assert all(e["fromNode"] in cids and e["toNode"] in cids and e["id"] for e in canvas["edges"])
    assert len(cids) == len(canvas["nodes"])
    out = registry.call("kg_query", {"action": "export", "format": "graphml"})
    assert out["format"] == "graphml" and out["content"].startswith("<graphml")
    assert graph.to_json() == kg.build(VaultIndex.build(project / "vault")).to_json()


def test_cli_exports_a_canvas_file(project, tmp_path, monkeypatch):
    populated(project, tmp_path)
    monkeypatch.chdir(project)
    target = tmp_path / "graph.canvas"
    assert main(["vault", "graph", "--format", "canvas", "--out", str(target)]) == 0
    assert json.loads(target.read_text())["nodes"]


def test_kg_explore_workflow_uses_real_tools(project, tmp_path):
    rt, _, registry = populated(project, tmp_path)
    spec = WorkflowLibrary(rt.root / ".laris" / "workflows").get("kg-explore")
    assert set(spec.allowed_tools) <= set(registry.tools)
    assert isinstance(Graph().stats(), dict)
