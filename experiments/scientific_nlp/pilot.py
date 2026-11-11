"""Bounded real-paper pilot. Re-run after acquire.py, on the source-gate branch."""

import hashlib
import json
import re
import time
from pathlib import Path

import numpy as np
import torch

from core.schemas import EvidenceCoordinate
from corpus.pipeline import CorpusIngestionPipeline, RawDocumentInput
from corpus.schemas import LicenseType
from graph.schemas import DocumentNode, EdgeType, EvidenceEdge, EvidenceGraph
from graph.sqlite_adapter import SQLiteGraphPersistenceAdapter
from language.inference.loader import load_encoder
from language.training.dataloader import build_sequence
from reasoning.gap_classifier import RuleBasedGapClassifier
from reporting import (
    CorpusManifestEntry,
    ReportAssertion,
    ReportSectionType,
    SourceEvidenceGate,
    StructuredReportGenerator,
)
from retrieval.dense_adapter import DenseVectorAdapter, DenseVectorItem
from retrieval.engine import HybridRetrievalEngine
from retrieval.graph_adapter import GraphRetrievalAdapter
from retrieval.lexical_adapter import LexicalBM25Adapter, LexicalDocument
from retrieval.provenance import EvidenceCoordinateValidator
from retrieval.schemas import RetrievalChannel, RetrievalQuery

ROOT = Path("artifacts/pilots/scientific_nlp").resolve()
QUERIES = [
    (
        "Scientific claim verification with evidence abstracts and rationale annotations",
        "2020.emnlp-main.609",
    ),
    ("Document level N-ary relation extraction from scientific articles", "2020.acl-main.670"),
    (
        "Compositional reasoning and scientific claim verification with table evidence",
        "2023.emnlp-main.483",
    ),
    (
        "Extraction detection and generation of research questions using regular expressions",
        "2025.coling-main.573",
    ),
    ("Citation intent classification using structural scaffolds", "N19-1361"),
    ("Scientific pretrained language representation for scientific text", "D19-1371"),
]


