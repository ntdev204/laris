"""Tokenizer fertility benchmark: definitions, sampling, leakage and readiness contract.

Only text is encoded with a stub or the existing tokenizer; nothing is fitted or trained.
"""

import json
from pathlib import Path

import numpy as np
import pytest
import yaml

pa = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")

from language.benchmarks import fertility as F  # noqa: E402
from language.evaluation.readiness import assess_readiness  # noqa: E402
from language.training.checkpoint import file_sha256  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]


class PieceTokenizer:
    """Words of up to three characters are one piece, longer words two; 'unk' maps to [UNK]."""

    def encode_as_ids(self, text):
        out = []
        for word in text.split():
            out.append(1 if word == "unk" else 10)
            if len(word) > 3:
                out.append(11)
        return out


def test_definitions_count_whitespace_words_and_pieces():
    assert F.count_words("  a  bb\tccc\n") == 3
    assert F.count_words("Hà Nội là thủ đô") == 5  # Vietnamese syllables, not segmented words
    tokenizer = PieceTokenizer()
    result = F.measure_texts(tokenizer, ["abc abcd", "unk"])
    assert result["words"] == 3 and result["tokens"] == 4
    assert result["fertility"] == pytest.approx(4 / 3)
    assert result["unknown_token_rate"] == pytest.approx(1 / 4)  # one [UNK] among four tokens
    assert F.fertility(0, 0) == 0.0


def test_sampling_is_seeded_sorted_and_without_replacement():
    first = F.sample_indices(1000, 50, seed=7)
    assert list(first) == list(F.sample_indices(1000, 50, seed=7))
    assert list(first) != list(F.sample_indices(1000, 50, seed=8))
    assert list(first) == sorted(set(first.tolist())) and len(first) == 50
    assert list(F.sample_indices(10, 50, seed=7)) == list(range(10))


def test_read_texts_returns_selected_rows_and_deduplicates_multi_column_sources(tmp_path):
    path = tmp_path / "t.parquet"
    pq.write_table(
        pa.table({"premise": ["p0", "p1", "p1", "p3"], "hypothesis": ["h0", "h1", "h2", "h3"]}),
        path,
    )
    texts = F.read_texts(path, ("premise", "hypothesis"), np.array([1, 2]))
    assert texts == ["h1", "h2", "p1"]  # p1 appears in both selected rows, once in the output
    single = tmp_path / "s.parquet"
    pq.write_table(pa.table({"text": ["a", "b", "c"]}), single)
    assert F.read_texts(single, ("text",), np.array([0, 2])) == ["a", "c"]


def test_exact_fit_corpus_matches_are_excluded_and_counted(tmp_path):
    seen = "Hà Nội là thủ đô của Việt Nam và là một thành phố lớn"
    corpus = tmp_path / "fit.txt"
    corpus.write_text(F.fit_text_key(seen) + "\nanother article about physics\n", encoding="utf-8")
    full, prefix, lines = F.fingerprint_fit_corpus(corpus)
    assert lines == 2
    overlap = lambda text: F.classify_overlap(text, full, prefix)  # noqa: E731
    assert overlap(seen) == (True, True)
    assert overlap("A completely new unseen sentence") == (False, False)
    result = F.measure_texts(PieceTokenizer(), [seen, "fresh unseen text here"], overlap)
    assert result["texts_sampled"] == 2 and result["texts_scored"] == 1
    assert result["excluded_exact_fit_corpus_matches"] == 1


def test_shared_leading_text_is_reported_but_not_excluded(tmp_path):
    lead = "x" * 250
    corpus = tmp_path / "fit.txt"
    corpus.write_text(lead + " ending one\n", encoding="utf-8")
    full, prefix, _ = F.fingerprint_fit_corpus(corpus)
    exact, head = F.classify_overlap(lead + " a different ending", full, prefix)
    assert (exact, head) == (False, True)
    result = F.measure_texts(
        PieceTokenizer(),
        [lead + " a different ending", "other text"],
        lambda text: F.classify_overlap(text, full, prefix),
    )
    assert result["texts_scored"] == 2 and result["prefix_overlap_texts"] == 1
    assert "fertility_excluding_prefix_overlap" in result


def test_bootstrap_is_deterministic_and_brackets_the_point_estimate():
    tokens, words = [3, 4, 5, 6, 2] * 20, [2, 3, 3, 4, 2] * 20
    a = F.bootstrap_fertility(tokens, words, seed=1)
    assert np.array_equal(a, F.bootstrap_fertility(tokens, words, seed=1))
    point = sum(tokens) / sum(words)
    low, high = np.percentile(a, [2.5, 97.5])
    assert low <= point <= high


