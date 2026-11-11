"""Foundation retrieval benchmark: frozen relevance, rank metrics, isolation and gate wiring.

Synthetic rows below test the code paths only; they are never reported as benchmark data.
"""

import json
from pathlib import Path

import numpy as np
import pytest
import yaml

pa = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")

from laris.language.benchmarks import retrieval as R  # noqa: E402
from laris.language.evaluation.readiness import assess_readiness  # noqa: E402
from laris.language.training.checkpoint import file_sha256  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA = pa.schema(
    [
        ("id", pa.string()),
        ("title", pa.string()),
        ("context", pa.string()),
        ("question", pa.string()),
        (
            "answers",
            pa.struct([("text", pa.list_(pa.string())), ("answer_start", pa.list_(pa.int32()))]),
        ),
    ]
)


def row(qid, title, context, question, answer="x"):
    texts = [answer] if answer else []
    return {
        "id": qid,
        "title": title,
        "context": context,
        "question": question,
        "answers": {"text": texts, "answer_start": [0] * len(texts)},
    }


CORPUS = [
    row("q1", "A", "red apples grow on trees in orchards", "where do red apples grow"),
    row("q2", "A", "bananas ripen in warm tropical climates", "which fruit ripens in the tropics"),
    row("q3", "B", "granite is an igneous rock of quartz", "what is granite made of"),
    row("q4", "B", "basalt forms from cooled lava flows", "how does basalt form", answer=""),
]


def write_split(root, dataset_dir, split, rows):
    path = root / dataset_dir / f"{split}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMA), path)
    return path


SOURCE = {"id": "toy", "language": "en", "dataset_dir": "toy", "split": "test"}


# ------------------------------------------------------------------------------ loading
def test_load_split_keeps_answerable_questions_and_dedupes_paragraphs(tmp_path):
    write_split(tmp_path, "toy", "test", CORPUS + [row("q5", "A", CORPUS[0]["context"], "red?")])
    split = R.load_split(SOURCE, tmp_path)
    assert [q.query_id for q in split.queries] == ["q1", "q2", "q3", "q5"]  # q4 has no answer
    assert len(split.doc_ids) == 3  # q1 and q5 share one paragraph; q4's is not an answerable query
    assert {q.relevant_doc for q in split.queries} <= set(split.doc_ids)
    assert split.doc_ids == sorted(split.doc_ids)


def test_digest_is_stable_and_detects_any_change_in_queries_or_relevance(tmp_path):
    write_split(tmp_path, "toy", "test", CORPUS)
    base = R.split_digest(R.load_split(SOURCE, tmp_path))
    assert base == R.split_digest(R.load_split(SOURCE, tmp_path))
    changed = [dict(r) for r in CORPUS]
    changed[0] = row("q1", "A", CORPUS[0]["context"], "a different question text")
    write_split(tmp_path, "toy", "test", changed)
    assert R.split_digest(R.load_split(SOURCE, tmp_path)) != base
    relabelled = [dict(r) for r in CORPUS]
    relabelled[0] = row("q1", "A", CORPUS[2]["context"], CORPUS[0]["question"])
    write_split(tmp_path, "toy", "test", relabelled)
    assert R.split_digest(R.load_split(SOURCE, tmp_path)) != base


def test_frozen_config_must_match_before_anything_is_scored():
    digests = {"toy": {"queries": 3, "documents": 3, "digest": "abc"}}
    with pytest.raises(ValueError, match="not frozen"):
        R.verify_frozen({"frozen": {}}, digests)
    with pytest.raises(ValueError, match="differ"):
        R.verify_frozen({"frozen": {"toy": {**digests["toy"], "digest": "zzz"}}}, digests)
    R.verify_frozen({"frozen": digests}, digests)


# ------------------------------------------------------------------------------- metrics
def test_summary_metrics_from_ranks():
    ranks = np.array([1, 2, 10, 11])
    out = R.summarise(ranks)
    assert out["mrr"] == pytest.approx((1 + 1 / 2 + 1 / 10 + 1 / 11) / 4)
    assert out["ndcg_at_10"] == pytest.approx((1 + 1 / np.log2(3) + 1 / np.log2(11) + 0) / 4)
    assert out["recall_at_1"] == 0.25 and out["recall_at_5"] == 0.5 and out["recall_at_10"] == 0.75
    assert R.summarise(np.array([], dtype=int))["mrr"] == 0.0


def test_ties_count_against_the_system(tmp_path):
    write_split(tmp_path, "toy", "test", CORPUS)
    split = R.load_split(SOURCE, tmp_path)
    flat = np.zeros((len(split.queries), len(split.doc_ids)))
    assert list(R.relevant_ranks(flat, split)) == [len(split.doc_ids)] * len(split.queries)


