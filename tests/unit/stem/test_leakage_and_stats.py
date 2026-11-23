"""13-gram scanner on seeded hits, Wilson interval and summaries (T275, gates B6 and B1-B4)."""

import pytest

from laris.research.stem import leakage, stats

ITEM = {
    "id": "gpqa/r1",
    "question": "A particle of mass m moves in a central potential and its angular momentum is "
    "conserved because the torque about the centre vanishes at every instant of the motion",
    "options": [
        "the Runge Lenz vector is conserved only for the inverse square law of attraction here"
    ],
}


def test_seeded_hits_are_found_and_carry_no_text(tmp_path):
    notes = tmp_path / "notes"
    (notes / "sub").mkdir(parents=True)
    (notes / "clean.md").write_text("Angular momentum is conserved when the net torque is zero.")
    copied = " ".join(ITEM["question"].split()[3:17])  # 14 words of the question
    (notes / "sub" / "leak.md").write_text(f"Intro. {copied.upper()}, end.")
    (notes / "option.txt").write_text(" ".join(ITEM["options"][0].split()[:13]))
    (notes / "ignored.json").write_text(ITEM["question"])
    hits = leakage.scan_folder(notes, [ITEM], 13)
    assert {h["note"] for h in hits} == {"sub/leak.md", "option.txt"}
    assert sum(1 for h in hits if h["note"] == "sub/leak.md") == 2  # 14 words: two 13-grams
    for hit in hits:
        assert hit["item"] == "gpqa/r1" and len(hit["ngram_sha256"]) == 64
        assert "particle" not in str(hit) and "torque" not in str(hit)


def test_twelve_shared_words_are_not_a_hit(tmp_path):
    (tmp_path / "n.md").write_text(" ".join(ITEM["question"].split()[:12]))
    assert leakage.scan_folder(tmp_path, [ITEM], 13) == []


def test_wilson_interval():
    low, high = stats.wilson_interval(95, 100)
    assert low == pytest.approx(0.8882, abs=1e-4) and high == pytest.approx(0.9785, abs=1e-4)
    assert stats.wilson_interval(0, 0) == (0.0, 0.0)
    low, high = stats.wilson_interval(0, 10)
    assert low == 0.0 and 0 < high < 0.35
    assert stats.wilson_interval(10, 10)[1] == pytest.approx(1.0)


def test_summary_counts_and_costs():
    cost = stats.CostRecord(2.0, 10, 100, 1, 0, 5).as_dict()
    rows = [
        {"correct": True, "extracted": "A", "truncated": False, "cost": cost},
        {
            "correct": False,
            "extracted": None,
            "truncated": True,
            "cost": dict(cost, seconds=4.0, generated_tokens=300, peak_vram_bytes=9),
        },
    ]
    summary = stats.summarise(rows)
    assert summary["accuracy"] == 0.5 and summary["unparsed"] == 1 and summary["truncated"] == 1
    assert summary["seconds_median"] == 3.0 and summary["peak_vram_bytes"] == 9
    assert stats.percentile([1, 2, 3, 4, 5], 0.95) == pytest.approx(4.8)
