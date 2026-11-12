"""Tools for scholarly analytics: literature mining, citations, knowledge graph.

Read-only tools return their result with the scope it covers; `save_analysis` writes an Analysis
note into the project vault and therefore asks for approval like any other write.
"""

import json
from typing import Any, Callable, Dict, List

from laris.client.agent.tools import ToolExecutionError, ToolSpec, schema
from laris.client.application.service import SearchService
from laris.shared.harness.runtime import HarnessRuntime
from laris.shared.scholarly import citations, kg, mining
from laris.shared.scholarly.mining import Doc, docs_from_chunks

VAULT_FOLDERS = (
    "Sources",
    "Concepts",
    "Claims",
    "Questions",
    "Memory",
    "Analyses",
    "Knowledge",
    "Decisions",
)  # never _inbox
KG_ACTIONS = ("stats", "find", "neighbours", "path", "subgraph", "export")
EXPORT_CHARS = 20000
KINDS = ("overview", "trends", "duplicates", "groups")
CITATION_KINDS = ("summary", "edges", "cocitation", "coupling", "centrality", "unresolved")


def corpus_docs(service: SearchService) -> List[Doc]:
    return docs_from_chunks(service.workspace.load())


def _run(kind: str, docs: List[Doc], args: Dict[str, Any]) -> Dict[str, Any]:
    if kind == "overview":
        return mining.overview(docs)
    if kind == "trends":
        return mining.term_trends(docs, int(args.get("top", 10)), int(args.get("min_docs", 2)))
    if kind == "duplicates":
        return mining.near_duplicates(docs, float(args.get("threshold", 0.8)))
    if kind == "groups":
        return mining.group_documents(docs, float(args.get("threshold", 0.25)))
    raise ToolExecutionError("invalid_arguments", f"kind must be one of: {', '.join(KINDS)}")