def test_same_article_negatives_rank_only_documents_of_that_article(tmp_path):
    write_split(tmp_path, "toy", "test", CORPUS)
    split = R.load_split(SOURCE, tmp_path)
    scores = np.zeros((len(split.queries), len(split.doc_ids)))
    index = {d: i for i, d in enumerate(split.doc_ids)}
    for r, q in enumerate(split.queries):
        scores[r, index[q.relevant_doc]] = 1.0  # perfect everywhere
    assert list(R.relevant_ranks(scores, split)) == [1, 1, 1]
    assert list(R.relevant_ranks(scores, split, same_title_only=True)) == [1, 1, 1]
    # a distractor from another article outranks the target: it matters only for full ranking
    q0 = split.queries[0]
    other = next(i for i, t in enumerate(split.doc_titles) if t != q0.title)
    scores[0, other] = 2.0
    assert R.relevant_ranks(scores, split)[0] == 2
    assert R.relevant_ranks(scores, split, same_title_only=True)[0] == 1


def test_rrf_rewards_documents_both_systems_rank_well():
    a = np.array([[0.9, 0.5, 0.1]])
    b = np.array([[0.2, 0.8, 0.1]])
    fused = R.rrf_scores([a, b])
    assert fused[0].argmax() in {0, 1} and fused[0, 2] < fused[0, :2].min()
    assert np.array_equal(R.rank_matrix(np.array([[0.1, 0.9, 0.5]])), [[3, 1, 2]])


def test_paired_bootstrap_is_seeded():
    values = np.array([0.0, 0.5, 1.0, 0.25] * 10)
    assert R.bootstrap_mean(values, 3) == R.bootstrap_mean(values, 3)
    low, high = R.bootstrap_mean(values, 3)
    assert low <= values.mean() <= high


# ----------------------------------------------------------------------------- end to end
def bag_embedder(texts):
    rows = []
    for text in texts:
        vec = np.zeros(64)
        for word in text.lower().split():
            vec[hash_word(word) % 64] += 1.0
        rows.append(vec / max(np.linalg.norm(vec), 1e-12))
    return np.stack(rows)


def hash_word(word):
    return sum(ord(c) * (i + 1) for i, c in enumerate(word))


def toy_config():
    return {
        "benchmark_id": "toy",
        "gate_dataset": "stem_retrieval",
        "gate_system": "dense",
        "baseline_system": "bm25",
        "systems": {"bm25": {"k1": 1.5, "b": 0.75}, "hybrid_rrf": {"k": 60}},
        "subsets": [{"id": "sub", "source": "toy", "titles": ["B"], "note": "diagnostic"}],
    }


def test_evaluate_split_reports_systems_differences_and_subsets(tmp_path):
    write_split(tmp_path, "toy", "test", CORPUS)
    split = R.load_split(SOURCE, tmp_path)
    result = R.evaluate_split(split, SOURCE, toy_config(), bag_embedder)
    assert set(result["systems"]) == {"bm25", "dense", "hybrid_rrf"}
    assert "dense_minus_bm25_mrr" in result["paired_differences"]
    assert (
        result["subsets"]["sub"]["queries"] == 1
        and result["subsets"]["sub"]["gate_eligible"] is False
    )
    for system in result["systems"].values():
        assert 0.0 < system["mrr"] <= 1.0 and "hard_negative_same_article" in system


def formal_config():
    return yaml.safe_load((REPO_ROOT / "configs/evaluation/foundation.yaml").read_text())


def readiness_report(rows):
    return {
        "split": "test",
        "datasets": rows,
        "model_sha256": "a" * 64,
        "tokenizer_sha256": "b" * 64,
        "dataset_manifest_sha256": "c" * 64,
        "split_isolation_checked": True,
    }


def test_general_domain_source_never_fills_the_stem_gate(tmp_path):
    write_split(tmp_path, "toy", "test", CORPUS)
    split = R.load_split(SOURCE, tmp_path)
    evaluation = R.evaluate_split(split, SOURCE, toy_config(), bag_embedder)
    row_ = R.gate_row(split, {**SOURCE, "gate_eligible": False}, toy_config(), evaluation)
    assert row_["dataset"] == R.NON_GATE_DATASET
    gates = {
        g["id"]: g for g in assess_readiness([readiness_report([row_])], formal_config())["gates"]
    }
    assert gates["G12"]["status"] == "MISSING"


