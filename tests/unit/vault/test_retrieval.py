import json
from pathlib import Path

from laris.shared.brain import Brain
from laris.shared.vault.index import VaultIndex
from laris.shared.vault.retrieval import (
    GraphRetriever,
    evaluate,
    fuse_with_corpus,
    mrr,
    navigate,
    ndcg_at_k,
    recall_at_k,
    tokens_of,
)
from laris.shared.vault.search import NoteSearch

REPO = Path(__file__).resolve().parents[3]
FIX = REPO / "tests" / "fixtures" / "retrieval"


def load():
    index = VaultIndex.build(FIX / "vault")
    qrels = {q: set(v) for q, v in json.loads((FIX / "qrels.json").read_text()).items()}
    return index, qrels


def test_metrics_on_known_rankings():
    assert recall_at_k(["a", "b", "c"], {"a", "c"}, 2) == 0.5
    assert mrr(["x", "a"], {"a"}) == 0.5 and mrr(["x"], {"a"}) == 0.0
    assert ndcg_at_k(["a", "b"], {"a", "b"}, 2) == 1.0
    assert 0 < ndcg_at_k(["x", "a"], {"a"}, 2) < 1


def test_graph_retrieval_beats_bm25_alone_on_the_fixture_and_is_deterministic():
    index, qrels = load()
    bm25 = NoteSearch(index)
    graph = GraphRetriever(index)
    base = evaluate(qrels, lambda q: [h.path for h in bm25.search(q, 5)])
    expanded = evaluate(qrels, lambda q: [r.path for r in graph.retrieve(q, 5)])
    print("bm25", base, "graph", expanded)  # the measured figures (pytest -s)
    assert expanded["recall@5"] > base["recall@5"]
    assert expanded["mrr"] >= base["mrr"] and expanded["ndcg@5"] >= base["ndcg@5"]
    first = [r for q in sorted(qrels) for r in graph.retrieve(q, 5)]
    assert first == [r for q in sorted(qrels) for r in graph.retrieve(q, 5)]


def test_results_carry_provenance_and_folders_filter():
    index, _ = load()
    results = GraphRetriever(index).retrieve("perovskite solar", 5)
    by_path = {r.path: r for r in results}
    assert by_path["Perovskite solar cells.md"].via == "bm25"
    leaf = by_path["Stability protocol.md"]
    assert leaf.via == "link" and leaf.seed == "Perovskite solar cells.md"
    assert GraphRetriever(index, folders=("Nope",)).retrieve("perovskite solar", 5) == []


def test_fusion_with_the_corpus_search_joins_sources_and_reports_corpus_only_hits():
    index, _ = load()
    notes = GraphRetriever(index).retrieve("perovskite solar", 3)
    fused = fuse_with_corpus(notes, ["docs/other.pdf", "docs/Perovskite solar cells.pdf"], k=6)
    paths = [r.path for r in fused]
    assert "Sources/other (source).md" in paths
    assert fused[0].path == "Perovskite solar cells.md" or fused[0].via in {"bm25", "corpus"}
    assert fused == fuse_with_corpus(
        notes, ["docs/other.pdf", "docs/Perovskite solar cells.pdf"], k=6
    )
    assert tokens_of(notes, index) > 0


def test_navigation_first_on_the_real_brain_and_search_as_fallback(project):
    from laris.shared.config.loader import load_runtime_config

    cfg = load_runtime_config(project).brain
    brain = Brain(project / ".laris" / "brain", cfg)
    nav = navigate(brain, "Hãy xác minh các trích dẫn của bài báo")
    assert nav["mode"] == "navigate" and nav["trace"][0] == cfg.root_note and nav["tokens"] > 0
    miss = navigate(brain, "zzzz qqqq")
    assert miss["mode"] == "search" and miss["tokens"] >= 0