def scholarly_specs(service: SearchService, rt: HarnessRuntime) -> tuple:
    def need_docs() -> List[Doc]:
        docs = corpus_docs(service)
        if not docs:
            raise ToolExecutionError("empty_corpus", "no documents yet; ingest some first")
        return docs

    def make(kind: str) -> Callable[[Dict[str, Any]], Any]:
        return lambda args: _run(kind, need_docs(), args)

    def save_analysis(args: Dict[str, Any]) -> Any:
        from laris.client.vault.hooks import project_vault
        from laris.shared.vault.project import source_title

        kind = str(args.get("kind", ""))
        docs = need_docs()
        result = _run(kind, docs, args)
        scope = ", ".join(f"{k}={v}" for k, v in result["scope"].items())
        text = mining.to_markdown(kind, result)
        sources = [source_title(d.source) for d in docs]
        name = str(args.get("name") or f"{kind} analysis")
        saved = project_vault(rt).record_analysis(name, scope, rt.redactor.redact(text)[0], sources)
        if saved.status in {"skipped", "conflict"}:
            raise ToolExecutionError("not_saved", saved.reason or "the note was edited by hand")
        return {"note": saved.note, "status": saved.status, "scope": result["scope"]}

    def citation_graph(args: Dict[str, Any]) -> Any:
        kind = str(args.get("kind", "summary"))
        if kind not in CITATION_KINDS:
            raise ToolExecutionError(
                "invalid_arguments", f"kind must be one of: {', '.join(CITATION_KINDS)}"
            )
        return citations.summary(citations.analyse(need_docs()), kind)

    def build_kg() -> kg.Graph:
        from laris.shared.vault.index import VaultIndex
        from laris.shared.vault.project import source_title

        docs = corpus_docs(service)
        report = citations.analyse(docs) if docs else None
        root = rt.root / rt.config.vault.dir
        index = VaultIndex.build(root) if root.is_dir() else VaultIndex(root)
        mapping = {d.doc_id: f"Sources/{source_title(d.source)}.md" for d in docs}
        return kg.build(index, report.triples() if report else (), mapping)

    def kg_query(args: Dict[str, Any]) -> Any:
        action = str(args.get("action", "stats"))
        if action not in KG_ACTIONS:
            raise ToolExecutionError(
                "invalid_arguments", f"action must be one of: {', '.join(KG_ACTIONS)}"
            )
        graph = build_kg()
        node = str(args.get("node", ""))
        node_id = graph.find(node, 1)[0] if node and graph.find(node, 1) else node
        if action == "stats":
            return graph.stats()
        if action == "find":
            return {"nodes": [{"id": n, **graph.nodes[n]} for n in graph.find(node, 10)]}
        if action == "neighbours":
            return {
                "node": node_id,
                "neighbours": graph.neighbours(node_id, args.get("relation", "")),
            }
        if action == "path":
            target = str(args.get("target", ""))
            end = graph.find(target, 1)[0] if graph.find(target, 1) else target
            return {"path": graph.path(node_id, end)}
        if action == "subgraph":
            return json.loads(graph.subgraph(node_id, int(args.get("depth", 1))).to_json())
        fmt = str(args.get("format", "json"))
        text = {"json": graph.to_json, "graphml": graph.to_graphml, "canvas": graph.to_canvas}.get(
            fmt, graph.to_json
        )()
        return {
            "format": fmt,
            "content": text[:EXPORT_CHARS],
            "truncated": len(text) > EXPORT_CHARS,
            "chars": len(text),
        }

    def search_vault(args: Dict[str, Any]) -> Any:
        from laris.shared.vault.index import VaultIndex
        from laris.shared.vault.retrieval import GraphRetriever, estimate_tokens

        root = rt.root / rt.config.vault.dir
        if not root.is_dir():
            raise ToolExecutionError("no_vault", "no project vault yet; ingest a document first")
        index = VaultIndex.build(root)
        found = GraphRetriever(index, VAULT_FOLDERS).retrieve(
            str(args["query"]), min(int(args.get("limit", 6)), 12)
        )
        rows = []
        for item in found:
            note = index.notes[item.path]
            snippet = " ".join(note.body.split())[:300]
            rows.append(
                {
                    "note": note.title,
                    "type": note.props.get("type", ""),
                    "score": item.score,
                    "via": item.via,
                    "seed": index.notes[item.seed].title if item.seed in index.notes else "",
                    "snippet": snippet,
                }
            )
        return {"results": rows, "tokens": estimate_tokens(" ".join(r["snippet"] for r in rows))}

    num = {"type": "number"}
    return (
        ToolSpec(
            "search_vault",
            "Search the project vault (notes, entities, claims) with link-aware ranking; each "
            "result says whether it matched the words or came in through a link.",
            schema({"query": {"type": "string"}, "limit": {"type": "integer"}}, ["query"]),
            search_vault,
            untrusted=True,
        ),
        ToolSpec(
            "kg_query",
            "Query the scholarly knowledge graph (notes, entities with spans, citations). Every "
            "edge carries its provenance. Actions: stats, find, neighbours, path, subgraph, "
            "export.",
            schema(
                {
                    "action": {"type": "string", "enum": list(KG_ACTIONS)},
                    "node": {"type": "string"},
                    "target": {"type": "string"},
                    "relation": {"type": "string"},
                    "depth": {"type": "integer"},
                    "format": {"type": "string", "enum": ["json", "graphml", "canvas"]},
                }
            ),
            kg_query,
        ),
        ToolSpec(
            "citation_graph",
            "Citation graph of the corpus: edges between ingested documents, co-citation, "
            "coupling, centrality, and the references that could not be resolved (listed, never "
            "guessed).",
            schema({"kind": {"type": "string", "enum": list(CITATION_KINDS)}}),
            citation_graph,
        ),
        ToolSpec(
            "corpus_overview",
            "Statistics of the whole corpus (documents, years, DOIs) with the scope stated.",
            schema({}),
            make("overview"),
        ),
        ToolSpec(
            "term_trends",
            "Documents per year that contain the most common terms (undated ones excluded).",
            schema({"top": {"type": "integer"}, "min_docs": {"type": "integer"}}),
            make("trends"),
        ),
        ToolSpec(
            "find_duplicates",
            "Near-duplicate document pairs (shingle similarity at or above the threshold).",
            schema({"threshold": num}),
            make("duplicates"),
        ),
        ToolSpec(
            "group_documents",
            "Group similar documents (TF-IDF cosine at or above the threshold) with label terms.",
            schema({"threshold": num}),
            make("groups"),
        ),
        ToolSpec(
            "save_analysis",
            "Compute an analysis (overview, trends, duplicates, groups) and save it as an Analysis "
            "note in the project vault (needs approval).",
            schema(
                {
                    "kind": {"type": "string", "enum": list(KINDS)},
                    "name": {"type": "string"},
                    "threshold": num,
                    "top": {"type": "integer"},
                },
                ["kind"],
            ),
            save_analysis,
            writes=True,
        ),
    )