def make_data(tmp_path, en_texts, vi_texts):
    entries = []
    for dataset_id, folder, texts in (
        ("WIKIPEDIA-EN", "wikipedia_en", en_texts),
        ("WIKIPEDIA-VI", "wikipedia_vi", vi_texts),
    ):
        path = tmp_path / folder / "test.parquet"
        path.parent.mkdir()
        pq.write_table(pa.table({"text": texts}), path)
        entries.append(
            {
                "dataset_id": dataset_id,
                "leakage_verified": True,
                "sha256": {"test": file_sha256(path)},
            }
        )
    (tmp_path / "task_splits_manifest.json").write_text(
        json.dumps({"partitioned_datasets": entries}), encoding="utf-8"
    )
    return (
        F.SourceSpec("wiki_en", "en", "wikipedia_en", "WIKIPEDIA-EN", ("text",), "wiki"),
        F.SourceSpec("wiki_vi", "vi", "wikipedia_vi", "WIKIPEDIA-VI", ("text",), "wiki"),
    )


def formal_config():
    return yaml.safe_load((REPO_ROOT / "configs/evaluation/foundation.yaml").read_text())


def wrap_for_readiness(report):
    return {**report, "model_sha256": "a" * 64, "tokenizer_sha256": "b" * 64}


def test_report_feeds_the_formal_gates_with_the_declared_protocol(tmp_path):
    specs = make_data(tmp_path, ["ab cd ef"] * 5, ["abcd ef gh"] * 5)  # 1.0 en, 1.33 vi
    report = F.build_report(PieceTokenizer(), specs, tmp_path, 5, seed=3, overlap=None)
    assert report["split"] == "test" and report["split_isolation_checked"] is True
    assert {d["language"] for d in report["datasets"]} == {"en", "vi"}
    for row in report["datasets"]:
        assert row["dataset"] == "unseen_text"
        assert row["metric_protocols"]["fertility"] == F.FERTILITY_PROTOCOL
        assert row["samples"] > 0
    gates = {
        g["id"]: g for g in assess_readiness([wrap_for_readiness(report)], formal_config())["gates"]
    }
    assert gates["G10"]["status"] == "PASS" and gates["G11"]["status"] == "PASS"
    assert gates["G10"]["value"] == pytest.approx(1.0)


def test_report_fails_a_gate_when_fertility_is_too_high(tmp_path):
    specs = make_data(tmp_path, ["abcd efgh"] * 5, ["ab cd"] * 5)  # 2.0 en
    report = F.build_report(PieceTokenizer(), specs, tmp_path, 5, seed=3, overlap=None)
    gates = {
        g["id"]: g for g in assess_readiness([wrap_for_readiness(report)], formal_config())["gates"]
    }
    assert gates["G10"]["status"] == "FAIL" and gates["G11"]["status"] == "PASS"


def test_unverified_split_or_changed_file_is_refused(tmp_path):
    specs = make_data(tmp_path, ["ab"] * 3, ["cd"] * 3)
    manifest_path = tmp_path / "task_splits_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["partitioned_datasets"][0]["sha256"]["test"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="SHA-256"):
        F.build_report(PieceTokenizer(), specs, tmp_path, 3, seed=1, overlap=None)
    manifest["partitioned_datasets"][0]["sha256"]["test"] = file_sha256(
        tmp_path / "wikipedia_en" / "test.parquet"
    )
    manifest["partitioned_datasets"][1]["leakage_verified"] = False
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="isolation"):
        F.build_report(PieceTokenizer(), specs, tmp_path, 3, seed=1, overlap=None)


def test_committed_report_is_a_complete_readiness_measurement():
    path = REPO_ROOT / "reports/tokenizer/fertility.json"
    if not path.is_file():
        pytest.skip("fertility report has not been generated")
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["report_version"] == F.REPORT_VERSION
    assert report["training_executed"] is False and report["tokenizer_fitting_executed"] is False
    assert report["fit_corpus"]["lines_match_partition_train_counts"] is True
    gates = {g["id"]: g for g in assess_readiness([report], formal_config())["gates"]}
    for gate_id in ("G10", "G11"):
        assert gates[gate_id]["status"] in {"PASS", "FAIL"}, gates[gate_id]
