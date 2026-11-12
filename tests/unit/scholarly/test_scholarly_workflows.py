"""T31: the research workflows run with a scripted provider and use their tools and the brain."""

from laris.client.agent.builtin_tools import build_registry
from laris.client.agent.loop import AgentSession
from laris.client.agent.provider import AssistantTurn, ChatProvider, ToolCall
from laris.client.agent.tools import Sandbox
from laris.client.application.service import SearchService
from laris.client.application.workspace import Workspace, chunks_from_text
from laris.client.vault.hooks import record_ingest
from laris.shared.harness.runtime import HarnessRuntime
from tests.unit.scholarly.test_citations import D1, D2, D3


class Scripted(ChatProvider):
    def __init__(self, turns):
        self.turns, self.seen, self.messages = list(turns), [], []

    def chat(self, messages, tools):
        self.seen.append([t["function"]["name"] for t in tools])
        self.messages.append(list(messages))
        return self.turns.pop(0)


def setup(project, tmp_path):
    rt = HarnessRuntime.load(project)
    service = SearchService(Workspace(tmp_path / "ws"))
    registry = build_registry(service, Sandbox([project], tmp_path / "o", policy=rt.paths), rt)
    for name, text in (("d1", D1), ("d2", D2), ("d3", D3)):
        chunks = chunks_from_text(f"p/{name}.txt", text, name)
        service.ingest(chunks)
        record_ingest(rt, chunks)
    return rt, registry


def run(rt, registry, provider, flow, text):
    spec = rt.workflows().get(flow)
    session = AgentSession(provider, registry, rt, approve=lambda n, a: False)
    return session, list(session.send(text, workflow=(spec, text)))


def call(i, name, args=None):
    return AssistantTurn(None, [ToolCall(f"c{i}", name, args or {})])


def results(events):
    return [e["result"] for e in events if e["type"] == "tool_result"]


LIT = (
    "Scope: 3 documents. Findings: none. Duplicates: none. Groups: none. Caveats: none. "
    "Sources: none."
)
CIT = (
    "Scope: 3. Citation structure: one edge. Influential documents: d2. "
    "Unresolved references: some. Caveats: none. Sources: none."
)
KG = "Graph size: 20 nodes. Connections found: yes. Provenance: notes. Gaps: none. Sources: none."


def test_literature_map_runs_its_tools_and_stays_in_its_allow_list(project, tmp_path):
    rt, registry = setup(project, tmp_path)
    provider = Scripted(
        [
            call(1, "corpus_overview"),
            call(2, "term_trends", {"top": 3}),
            call(3, "write_file", {"path": "x", "content": "y"}),
            AssistantTurn(LIT),
        ]
    )
    _, events = run(rt, registry, provider, "literature-map", "Hãy lập bản đồ tài liệu")
    out = results(events)
    assert out[0]["scope"]["documents"] == 3 and out[1]["scope"]["documents_with_year"] == 3
    assert out[2]["error"]["code"] == "tool_not_allowed"
    assert "write_file" not in provider.seen[0] and "corpus_overview" in provider.seen[0]
    assert events[-1]["status"] == "completed"


def test_citation_analysis_reports_edges_and_unresolved(project, tmp_path):
    rt, registry = setup(project, tmp_path)
    provider = Scripted(
        [
            call(1, "citation_graph"),
            call(2, "citation_graph", {"kind": "unresolved"}),
            AssistantTurn(CIT),
        ]
    )
    _, events = run(rt, registry, provider, "citation-analysis", "who cites whom")
    out = results(events)
    assert out[0]["summary"]["edges"] == 3 and out[1]["unresolved"]
    assert events[-1]["status"] == "completed"


def test_kg_explore_returns_edges_with_provenance(project, tmp_path):
    rt, registry = setup(project, tmp_path)
    provider = Scripted(
        [
            call(1, "kg_query", {"action": "stats"}),
            call(2, "kg_query", {"action": "neighbours", "node": "d1 (source)"}),
            AssistantTurn(KG),
        ]
    )
    _, events = run(rt, registry, provider, "kg-explore", "how are d1 and d2 connected")
    out = results(events)
    assert out[0]["edges"] > 0
    assert all(row["provenance"] for row in out[1]["neighbours"])
    assert events[-1]["status"] == "completed"


def test_grounded_qa_gets_the_brain_brief_and_can_search_the_vault(project, tmp_path):
    rt, registry = setup(project, tmp_path)
    provider = Scripted(
        [
            call(1, "search_vault", {"query": "passivation interface perovskite"}),
            AssistantTurn("Assumptions: none. Uncertainties: none. Next step: none. Sources: d2."),
        ]
    )
    _, events = run(rt, registry, provider, "grounded-qa", "Passivation of perovskite interfaces?")
    rows = results(events)[0]["results"]
    assert rows and {r["via"] for r in rows} <= {"bm25", "link"}
    first = provider.messages[0]
    assert any(
        m.get("harness") and "Domain:" in str(m.get("content")) for m in first
    )  # brain brief
    assert "search_vault" in provider.seen[0]
    assert all("_inbox" not in str(r) for r in rows)
