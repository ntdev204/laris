"""Two-segment sequence builder (T194): pair-format MLM and sentence-order records."""

import random
from pathlib import Path
from typing import Dict, List

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from laris.shared.config.schemas import TrainingConfig
from laris.shared.language.loading.dataloader import (
    CLS_ID,
    MASK_ID,
    PAD_ID,
    SEP_ID,
    StreamingParquetMultiTaskDataLoader,
)
from laris.shared.language.loading.segments import (
    IGNORE_INDEX,
    ORDER_IN_ORDER,
    ORDER_OTHER_DOCUMENT,
    ORDER_SWAPPED,
    build_pair_sequence,
    cut_two_segments,
    document_id,
    fit_pair,
    split_units,
)

WORD_IDS: Dict[str, int] = {}


class _Tok:
    """One id per distinct word, so a token id names its word (and its split and document)."""

    def encode_as_ids(self, text: str) -> List[int]:
        return [WORD_IDS.setdefault(w, 10 + len(WORD_IDS)) for w in text.split()]


class _Words:
    """Token id -> word, read from the tokenizer's table at lookup time."""

    def __getitem__(self, tok: int) -> str:
        return {v: k for k, v in WORD_IDS.items()}[int(tok)]


def _passage(split: str, doc: int, part: int, sentences: int = 4) -> str:
    return " ".join(f"S{split}{doc}p{part}s{k} w{split}{doc}x{part}y{k}." for k in range(sentences))


def _data(tmp_path: Path, docs: int = 12, parts: int = 2) -> Path:
    out = tmp_path / "fineweb_edu_en"
    out.mkdir()
    for split in ("train", "val"):
        rows = [
            {"id": f"<urn:{split}-{d}>#{p}", "text": _passage(split, d, p), "source": "fixture"}
            for d in range(docs)
            for p in range(parts)
        ]
        pq.write_table(pa.Table.from_pylist(rows), out / f"{split}.parquet")
    return tmp_path


def _loader(data: Path, **kwargs) -> StreamingParquetMultiTaskDataLoader:
    return StreamingParquetMultiTaskDataLoader(
        data_dir=data, tokenizer=_Tok(), vocab_size=100_000, seq_len=64, batch_size=4, seed=3,
        **kwargs,
    )  # fmt: skip


def _segments(row: np.ndarray) -> List[List[int]]:
    """Token ids between [CLS], [SEP] and padding."""
    out: List[List[int]] = [[]]
    for tok in row.tolist()[1:]:
        if tok == PAD_ID:
            break
        if tok == SEP_ID:
            out.append([])
        else:
            out[-1].append(tok)
    return [seg for seg in out if seg]


# ----------------------------------------------------------------------------- pure functions


def test_document_id_strips_passage_number():
    assert document_id({"id": "<urn:uuid:abc>#3"}) == "<urn:uuid:abc>"
    assert document_id({"id": "23583319"}) == "23583319"  # whole Wikipedia article
    assert document_id({"id": "a#b"}) == "a#b"
    assert document_id({"text": "x"}) == document_id({"text": "x"})


def test_split_units_cuts_at_sentences_and_paragraphs():
    text = 'First one. "Second" here! Third? fourth stays.\n\nNew paragraph'
    assert split_units(text) == [
        "First one.",
        '"Second" here!',
        "Third? fourth stays.",
        "New paragraph",
    ]
    assert split_units("e.g. lower case keeps going") == ["e.g. lower case keeps going"]


def test_cut_gives_two_consecutive_segments_or_none():
    rng = random.Random(0)
    text = "A one. B two. C three. D four."
    for _ in range(20):
        a, b = cut_two_segments(text, rng)
        assert a and b and f"{a} {b}" == text
    assert cut_two_segments("Only one sentence here", rng) is None


