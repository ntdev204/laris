"""Scholarly knowledge graph: nodes from the vault and the corpus, edges with provenance.

Sources of edges: links between notes (the note that holds the link is the provenance), claim,
limitation and entity notes (their character span in the source document), and resolved citations
(the reference line). Every edge has provenance; an edge without it is rejected. Queries are
deterministic; exports are JSON, GraphML and an Obsidian canvas (JSON Canvas 1.0, write-only).
"""

import json
import re
import xml.etree.ElementTree as ET
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from vault.index import VaultIndex
from vault.notes import link_name

_MENTION = re.compile(r"\[\[([^\]|#]+)\]\]\s*\[(\d+)-(\d+)\]")
GRAPHML_NS = "http://graphml.graphdrawing.org/xmlns"


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    relation: str
    provenance: Tuple[Tuple[str, str], ...]  # sorted key/value pairs, hashable

    def prov(self) -> Dict[str, str]:
        return dict(self.provenance)


def _prov(**items: Any) -> Tuple[Tuple[str, str], ...]:
    return tuple(sorted((k, str(v)) for k, v in items.items() if v not in (None, "")))


@dataclass
class Graph:
    nodes: Dict[str, Dict[str, str]] = field(default_factory=dict)  # id -> {label, kind}
    edges: List[Edge] = field(default_factory=list)

    def add_node(self, node_id: str, label: str, kind: str) -> None:
        self.nodes.setdefault(node_id, {"label": label, "kind": kind})

    def add_edge(self, source: str, target: str, relation: str, **provenance: Any) -> None:
        if source not in self.nodes or target not in self.nodes or source == target:
            return
        prov = _prov(**provenance)
        if not prov:
            raise ValueError("an edge needs provenance")
        edge = Edge(source, target, relation, prov)
        if edge not in self.edges:
            self.edges.append(edge)

    def finish(self) -> "Graph":
        self.edges.sort(key=lambda e: (e.source, e.target, e.relation, e.provenance))
        return self

    # -- validation ------------------------------------------------------------------------------
    def problems(self) -> List[str]:
        found = []
        for e in self.edges:
            if not e.provenance:
                found.append(f"edge {e.source}->{e.target} has no provenance")
            if e.source not in self.nodes or e.target not in self.nodes:
                found.append(f"edge {e.source}->{e.target} points to a missing node")
        return found

    # -- queries ---------------------------------------------------------------------------------
    def find(self, text: str, limit: int = 10) -> List[str]:
        low = text.lower()
        hits = [n for n, d in self.nodes.items() if low in d["label"].lower() or low in n.lower()]
        return sorted(hits, key=lambda n: (self.nodes[n]["label"].lower() != low, n))[:limit]

    def neighbours(
        self, node: str, relation: str = "", direction: str = "both"
    ) -> List[Dict[str, Any]]:
        out = []
        for e in self.edges:
            if relation and e.relation != relation:
                continue
            if direction in ("out", "both") and e.source == node:
                out.append(self._row(e, e.target, "out"))
            if direction in ("in", "both") and e.target == node:
                out.append(self._row(e, e.source, "in"))
        return sorted(out, key=lambda r: (r["node"], r["relation"], r["direction"]))

    def _row(self, e: Edge, other: str, direction: str) -> Dict[str, Any]:
        return {
            "node": other,
            "label": self.nodes[other]["label"],
            "relation": e.relation,
            "direction": direction,
            "provenance": e.prov(),
        }

    def path(self, source: str, target: str) -> Optional[List[str]]:
        if source not in self.nodes or target not in self.nodes:
            return None
        adjacent: Dict[str, List[str]] = {}
        for e in self.edges:
            adjacent.setdefault(e.source, []).append(e.target)
            adjacent.setdefault(e.target, []).append(e.source)
        previous: Dict[str, Optional[str]] = {source: None}
        queue = deque([source])
        while queue:
            node = queue.popleft()
            if node == target:
                break
            for other in sorted(set(adjacent.get(node, []))):
                if other not in previous:
                    previous[other] = node
                    queue.append(other)
        if target not in previous:
            return None
        route: List[str] = []
        cursor: Optional[str] = target
        while cursor is not None:
            route.append(cursor)
            cursor = previous[cursor]
        return route[::-1]

    def subgraph(self, centre: str, depth: int = 1) -> "Graph":
        keep = {centre} if centre in self.nodes else set()
        frontier = set(keep)
        for _ in range(depth):
            frontier = {
                o
                for e in self.edges
                for n in frontier
                for o in ((e.target,) if e.source == n else (e.source,) if e.target == n else ())
            } - keep
            keep |= frontier
        sub = Graph({n: dict(self.nodes[n]) for n in sorted(keep)})
        sub.edges = [e for e in self.edges if e.source in keep and e.target in keep]
        return sub

    def stats(self) -> Dict[str, Any]:
        kinds: Dict[str, int] = {}
        for d in self.nodes.values():
            kinds[d["kind"]] = kinds.get(d["kind"], 0) + 1
        relations: Dict[str, int] = {}
        for e in self.edges:
            relations[e.relation] = relations.get(e.relation, 0) + 1
        return {
            "nodes": len(self.nodes),
            "edges": len(self.edges),
            "node_kinds": dict(sorted(kinds.items())),
            "relations": dict(sorted(relations.items())),
        }

    # -- exports ---------------------------------------------------------------------------------
    def to_json(self) -> str:
        data = {
            "nodes": [{"id": n, **d} for n, d in sorted(self.nodes.items())],
            "edges": [
                {"source": e.source, "target": e.target, "relation": e.relation,
                 "provenance": e.prov()}
                for e in self.edges
            ],
        }  # fmt: skip
        return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)

    def to_graphml(self) -> str:
        root = ET.Element("graphml", xmlns=GRAPHML_NS)
        for key_id, target, name in (
            ("label", "node", "label"),
            ("kind", "node", "kind"),
            ("relation", "edge", "relation"),
            ("provenance", "edge", "provenance"),
        ):
            ET.SubElement(
                root, "key", {"id": key_id, "for": target, "attr.name": name, "attr.type": "string"}
            )
        graph = ET.SubElement(root, "graph", id="G", edgedefault="directed")
        for node_id, d in sorted(self.nodes.items()):
            node = ET.SubElement(graph, "node", id=node_id)
            ET.SubElement(node, "data", key="label").text = d["label"]
            ET.SubElement(node, "data", key="kind").text = d["kind"]
        for i, e in enumerate(self.edges):
            edge = ET.SubElement(graph, "edge", id=f"e{i}", source=e.source, target=e.target)
            ET.SubElement(edge, "data", key="relation").text = e.relation
            ET.SubElement(edge, "data", key="provenance").text = json.dumps(
                e.prov(), ensure_ascii=False, sort_keys=True
            )
        ET.indent(root)
        return ET.tostring(root, encoding="unicode", xml_declaration=False)

    def to_canvas(self, columns: int = 5) -> str:
        """JSON Canvas 1.0 (jsoncanvas.org): text nodes on a grid, edges labelled by relation.
        LARIS writes canvases for Obsidian to open; it never reads them."""
        ids = {n: f"n{i}" for i, n in enumerate(sorted(self.nodes))}
        nodes = []
        for i, node_id in enumerate(sorted(self.nodes)):
            d = self.nodes[node_id]
            nodes.append(
                {
                    "id": ids[node_id],
                    "type": "text",
                    "text": f"**{d['label']}**\n{d['kind']}",
                    "x": (i % columns) * 340,
                    "y": (i // columns) * 180,
                    "width": 300,
                    "height": 120,
                }
            )
        edges = [
            {"id": f"e{i}", "fromNode": ids[e.source], "toNode": ids[e.target], "label": e.relation}
            for i, e in enumerate(self.edges)
        ]
        return json.dumps({"nodes": nodes, "edges": edges}, ensure_ascii=False, indent=2)


def build(
    index: VaultIndex,
    citation_edges: Sequence[Tuple[str, str, str]] = (),
    doc_nodes: Optional[Mapping[str, str]] = None,
) -> Graph:
    """Graph of the vault. `citation_edges` are (citing doc id, cited doc id, reference line);
    `doc_nodes` maps a document id to the Source note that stands for it."""
    graph = Graph()
    for path, note in sorted(index.notes.items()):
        graph.add_node(path, note.title, str(note.props.get("type") or "note"))
    for path, note in sorted(index.notes.items()):
        for link in note.links:
            target, status = index.resolve(link, path)
            if status == "ok" and target:
                graph.add_edge(
                    path, target, link.prop or "links_to", origin="vault link", note=path
                )
        kind = str(note.props.get("type", ""))
        if kind in {"claim", "limitation"} and note.props.get("source_ref"):
            target_note = index.find(link_name(str(note.props["source_ref"])))
            if target_note is not None:
                graph.add_edge(
                    path,
                    target_note.path,
                    "stated_in",
                    origin="extraction",
                    note=path,
                    doc_id=note.props.get("doc_id"),
                    char_start=note.props.get("char_start"),
                    char_end=note.props.get("char_end"),
                )
        if kind in {"method", "dataset", "metric"}:
            for title, start, end in _MENTION.findall(note.body):
                found = index.find(title)
                if found is not None:
                    graph.add_edge(
                        path,
                        found.path,
                        "mentioned_in",
                        origin="extraction",
                        note=path,
                        char_start=start,
                        char_end=end,
                    )
    mapping = dict(doc_nodes or {})
    for citing, cited, reference in citation_edges:
        for doc in (citing, cited):
            if mapping.get(doc, f"doc:{doc}") not in graph.nodes:
                node = mapping.get(doc, f"doc:{doc}")
                graph.add_node(node, doc, "document")
        graph.add_edge(
            mapping.get(citing, f"doc:{citing}"),
            mapping.get(cited, f"doc:{cited}"),
            "cites",
            origin="citation",
            reference=reference[:200],
        )
    return graph.finish()