def test_gate_requires_both_the_threshold_and_beating_bm25():
    def record(dense, bm25):
        return {
            "dataset": "stem_retrieval",
            "language": "all",
            "samples": 100,
            "metrics": {"mrr": dense},
            "baseline": {"mrr": bm25},
            "metric_protocols": {"mrr": R.RETRIEVAL_PROTOCOL},
        }

    def status(dense, bm25):
        report = readiness_report([record(dense, bm25)])
        return next(
            g for g in assess_readiness([report], formal_config())["gates"] if g["id"] == "G12"
        )["status"]

    assert status(0.90, 0.80) == "PASS"
    assert status(0.90, 0.95) == "FAIL"  # above 0.82 but not better than BM25
    assert status(0.70, 0.50) == "FAIL"  # better than BM25 but below 0.82


def make_data_dir(tmp_path, train_rows, test_rows=CORPUS):
    write_split(tmp_path, "toy", "train", train_rows)
    test_path = write_split(tmp_path, "toy", "test", test_rows)
    manifest = {
        "partitioned_datasets": [
            {
                "dataset_id": "TOY",
                "leakage_verified": True,
                "sha256": {"test": file_sha256(test_path)},
            }
        ]
    }
    (tmp_path / "task_splits_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def frozen_config(tmp_path):
    split = R.load_split(SOURCE, tmp_path)
    config = {
        **toy_config(),
        "sources": [{**SOURCE, "manifest_id": "TOY", "gate_eligible": False}],
        "frozen": {
            "toy": {
                "queries": len(split.queries),
                "documents": len(split.doc_ids),
                "digest": R.split_digest(split),
            }
        },
    }
    return config


def test_build_report_scores_only_an_isolated_frozen_benchmark(tmp_path):
    make_data_dir(tmp_path, [row("t1", "Z", "train only paragraph", "train question")])
    report = R.build_report(frozen_config(tmp_path), tmp_path, bag_embedder)
    assert report["split_isolation_checked"] is True and report["datasets"][0]["samples"] == 3
    assert report["sources"][0]["isolation"]["train_paragraph_overlap"] == 0
    assert "relevance" in report and report["tie_policy"].startswith("pessimistic")


def test_overlap_with_the_training_split_is_refused(tmp_path):
    make_data_dir(tmp_path, [row("t1", "A", CORPUS[0]["context"], "leaked question")])
    with pytest.raises(ValueError, match="overlaps the training split"):
        R.build_report(frozen_config(tmp_path), tmp_path, bag_embedder)


def test_altered_split_after_freezing_is_refused(tmp_path):
    make_data_dir(tmp_path, [row("t1", "Z", "train only paragraph", "train question")])
    config = frozen_config(tmp_path)
    write_split(tmp_path, "toy", "test", CORPUS[:2])
    with pytest.raises(ValueError, match="differ|SHA-256"):
        R.build_report(config, tmp_path, bag_embedder)


def test_pretraining_text_exposure_is_measured_not_hidden(tmp_path):
    make_data_dir(tmp_path, [row("t1", "Z", "train only paragraph", "train question")])
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    pq.write_table(pa.table({"title": ["A", "Other"], "text": ["a", "b"]}), wiki / "train.parquet")
    split = R.load_split(SOURCE, tmp_path)
    checks = R.isolation_checks(split, {**SOURCE, "pretraining_corpus": "wiki"}, tmp_path)
    exposure = checks["pretraining_text_exposure"]
    assert exposure["matching_titles"] == 1 and exposure["of_titles"] == 2
    assert exposure["titles"] == ["A"]


def test_committed_config_is_frozen_and_matches_the_data():
    config = R.load_config(REPO_ROOT / "configs/evaluation/foundation_retrieval.yaml")
    assert {s["id"] for s in config["sources"]} == set(config["frozen"])
    assert config["gate_system"] == "dense" and config["baseline_system"] == "bm25"
    eligible = [s["id"] for s in config["sources"] if s["gate_eligible"]]
    assert eligible == ["scifact_test_en"]  # only the STEM source with human qrels may gate G12
    assert all(s["gate_eligible"] is False for s in config["sources"] if s.get("kind") != "qrels")
    data_dir = REPO_ROOT / "data/processed"
    if not (data_dir / "squad" / "test.parquet").is_file():
        pytest.skip("processed datasets are not available")
    assert R.freeze_digests(config, data_dir) == config["frozen"]


# ----------------------------------------------------------------------------- qrels sources
def write_qrels_source(root):
    raw = root / "raw" / "sci"
    raw.mkdir(parents=True)
    pq.write_table(
        pa.Table.from_pylist(
            [
                {"_id": "d1", "title": "Apples", "text": "apples grow on trees"},
                {"_id": "d2", "title": "Rocks", "text": "granite is igneous"},
                {"_id": "d3", "title": "Lava", "text": "basalt cools from lava"},
            ]
        ),
        raw / "corpus.parquet",
    )
    pq.write_table(
        pa.Table.from_pylist(
            [
                {"_id": "1", "title": "", "text": "where do apples grow"},
                {"_id": "2", "title": "", "text": "what rocks are igneous"},
            ]
        ),
        raw / "queries.parquet",
    )
    (raw / "test.tsv").write_text(
        "query-id\tcorpus-id\tscore\n1\td1\t1\n2\td2\t1\n2\td3\t1\n2\td1\t0\n", encoding="utf-8"
    )
    return {
        "id": "sci",
        "language": "en",
        "kind": "qrels",
        "raw_dir": "sci",
        "corpus_file": "corpus.parquet",
        "queries_file": "queries.parquet",
        "qrels_file": "test.tsv",
    }


def test_qrels_loader_keeps_every_positive_judgement(tmp_path):
    source = write_qrels_source(tmp_path)
    split = R.load_any(source, tmp_path / "processed")
    assert [q.query_id for q in split.queries] == ["1", "2"]
    assert split.queries[1].relevant_doc == "d2" and split.queries[1].also_relevant == ("d3",)
    assert len(split.doc_ids) == 3
    assert R.split_digest(split) == R.split_digest(R.load_any(source, tmp_path / "processed"))


def test_multi_relevant_rank_and_ndcg():
    q = R.RetrievalQuery("1", "q", "d1", "", ("d3",))
    split = R.RetrievalSplit("s", "en", [q], ["d1", "d2", "d3"], ["a", "b", "c"], ["", "", ""])
    scores = np.array([[0.1, 0.9, 0.5]])  # d3 ranks 2nd, d1 3rd
    assert R.relevant_ranks(scores, split).tolist() == [2]
    expected = (1 / np.log2(3) + 1 / np.log2(4)) / (1 + 1 / np.log2(3))
    assert R.ndcg_at_10_values(scores, split)[0] == pytest.approx(expected)


def test_single_judgement_ndcg_matches_rank_formula():
    q = R.RetrievalQuery("1", "q", "d1", "A")
    split = R.RetrievalSplit("s", "en", [q], ["d1", "d2"], ["a", "b"], ["A", "A"])
    scores = np.array([[0.2, 0.8]])
    assert R.ndcg_at_10_values(scores, split)[0] == pytest.approx(1 / np.log2(3))
    assert R.summarise(R.relevant_ranks(scores, split))["ndcg_at_10"] == pytest.approx(
        1 / np.log2(3)
    )


def test_parallel_loader_is_seeded_and_relevance_is_the_same_row(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    rows = [
        {"en": f"english abstract number {i} " * 4, "vi": f"ban tom tat so {i} " * 4}
        for i in range(30)
    ]
    rows.append({"en": "short", "vi": "ngan"})
    pq.write_table(pa.Table.from_pylist(rows), raw / "pairs.parquet")
    source = {
        "id": "p",
        "language": "vi",
        "kind": "parallel",
        "parquet": "raw/pairs.parquet",
        "query_column": "en",
        "doc_column": "vi",
        "sample_size": 10,
        "sample_seed": 1,
        "min_chars": 20,
    }
    first = R.load_any(source, tmp_path / "processed")
    again = R.load_any(source, tmp_path / "processed")
    assert R.split_digest(first) == R.split_digest(again)
    assert len(first.queries) == 10 and "r30" not in first.doc_ids  # short row filtered out
    for q, d in zip(first.queries, first.doc_texts):
        assert q.relevant_doc == q.query_id
        assert q.text.split()[3] == d.split()[4]  # both carry the same source row index
    other = R.load_any({**source, "sample_seed": 2}, tmp_path / "processed")
    assert R.split_digest(other) != R.split_digest(first)


def test_dev_config_is_frozen_and_never_gates():
    config = R.load_config(REPO_ROOT / "configs/evaluation/foundation_retrieval_dev.yaml")
    assert all(s["gate_eligible"] is False for s in config["sources"])
    assert all(s["qrels_file"] != "qrels__test.tsv" for s in config["sources"])
    data_dir = REPO_ROOT / "data/processed"
    if not (REPO_ROOT / "data/raw/scifact/qrels__train.tsv").is_file():
        pytest.skip("SciFact is not available")
    assert R.freeze_digests(config, data_dir) == config["frozen"]


def test_stem_vi_diagnostic_config_is_frozen_and_never_gates():
    config = R.load_config(REPO_ROOT / "configs/evaluation/foundation_retrieval_stem_vi_diag.yaml")
    assert [s["kind"] for s in config["sources"]] == ["parallel"]
    assert all(s["gate_eligible"] is False for s in config["sources"])
    full = R.load_config(REPO_ROOT / "configs/evaluation/foundation_retrieval.yaml")
    assert (
        config["frozen"]["stem_vi_crosslingual_en_to_vi"]
        == (full["frozen"]["stem_vi_crosslingual_en_to_vi"])
    )
