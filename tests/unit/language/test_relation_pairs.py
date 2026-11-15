"""Relation pairs for contrastive similarity (T197): rules, leakage guard, rescan."""

import importlib.util
import random
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "build_relation_pairs.py"
spec = importlib.util.spec_from_file_location("build_relation_pairs", SCRIPT)
assert spec and spec.loader
brp = importlib.util.module_from_spec(spec)
sys.modules["build_relation_pairs"] = brp
spec.loader.exec_module(brp)

GATE = [
    "A man is playing a guitar on the stage tonight.",
    "Two dogs run across the green field together near the old barn.",
]


def make_builder() -> "brp.Builder":
    return brp.Builder(brp.GateIndex(GATE))


def test_normalise_and_windows():
    assert brp.normalise("Hello,  World!") == "hello world"
    assert list(brp.windows("a b c d e f g h i")) == [
        tuple("abcdefgh"),
        tuple("bcdefghi"),
    ]
    assert list(brp.windows("too short")) == []


def test_exact_and_window_leaks_are_dropped():
    b = make_builder()
    b.add(
        "s",
        "entailment",
        "positive",
        "a man is playing a guitar on the stage tonight",
        "Someone makes music.",
    )
    b.add(
        "s",
        "entailment",
        "positive",
        "Yesterday two dogs run across the green field together near the old barn today.",
        "Dogs move.",
    )
    b.add("s", "entailment", "positive", "A cat sleeps.", "An animal rests.")
    assert [r["sentence1"] for r in b.rows] == ["A cat sleeps."]
    assert b.counts["dropped_exact"][("s", "entailment")] == 1
    assert b.counts["dropped_window"][("s", "entailment")] == 1


def test_leak_on_second_sentence_is_dropped():
    b = make_builder()
    b.add(
        "s",
        "contradiction",
        "negative",
        "Nobody is here.",
        "A man is playing a guitar on the stage tonight.",
    )
    assert b.rows == []


def test_degenerate_and_duplicate_pairs():
    b = make_builder()
    b.add("s", "paraphrase_duplicate", "positive", "Same text.", "same   text!")
    b.add("s", "paraphrase_duplicate", "positive", "", "x")
    b.add("s", "paraphrase_duplicate", "positive", "How old are you?", "What is your age?")
    b.add("t", "paraphrase_duplicate", "positive", "What is your age?", "How old are you?")
    assert len(b.rows) == 1
    assert b.counts["dropped_degenerate"][("s", "paraphrase_duplicate")] == 2
    assert b.counts["dropped_duplicate"][("t", "paraphrase_duplicate")] == 1


def test_order_swapped_never_collides_with_its_adjacent_pair():
    b = make_builder()
    first, second = "Alpha comes before the second one.", "Beta follows right after it."
    for a, c in ((first, second), (second, first)):
        b.add("w", "adjacent_sentences", "positive", a, c)
    b.rows.clear()
    b.seen.clear()
    b.add("w", "adjacent_sentences", "positive", first, second)
    b.add("w", "order_swapped", "negative", second, first, symmetric=False)
    assert [r["relation"] for r in b.rows] == ["adjacent_sentences", "order_swapped"]
    assert [r["symmetric"] for r in b.rows] == [True, False]
    assert {r["label_source"] for r in b.rows} == {"derived"}


def test_split_sentences_and_adjacent_pair():
    text = "The first sentence is here today. The second sentence follows it. Third one ends it."
    assert len(brp.split_sentences(text)) == 3
    pair = brp.adjacent_pair(text, random.Random(0), 3, 20)
    assert pair in {
        ("The first sentence is here today.", "The second sentence follows it."),
        ("The second sentence follows it.", "Third one ends it."),
    }
    assert brp.adjacent_pair("Short. Tiny.", random.Random(0), 3, 20) is None
    # A newline inside a paragraph (heading, list) disables the pair.
    assert (
        brp.adjacent_pair(
            "Heading\nOne two three four. Five six seven eight.", random.Random(0), 2, 20
        )
        is None
    )
    # Seed-stable.
    assert brp.adjacent_pair(text, random.Random(5), 3, 20) == brp.adjacent_pair(
        text, random.Random(5), 3, 20
    )


def test_rule_accepts_by_label():
    rule = brp.Rule("entailment", "positive", "label", ("entailment",))
    assert rule.accepts({"label": "entailment"}) and not rule.accepts({"label": "neutral"})


def test_add_pair_source_applies_first_matching_rule(tmp_path):
    path = tmp_path / "train.parquet"
    pq.write_table(
        pa.table(
            {
                "premise": ["A boy plays outside now.", "A girl reads a long book.", "Rain falls."],
                "hypothesis": ["A child is outdoors.", "A girl sleeps in bed.", "It is dry today."],
                "label": ["entailment", "contradiction", "neutral"],
            }
        ),
        path,
    )
    b = make_builder()
    brp.add_pair_source(
        b,
        "nli",
        path,
        ("premise", "hypothesis"),
        [
            brp.Rule("entailment", "positive", "label", ("entailment",)),
            brp.Rule("contradiction", "negative", "label", ("contradiction",)),
        ],
    )
    assert [(r["relation"], r["polarity"]) for r in b.rows] == [
        ("entailment", "positive"),
        ("contradiction", "negative"),
    ]


def test_rescan_is_independent_and_finds_a_leak():
    clean = [("A cat sleeps.", "An animal rests.")]
    assert brp.rescan(clean, GATE) == {"pairs_checked": 1, "exact_hits": 0, "window_hits": 0}
    leaky = [
        ("A man is playing a guitar on the stage tonight!", "x y"),
        ("so two dogs run across the green field together near the old barn", "z"),
    ]
    scan = brp.rescan(leaky, GATE)
    assert scan["exact_hits"] == 1 and scan["window_hits"] == 1


def test_write_parquet_schema(tmp_path):
    b = make_builder()
    b.add("s", "entailment", "positive", "A cat sleeps.", "An animal rests.")
    out = tmp_path / "x" / "train.parquet"
    brp.write_parquet(b.rows, out)
    table = pq.read_table(out)
    assert table.schema.names == brp.SCHEMA.names and table.num_rows == 1
