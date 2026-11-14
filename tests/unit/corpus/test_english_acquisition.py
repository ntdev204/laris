"""Non-network checks for the English data acquirer and the STS-B leakage filter (T175)."""

import importlib.util
from pathlib import Path

import pytest

from laris.research.corpus.acquisition.sources import english_hf

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_leakage_module():
    spec = importlib.util.spec_from_file_location(
        "check_sts_leakage", REPO_ROOT / "scripts/check_sts_leakage.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_config_is_valid_and_covers_every_role() -> None:
    config = english_hf.load_sources_config()
    roles = {s["role"] for s in config["sources"]}
    assert {"mlm", "nli", "similarity", "paraphrase", "qa", "retrieval"} <= roles
    assert all("vi" not in s["id"].lower().split("-") for s in config["sources"])
    assert english_hf.english_acquirers().keys() == {s["id"] for s in config["sources"]}


def test_select_files_is_sorted_and_limited() -> None:
    source = {"pattern": "*.parquet", "limit": 2, "path": "d"}
    listing = [{"path": f"d/{n}"} for n in ("b.parquet", "a.parquet", "c.txt", "c.parquet")]
    assert [f["path"] for f in english_hf.select_files(source, listing)] == [
        "d/a.parquet",
        "d/b.parquet",
    ]


def test_local_name_flattens_subdirectories() -> None:
    assert english_hf.local_name({"path": "x"}, "x/train/0000.parquet") == "train__0000.parquet"
    assert english_hf.local_name({"path": ""}, "train.tsv") == "train.tsv"


def test_duplicate_source_id_is_rejected(tmp_path: Path) -> None:
    source = (
        "config_version: '1'\nsources:\n"
        + "  - {id: A, role: mlm, repo: r/x, pattern: '*', license_name: l, license_approved: true, min_rows: 1}\n"  # noqa: E501
        * 2
    )
    path = tmp_path / "s.yaml"
    path.write_text(source, encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        english_hf.load_sources_config(path)


def test_leakage_filter_drops_heldout_duplicate_and_empty() -> None:
    mod = _load_leakage_module()
    blocked = {mod.normalise("A girl is styling her hair.")}
    pairs = [
        (
            "A girl is STYLING her hair!",
            "Someone else",
            3.0,
        ),  # leaked (case and punctuation differ)
        ("Cats purr.", "Dogs bark.", 1.0),
        ("Dogs bark", "cats purr", 1.0),  # same unordered pair
        ("", "x", 2.0),
    ]
    kept, stats = mod.filter_pairs(pairs, blocked, set())
    assert kept == [("Cats purr.", "Dogs bark.", 1.0)]
    assert stats == {"input": 4, "leaked": 1, "duplicate": 1, "empty": 1, "kept": 1}
