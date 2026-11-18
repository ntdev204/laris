"""Regenerate the golden file of the retrieval crate from the generation-1 implementation.

    PYTHONPATH=src .venv/bin/python tests/golden/retrieval/generate.py

`cases.json` holds, for the vault in `tests/fixtures/retrieval/vault/`, what generation 1's `NoteSearch`,
`GraphRetriever`, `fuse_with_corpus` and `evaluate` return. `laris-retrieval` must reproduce every number and every
order. The script only reads the fixture and writes one JSON file; it runs no model code.
"""

import json
from pathlib import Path

from laris.shared.vault.index import VaultIndex
from laris.shared.vault.retrieval import (
    GraphRetriever,
    evaluate,
    fuse_with_corpus,
    mrr,
    ndcg_at_k,
    recall_at_k,
)
from laris.shared.vault.search import NoteSearch, tokens

HERE = Path(__file__).parent
FIXTURE = HERE.parent.parent / "fixtures" / "retrieval"

QUERIES = [
    "perovskite solar",
    "silicon heterojunction devices",
    "lithium electrolyte",
    "transformer attention",
    "Perovskite SOLAR cells",
    "stability",
    "encapsulation of cells",
    "wafer",
    "meeting",
    "positional encoding for attention models",
    "nothing matches this zzzz",
    "the of and",
    "Électrolyte lithium",
    "solar-cell/stability_protocol 42",
    "",
]
TOKEN_CASES = ["Hello, World_42!", "ÉLECTROLYTE naïve", "a_b c-d", "٣ ١٢ x²", "", "   "]
CORPUS = [
    ["Papers/Perovskite review.pdf", "Papers/Stability protocol.pdf"],
    ["a/Lithium electrolytes (source).md", "a/Lithium electrolytes (source).md", "b/Other.txt"],
    [],
]


def main() -> None:
    index = VaultIndex.build(FIXTURE / "vault")
    out = {"tokens": [[t, tokens(t)] for t in TOKEN_CASES], "search": [], "graph": [], "fuse": []}
    search = NoteSearch(index)
    for q in QUERIES:
        out["search"].append(
            {"query": q, "hits": [[h.path, h.score] for h in search.search(q, 10)]}
        )
    configs = [
        {"seeds": 5, "link_weight": 0.4, "decay": 0.8},
        {"seeds": 1, "link_weight": 0.4, "decay": 0.8},
        {"seeds": 2, "link_weight": 1.0, "decay": 0.5},
    ]
    for cfg in configs:
        retriever = GraphRetriever(index, **cfg)
        for q in QUERIES:
            for k in (3, 10):
                try:
                    res = retriever.retrieve(q, k)
                except Exception as exc:  # noqa: BLE001
                    raise SystemExit(f"{q!r}: {exc}")
                out["graph"].append(
                    {
                        "config": cfg,
                        "query": q,
                        "k": k,
                        "results": [[r.path, r.score, r.via, r.seed, r.detail] for r in res],
                    }
                )
    base = GraphRetriever(index)
    notes = base.retrieve("perovskite solar", 10)
    for sources in CORPUS:
        for k in (3, 10):
            res = fuse_with_corpus(notes, sources, k)
            out["fuse"].append(
                {
                    "sources": sources,
                    "k": k,
                    "results": [[r.path, r.score, r.via, r.seed, r.detail] for r in res],
                }
            )
    qrels = json.loads((FIXTURE / "qrels.json").read_text(encoding="utf-8"))
    relevant = {q: set(v) for q, v in qrels.items()}
    out["metrics"] = {
        "qrels": qrels,
        "by_graph": evaluate(
            relevant, lambda q: [r.path for r in base.retrieve(q, 10)], 5
        ),
        "by_bm25": evaluate(relevant, lambda q: [h.path for h in search.search(q, 10)], 5),
        "single": [
            {
                "ranked": ["a", "b", "c", "d"],
                "relevant": ["b", "d", "z"],
                "k": 3,
                "recall": recall_at_k(["a", "b", "c", "d"], {"b", "d", "z"}, 3),
                "mrr": mrr(["a", "b", "c", "d"], {"b", "d", "z"}),
                "ndcg": ndcg_at_k(["a", "b", "c", "d"], {"b", "d", "z"}, 3),
            }
        ],
    }
    (HERE / "cases.json").write_text(
        json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print("graph cases", len(out["graph"]), "search", len(out["search"]))


if __name__ == "__main__":
    main()
