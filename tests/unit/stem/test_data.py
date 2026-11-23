"""Seeded splits, manifest, sealed guard and GPQA option shuffle (T275, ADR-026 sections 3, 7)."""

import csv
import json

import pytest

from laris.research.stem import data


def _items(prefix, n, category="c", options=()):
    return [
        {
            "id": f"{prefix}/{i}",
            "question": f"{prefix} question {i}",
            "options": list(options),
            "answer": "A" if options else str(i),
            "category": category,
        }
        for i in range(n)
    ]


def _splits(seed=7):
    math500 = _items("m5", 10)
    train = _items("mt", 40) + [dict(_items("dup", 1)[0], question="M5  Question 3")]
    mmlu = _items("mp", 50, "math", "abcd") + _items("pp", 30, "physics", "abcd")
    main = _items("gp", 20, "Physics", "abcd")
    diamond = main[:8]
    return data.build_splits(
        math500, train, mmlu, main, diamond, seed=seed, math_dev_size=20, mmlu_dev_fraction=0.2
    )


def test_splits_follow_adr_026():
    splits = _splits()
    assert len(splits["math500"]["sealed"]) == 10
    dev_ids = {i["id"] for i in splits["math500"]["dev"]}
    assert len(dev_ids) == 20 and not any(i.startswith("dup/") for i in dev_ids)
    mmlu = splits["mmlu_pro_stem"]
    assert len(mmlu["dev"]) == 16  # 20 % of 50 + 20 % of 30, per category
    assert sum(1 for i in mmlu["dev"] if i["category"] == "physics") == 6
    assert not {i["id"] for i in mmlu["dev"]} & {i["id"] for i in mmlu["sealed"]}
    assert len(mmlu["dev"]) + len(mmlu["sealed"]) == 80
    gpqa = splits["gpqa_diamond"]
    assert len(gpqa["sealed"]) == 8 and len(gpqa["dev"]) == 12
    assert not {i["id"] for i in gpqa["dev"]} & {i["id"] for i in gpqa["sealed"]}


def test_splits_are_seeded():
    assert _splits(7) == _splits(7)
    assert _splits(7)["math500"]["dev"] != _splits(8)["math500"]["dev"]


def test_gpqa_shuffle_is_seeded_and_keeps_the_key(tmp_path):
    folder = tmp_path / "gpqa"
    folder.mkdir()
    fields = [
        "Record ID",
        "Question",
        "Correct Answer",
        "Incorrect Answer 1",
        "Incorrect Answer 2",
        "Incorrect Answer 3",
        "High-level domain",
    ]
    with open(folder / "x.csv", "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for i in range(20):
            writer.writerow(
                {
                    "Record ID": f"r{i}",
                    "Question": "q",
                    "Correct Answer": "right",
                    "Incorrect Answer 1": "w1",
                    "Incorrect Answer 2": "w2",
                    "Incorrect Answer 3": "w3",
                    "High-level domain": "Physics",
                }
            )
    first = data.read_gpqa(tmp_path, "x.csv", 1)
    assert first == data.read_gpqa(tmp_path, "x.csv", 1)
    for item in first:
        assert item["options"][data.LETTERS.index(item["answer"])] == "right"
    assert len({i["answer"] for i in first}) > 1


@pytest.fixture
def written(tmp_path, monkeypatch):
    config = {
        "data_dir": "bench",
        "sealed_order_env": "TEST_SEALED_ORDER",
        "max_sealed_candidates": 2,
    }
    monkeypatch.delenv("TEST_SEALED_ORDER", raising=False)
    data_dir = tmp_path / "bench"
    manifest = {"benchmarks": {}}
    for bench in data.BENCHMARKS:
        manifest["benchmarks"][bench] = {}
        for part in ("dev", "sealed"):
            path = data_dir / "splits" / part / f"{bench}.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"id": f"{bench}/{part}"}) + "\n")
            manifest["benchmarks"][bench][part] = {
                "file": str(path.relative_to(data_dir)),
                "sha256": data.sha256_file(path),
            }
    (data_dir / "manifest.json").write_text(json.dumps(manifest))
    return config, tmp_path, data_dir


def test_dev_reads_without_order(written):
    config, root, _ = written
    assert data.load_items(config, root, "math500", "dev") == [{"id": "math500/dev"}]


def test_sealed_is_refused_outside_a_sealed_run(written, monkeypatch):
    config, root, _ = written
    with pytest.raises(data.SealedAccessError):
        data.load_items(config, root, "math500", "sealed")
    with pytest.raises(data.SealedAccessError):
        data.load_items(config, root, "math500", "sealed", sealed_order="c1")  # no owner order
    monkeypatch.setenv("TEST_SEALED_ORDER", "c1")
    with pytest.raises(data.SealedAccessError):
        data.load_items(config, root, "math500", "sealed", sealed_order="c2")  # not the ordered one


def test_sealed_run_once_per_candidate_and_capped(written, monkeypatch):
    config, root, _ = written
    monkeypatch.setenv("TEST_SEALED_ORDER", "c1")
    assert data.load_items(config, root, "math500", "sealed", sealed_order="c1")
    assert data.load_items(config, root, "gpqa_diamond", "sealed", sealed_order="c1")  # same run
    data.finish_sealed_run(config, root, "c1")
    with pytest.raises(data.SealedAccessError):
        data.load_items(config, root, "math500", "sealed", sealed_order="c1")
    monkeypatch.setenv("TEST_SEALED_ORDER", "c2")
    data.load_items(config, root, "math500", "sealed", sealed_order="c2")
    monkeypatch.setenv("TEST_SEALED_ORDER", "c3")
    with pytest.raises(data.SealedAccessError):
        data.load_items(config, root, "math500", "sealed", sealed_order="c3")  # cap of 2


def test_changed_split_file_is_refused(written):
    config, root, data_dir = written
    (data_dir / "splits/dev/math500.jsonl").write_text('{"id": "tampered"}\n')
    with pytest.raises(ValueError):
        data.load_items(config, root, "math500", "dev")