def test_fit_pair_keeps_the_junction():
    a, b = list(range(100)), list(range(100, 200))
    head, tail = fit_pair(a, b, 10)
    assert head == list(range(95, 100)) and tail == list(range(100, 105))
    head, tail = fit_pair([1, 2], b, 10)  # a short first segment gives its share to the second
    assert head == [1, 2] and tail == list(range(100, 108))
    head, tail = fit_pair(a, [7], 10)
    assert head == list(range(91, 100)) and tail == [7]


def test_pair_sequence_layout():
    seq, mask = build_pair_sequence([11, 12], [13], 8, CLS_ID, SEP_ID, PAD_ID)
    assert seq == [CLS_ID, 11, 12, SEP_ID, 13, SEP_ID, PAD_ID, PAD_ID]
    assert mask == [1, 1, 1, 1, 1, 1, 0, 0]
    seq, mask = build_pair_sequence(
        list(range(10, 40)), list(range(40, 70)), 16, CLS_ID, SEP_ID, PAD_ID
    )
    assert len(seq) == 16 and seq[0] == CLS_ID and seq.count(SEP_ID) == 2 and seq[-1] == SEP_ID
    assert sum(mask) == 16


# ----------------------------------------------------------------------------- loader


def test_default_is_unchanged(tmp_path):
    data = _data(tmp_path)
    plain = _loader(data).generate_batch("mlm")
    zero = _loader(data, mlm_pair_fraction=0.0).generate_batch("mlm")
    assert np.array_equal(plain.token_ids, zero.token_ids)
    assert np.array_equal(plain.labels["mlm_labels"], zero.labels["mlm_labels"])
    assert set(plain.labels) == {"mlm_labels"}
    assert all((plain.token_ids[i] == SEP_ID).sum() == 1 for i in range(plain.batch_size))


def test_pair_rows_hold_two_consecutive_segments_of_one_passage(tmp_path):
    loader = _loader(_data(tmp_path), mlm_pair_fraction=1.0, mlm_mask_prob=0.0)
    inverse = _Words()
    for _ in range(10):
        batch = loader.generate_batch("mlm")
        for row in batch.token_ids:
            a, b = _segments(row)
            words_a, words_b = [inverse[t] for t in a], [inverse[t] for t in b]
            assert words_a[0].startswith("S") and words_b[0].startswith("S")  # cut at a sentence
            prefix = lambda w: w[: w.index("s", 1)]  # noqa: E731  (split, document, passage)
            assert prefix(words_a[0]) == prefix(words_b[0])  # same passage, same document
            last_a, first_b = int(words_a[-2].rsplit("s", 1)[1]), int(words_b[0].rsplit("s", 1)[1])
            assert first_b == last_a + 1  # consecutive
    report = loader.two_segment_report()
    assert report["mlm_pair_share"] == 1.0 and report["mlm_sequences"] == 40


def test_masking_never_touches_special_ids(tmp_path):
    loader = _loader(_data(tmp_path), mlm_pair_fraction=1.0, mlm_mask_prob=1.0)
    batch = loader.generate_batch("mlm")
    special = np.isin(batch.token_ids, [CLS_ID, SEP_ID, PAD_ID])
    assert (batch.labels["mlm_labels"][special] == IGNORE_INDEX).all()
    assert ((batch.token_ids == SEP_ID).sum(axis=1) == 2).all()
    assert (batch.token_ids == MASK_ID).any()
    assert (
        batch.labels["mlm_labels"][~special & (batch.attention_mask == 1)] != IGNORE_INDEX
    ).all()


def test_pair_fraction_share(tmp_path):
    loader = _loader(_data(tmp_path), mlm_pair_fraction=0.5)
    for _ in range(100):
        loader.generate_batch("mlm")
    assert abs(loader.two_segment_report()["mlm_pair_share"] - 0.5) < 0.06


