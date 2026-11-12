import json
import threading
from dataclasses import asdict

from laris.client.application.service import SearchService
from laris.client.application.workspace import Workspace, chunks_from_text

DOCS = {
    "solar.txt": "Perovskite solar cells reach high efficiency. Silicon cells are cheaper.",
    "graphene.txt": "Graphene conducts electricity very well and is a single carbon layer.",
    "bio.txt": "Protein folding depends on amino acid sequence and the cellular environment.",
}


def _chunks():
    return [c for name, text in DOCS.items() for c in chunks_from_text(name, text)]


def test_rankings_are_identical_before_and_after_the_move(tmp_path):
    legacy = tmp_path / "old"
    legacy.mkdir()
    chunks = _chunks()
    (legacy / "chunks.jsonl").write_text(
        "\n".join(json.dumps(asdict(c)) for c in chunks) + "\n", encoding="utf-8"
    )
    imported = SearchService(Workspace(legacy))  # imports the JSONL once
    fresh = Workspace(tmp_path / "new")
    fresh.add(chunks)
    added = SearchService(fresh)
    assert [c.chunk_id for c in imported.workspace.load()] == [c.chunk_id for c in chunks]
    for query in ("graphene carbon", "solar efficiency", "protein sequence"):
        a, b = imported.search(query, top_k=3), added.search(query, top_k=3)
        assert [h["chunk_id"] for h in a["hits"]] == [h["chunk_id"] for h in b["hits"]]


def test_two_concurrent_ingests_lose_nothing(tmp_path):
    ws = Workspace(tmp_path / "ws")
    service = SearchService(ws)

    def ingest(n):
        for i in range(10):
            service.ingest(chunks_from_text(f"d{n}-{i}.txt", f"document {n} number {i} text"))

    threads = [threading.Thread(target=ingest, args=(n,)) for n in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len({c.doc_id for c in ws.load()}) == 20


def test_vectors_are_cached_by_passage_and_model(tmp_path):
    calls = []

    def embed(texts):
        calls.append(len(texts))
        return [[float(len(t)), 1.0] for t in texts]

    ws = Workspace(tmp_path / "ws")
    ws.add(_chunks())
    service = SearchService(ws, embedder=embed, model_id="m1")
    service.build_dense_index()
    assert sum(calls) == 3 and service.status()["dense_ready"]
    ws.add(chunks_from_text("new.txt", "a new passage"))
    assert not SearchService(ws, embedder=embed, model_id="m1").status()["dense_ready"]
    service.build_dense_index()
    assert sum(calls) == 4  # only the new passage was embedded
    assert not SearchService(ws, embedder=embed, model_id="m2").status()["dense_ready"]