def main():
    torch.set_num_threads(4)
    started = time.perf_counter()
    records = json.loads((ROOT / "corpus.json").read_text())
    sources = {r["id"]: (ROOT / r["text_file"]).read_text() for r in records}
    checksums = {r["id"]: r["text_sha256"] for r in records}
    assert all(hashlib.sha256(sources[k].encode()).hexdigest() == v for k, v in checksums.items())
    assert all(any("/by/4.0/" in link for link in r["license_links"]) for r in records)
    ingestion = CorpusIngestionPipeline().execute(
        [
            RawDocumentInput(
                r["id"],
                sources[r["id"]],
                LicenseType.CC_BY_4_0,
                r["url"],
                "ACL Anthology copyright notice",
                metadata={"use": "pilot_only"},
            )
            for r in records
        ],
        manifest_id="scientific-nlp-pilot",
        created_at="2026-11-10T00:00:00Z",
    )
    assert len(ingestion.unique_items) == len(records) and not ingestion.quarantined

    passages, coordinates = [], []
    graph = EvidenceGraph("scientific-nlp-pilot")
    for record in records:
        pid = record["id"]
        graph.add_node(DocumentNode(pid, record["title"], document_sha256=checksums[pid]))
        offset = 0
        for page_number, page in enumerate(sources[pid].split("\f"), 1):
            for match in re.finditer(r"[\s\S]{1,1200}(?:\s+|$)", page):
                text = match.group()
                if len(text.split()) < 20:
                    continue
                uid = f"{pid}:p{page_number}:{match.start()}"
                coord = EvidenceCoordinate(
                    uid,
                    pid,
                    checksums[pid],
                    page_number,
                    "pdf_text",
                    match.start(),
                    0,
                    offset + match.start(),
                    offset + match.end(),
                    text,
                )
                passages.append((uid, text, pid))
                coordinates.append(coord)
                if not graph.nodes[pid].provenance:
                    graph.nodes[pid].provenance = [coord]
                    graph.nodes[pid].properties.update({"canonical_text": text, "doc_id": pid})
                graph.add_node(
                    DocumentNode(
                        uid,
                        text[:80],
                        document_sha256=checksums[pid],
                        properties={"canonical_text": text, "doc_id": pid},
                        provenance=[coord],
                    )
                )
                graph.add_edge(EvidenceEdge(uid + ":source", uid, pid, EdgeType.DERIVED_FROM))
            offset += len(page) + 1
    store = SQLiteGraphPersistenceAdapter(ROOT / "evidence.sqlite")
    store.save(graph)
    loaded_graph = store.load(graph.graph_id)
    assert len(loaded_graph.nodes) == len(graph.nodes)
    print(f"Ingested {len(records)} papers, indexed {len(passages)} passages", flush=True)

    encoder = load_encoder(
        Path("artifacts/checkpoints/language_encoder/compact-1024-04/best"),
        Path("artifacts/tokenizer/laris_spm_32k.model"),
        device="cuda",
    )

    def embed(texts):
        vectors = []
        for start in range(0, len(texts), 16):
            ids = [encoder.tokenizer.encode_as_ids(t) for t in texts[start : start + 16]]
            length = min(encoder.seq_len, max(len(row) + 2 for row in ids))
            rows = [build_sequence(row, None, length) for row in ids]
            with torch.inference_mode():
                out = encoder.model(
                    torch.tensor([r[0] for r in rows], device="cuda"),
                    attention_mask=torch.tensor([r[1] for r in rows], device="cuda"),
                    task="similarity",
                )
            vectors.extend(out["cls_embedding"].float().cpu().numpy())
        arr = np.asarray(vectors)
        return arr / np.maximum(np.linalg.norm(arr, axis=1, keepdims=True), 1e-12)

    vectors = embed([p[1] for p in passages])
    lexical = LexicalBM25Adapter()
    dense = DenseVectorAdapter(expected_dim=encoder.config.d_model)
    lexical.add_documents(
        [
            LexicalDocument(p[0], p[1], metadata={"doc_id": p[2]}, coordinates=[c])
            for p, c in zip(passages, coordinates)
        ]
    )
    dense.add_items(
        [
            DenseVectorItem(p[0], p[1], v.tolist(), {"doc_id": p[2]}, [c])
            for p, c, v in zip(passages, coordinates, vectors)
        ]
    )
    validator = EvidenceCoordinateValidator(sources, checksums)
    engine = HybridRetrievalEngine(
        {a.channel: a for a in (lexical, dense, GraphRetrievalAdapter(graph=loaded_graph))},
        coordinate_validator=validator,
    )
    results, retrieved = [], []
    for (text, gold), vec in zip(QUERIES, embed([q[0] for q in QUERIES])):
        query = RetrievalQuery(text, top_k=100, dense_vector=vec.tolist(), require_coordinates=True)
        item = {"query": text, "expected_paper": gold}
        for name, channels in (
            ("bm25", [RetrievalChannel.LEXICAL]),
            ("dense", [RetrievalChannel.DENSE]),
            ("hybrid", None),
        ):
            candidates = engine.retrieve(query, channels=channels)
            docs = list(dict.fromkeys(c.coordinates[0].document_id for c in candidates))[:5]
            item[name] = {
                "top5_papers": docs,
                "hit_at_5": gold in docs,
                "reciprocal_rank_at_5": 1 / (docs.index(gold) + 1) if gold in docs else 0,
            }
            if name == "hybrid":
                retrieved.extend(candidates[:10])
        results.append(item)
        print(text, {k: item[k]["hit_at_5"] for k in ("bm25", "dense", "hybrid")}, flush=True)

    assertions, citations, used_docs, gaps = [], {}, set(), []
    classifier = RuleBasedGapClassifier()
    for candidate in retrieved:
        coord = candidate.coordinates[0]
        if coord.document_id in used_docs:
            continue
        for match in re.finditer(r"[^.!?]+[.!?]", candidate.content):
            text = match.group().strip()
            if (
                not 10 <= len(text.split()) <= 25
                or not text[0].isupper()
                or "\n\n" in text
                or text.count("\n") > 3
                or text.count("(") != text.count(")")
                or text.endswith(("et al.", "e.g.", "i.e."))
            ):
                continue
            local_start = candidate.content.index(text, match.start())
            exact = EvidenceCoordinate(
                coord.coordinate_id + ":excerpt",
                coord.document_id,
                coord.document_sha256,
                coord.page_number,
                "pdf_text",
                coord.paragraph_index,
                0,
                coord.char_start + local_start,
                coord.char_start + local_start + len(text),
                text,
            )
            is_limit = bool(
                re.search(r"\b(limitations?|challeng\w+|lack\w*|however)\b", text, re.I)
            )
            section = (
                ReportSectionType.LIMITATIONS_AND_BOUNDARIES
                if is_limit
                else ReportSectionType.COMPARATIVE_SYNTHESIS
            )
            assertions.append(
                ReportAssertion(f"a{len(assertions)}", section, text, [exact.coordinate_id])
            )
            citations[exact.coordinate_id] = exact
            used_docs.add(coord.document_id)
            if is_limit:
                gaps.append(
                    {
                        "assertion": assertions[-1].assertion_id,
                        "suggested_class": classifier.classify_text(text).value,
                        "status": "author_text_candidate_not_verified_research_gap",
                    }
                )
            break
    contents = {
        s: "\n\n".join(a.statement for a in assertions if a.section == s) for s in ReportSectionType
    }
    manifest = [
        CorpusManifestEntry(
            r["id"],
            r["title"],
            r["text_sha256"],
            int(re.search(r"\b(20\d\d)\b", r["id"]).group(1))
            if r["id"][0].isdigit()
            else 2000 + int(r["id"][1:3]),
            "ACL Anthology",
        )
        for r in records
    ]
    gate = SourceEvidenceGate(sources)
    report, summary = StructuredReportGenerator(evidence_gate=gate).generate_report(
        "scientific-nlp-pilot",
        "Inspect scientific NLP evidence and author-stated limitations",
        manifest,
        contents,
        assertions,
        citations,
        metadata={"scope": "extractive_pilot_not_autonomous_gap_discovery"},
    )
    (ROOT / "report.md").write_text(report.render_markdown())
    (ROOT / "report.json").write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    summary_data = {
        "papers": len(records),
        "passages": len(passages),
        "graph_nodes": len(graph.nodes),
        "graph_edges": len(graph.edges),
        "report_verification": summary.to_dict(),
        "queries": results,
        "gap_candidates": gaps,
        "elapsed_seconds": time.perf_counter() - started,
        "limitations": [
            "Six curated queries are not an independent retrieval benchmark.",
            "No semantic synthesis or novelty certification.",
            "PDF text extraction does not parse tables or figures.",
            "Corpus is English and deliberately bounded to 20 papers.",
        ],
    }
    (ROOT / "results.json").write_text(json.dumps(summary_data, indent=2, ensure_ascii=False))
    print(json.dumps(summary_data["report_verification"]), flush=True)


if __name__ == "__main__":
    main()