def test_order_classes_balanced_and_labelled(tmp_path):
    loader = _loader(_data(tmp_path), mlm_pair_fraction=1.0, order_task=True, mlm_mask_prob=0.0)
    inverse = _Words()
    seen = {ORDER_IN_ORDER: 0, ORDER_SWAPPED: 0, ORDER_OTHER_DOCUMENT: 0}
    for _ in range(150):
        batch = loader.generate_batch("mlm")
        for row, label in zip(batch.token_ids, batch.labels["order_labels"].tolist()):
            a, b = _segments(row)
            doc_a, doc_b = inverse[a[0]][1:].split("p")[0], inverse[b[0]][1:].split("p")[0]
            k_a, k_b = int(inverse[a[-2]].rsplit("s", 1)[1]), int(inverse[b[0]].rsplit("s", 1)[1])
            if label == ORDER_OTHER_DOCUMENT:
                assert doc_a != doc_b
            else:
                assert doc_a == doc_b
                assert (k_b > k_a) == (label == ORDER_IN_ORDER)
            seen[label] += 1
    total = sum(seen.values())
    assert all(abs(n / total - 1 / 3) < 0.05 for n in seen.values())
    report = loader.two_segment_report()
    assert report["order_counts"] == {
        "in_order": seen[0], "swapped": seen[1], "other_document": seen[2]
    }  # fmt: skip


def test_single_segment_rows_get_ignore_index(tmp_path):
    loader = _loader(_data(tmp_path), mlm_pair_fraction=0.5, order_task=True)
    for _ in range(20):
        batch = loader.generate_batch("mlm")
        seps = (batch.token_ids == SEP_ID).sum(axis=1)
        labels = batch.labels["order_labels"]
        assert ((labels == IGNORE_INDEX) == (seps == 1)).all()


def test_no_segment_crosses_splits(tmp_path):
    data = _data(tmp_path)
    for split in ("train", "val"):
        loader = _loader(
            data, split=split, mlm_pair_fraction=1.0, order_task=True, mlm_mask_prob=0.0
        )
        inverse = _Words()
        for _ in range(50):
            batch = loader.generate_batch("mlm")
            ids = batch.token_ids[batch.token_ids >= 10]
            assert {inverse[int(t)][1 : 1 + len(split)] for t in ids} == {split}


def test_other_document_falls_back_without_a_second_document(tmp_path):
    loader = _loader(_data(tmp_path, docs=1, parts=1), mlm_pair_fraction=1.0, order_task=True)
    for _ in range(30):
        labels = loader.generate_batch("mlm").labels["order_labels"]
        assert ORDER_OTHER_DOCUMENT not in labels.tolist()
    assert loader.two_segment_report()["order_other_document_unavailable"] > 0


def test_seed_stable_and_reset(tmp_path):
    data = _data(tmp_path)
    kwargs = dict(mlm_pair_fraction=0.5, order_task=True)
    one, two = _loader(data, **kwargs), _loader(data, **kwargs)
    first = [one.generate_batch("mlm") for _ in range(5)]
    for a, b in zip(first, [two.generate_batch("mlm") for _ in range(5)]):
        assert np.array_equal(a.token_ids, b.token_ids)
        assert np.array_equal(a.labels["order_labels"], b.labels["order_labels"])
    one.reset()
    assert np.array_equal(one.generate_batch("mlm").token_ids, first[0].token_ids)


def test_options_are_validated(tmp_path):
    data = _data(tmp_path)
    with pytest.raises(ValueError):
        _loader(data, mlm_pair_fraction=1.5)
    with pytest.raises(ValueError):
        _loader(data, order_task=True)
    with pytest.raises(ValueError):
        _loader(data, mlm_pair_fraction=0.5, order_class_shares=(0.0, 0.0, 0.0))
    assert TrainingConfig().mlm_pair_fraction == 0.0 and TrainingConfig().order_task is False
    with pytest.raises(ValueError):
        TrainingConfig(order_task=True)
    with pytest.raises(ValueError):
        TrainingConfig(mlm_pair_fraction=0.5, order_class_shares=(-1.0, 1.0, 1.0))
    TrainingConfig(mlm_pair_fraction=0.5, order_task=True)
