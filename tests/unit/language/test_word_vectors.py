"""Word vectors from the encoder (T186): shapes, determinism, piece pooling, no training.

Tiny random-weight encoder; forward passes only: no backward step, no optimizer step.
"""

import numpy as np
import pytest
import torch

from laris.shared.language.encoder.transformer import (
    LanguageEncoderConfig,
    PyTorchTransformerEncoder,
    RandomlyInitializedTransformerEncoder,
)
from laris.shared.language.loading.dataloader import build_sequence
from laris.shared.language.word_vectors import (
    WordVectorIndex,
    contextual_vocabulary,
    contextual_word_vectors,
    embedding_table,
    static_word_vector,
    static_word_vectors,
)

VOCAB = 200
SEQ = 16


class _PieceTok:
    """Splits a word into 2-character pieces with stable ids; the empty word has no piece."""

    def encode_as_ids(self, text):
        return [10 + sum(map(ord, text[i : i + 2])) % (VOCAB - 10) for i in range(0, len(text), 2)]


def _model(seed: int = 7) -> PyTorchTransformerEncoder:
    cfg = LanguageEncoderConfig(
        d_model=384, num_layers=2, num_heads=6, d_ff=1536, vocab_size=VOCAB,
        max_sequence_length=SEQ, seed=seed,
    )  # fmt: skip
    return PyTorchTransformerEncoder(cfg)


def test_static_vector_is_the_mean_of_its_piece_embeddings():
    model, tok = _model(), _PieceTok()
    table = embedding_table(model)
    assert table.shape == (VOCAB, 384) and table.dtype == np.float32
    ids = tok.encode_as_ids("lithium")  # 4 pieces
    assert len(ids) == 4
    expected = table[ids].mean(axis=0)
    vec = static_word_vector(table, tok, "lithium")
    assert vec.shape == (384,)
    np.testing.assert_allclose(vec, expected, rtol=1e-6)
    np.testing.assert_array_equal(vec, static_word_vector(table, tok, "lithium"))  # deterministic
    assert static_word_vector(table, tok, "") is None
    single = static_word_vector(table, tok, "ab")  # one piece: the row itself
    np.testing.assert_array_equal(single, table[tok.encode_as_ids("ab")[0]])


def test_static_vectors_dedupe_and_skip_empty_words():
    table = embedding_table(_model())
    out = static_word_vectors(table, _PieceTok(), ["anode", "", "anode", "cathode"])
    assert list(out) == ["anode", "cathode"]


def test_numpy_encoder_exposes_the_same_kind_of_table():
    cfg = LanguageEncoderConfig(
        d_model=384, num_layers=1, num_heads=6, d_ff=1536, vocab_size=VOCAB,
        max_sequence_length=SEQ,
    )  # fmt: skip
    table = embedding_table(RandomlyInitializedTransformerEncoder(cfg))
    assert table.shape == (VOCAB, 384)
    with pytest.raises(TypeError):
        embedding_table(object())


def test_contextual_vector_is_the_mean_of_piece_states_of_one_forward_pass():
    model, tok = _model(), _PieceTok()
    words = ["lithium", "ion", "anode"]
    vectors = contextual_word_vectors(model, tok, words, SEQ)
    flat = [i for w in words for i in tok.encode_as_ids(w)]  # 4 + 2 + 3 pieces
    ids, mask = build_sequence(flat, None, SEQ)
    out = model(torch.tensor([ids]), attention_mask=torch.tensor([mask]))
    states = out["hidden_states"][0].numpy()
    np.testing.assert_allclose(vectors[0], states[1:5].mean(axis=0), rtol=1e-5, atol=1e-6)
    np.testing.assert_allclose(vectors[1], states[5:7].mean(axis=0), rtol=1e-5, atol=1e-6)
    np.testing.assert_allclose(vectors[2], states[7:10].mean(axis=0), rtol=1e-5, atol=1e-6)
    again = contextual_word_vectors(model, tok, words, SEQ)
    assert all(np.array_equal(a, b) for a, b in zip(vectors, again))  # deterministic


def test_words_without_pieces_or_cut_by_the_limit_get_none():
    model, tok = _model(), _PieceTok()
    got = contextual_word_vectors(model, tok, ["ab", "", "x" * 40, "cd"], SEQ)
    assert got[0] is not None and got[1] is None
    assert got[2] is None and got[3] is None  # 20 pieces do not fit in 14 slots; "cd" follows
    assert contextual_word_vectors(model, tok, [], SEQ) == []


def test_contextual_vocabulary_averages_occurrences():
    model, tok = _model(), _PieceTok()
    sentences = ["anode ion", "ion anode", "ion"]
    vocab = contextual_vocabulary(model, tok, sentences, SEQ)
    assert set(vocab) == {"anode", "ion"}
    manual = np.mean(
        [contextual_word_vectors(model, tok, s.split(), SEQ)[s.split().index("ion")]
         for s in sentences],
        axis=0,
    )  # fmt: skip
    np.testing.assert_allclose(vocab["ion"], manual, rtol=1e-5, atol=1e-6)
    assert vocab["ion"].dtype == np.float32


def test_nearest_neighbours_by_cosine_with_deterministic_ties():
    index = WordVectorIndex(
        {"a": np.array([1.0, 0.0]), "b": np.array([2.0, 0.0]), "c": np.array([0.0, 1.0]),
         "d": np.array([1.0, 1.0])}
    )  # fmt: skip
    assert len(index) == 4
    near = index.nearest("a", k=3)
    assert [w for w, _ in near] == ["b", "d", "c"]  # b ties a in direction; self excluded
    assert near[0][1] == pytest.approx(1.0) and near[1][1] == pytest.approx(2**-0.5)
    assert index.nearest("a", k=1, exclude_self=False)[0] == ("a", pytest.approx(1.0))
    assert index.nearest(np.array([0.0, 5.0]), k=1)[0][0] == "c"
    with pytest.raises(KeyError):
        index.nearest("zzz")
    assert WordVectorIndex({}).nearest(np.zeros(2), k=3) == []


def test_reading_vectors_changes_no_weight_and_takes_no_gradient():
    model, tok = _model(), _PieceTok()
    before = {k: v.clone() for k, v in model.state_dict().items()}
    contextual_word_vectors(model, tok, ["lithium", "anode"], SEQ)
    embedding_table(model)
    assert all(torch.equal(before[k], v) for k, v in model.state_dict().items())
    assert all(p.grad is None for p in model.parameters())
