"""Normalising tokenizer wrapper: same text as the fit corpus, forwarding, and checkpoint wiring."""

from laris.shared.corpus.normalizer import normalize_scientific_text
from laris.shared.language.tokenization.normalized import (
    NORMALIZATION_ID,
    NormalizedSentencePiece,
    normalize_for_tokenizer,
)


class RecordingProcessor:
    """Stand-in processor that records what it is asked to encode."""

    def __init__(self):
        self.seen = []

    def encode(self, text, *args, **kwargs):
        self.seen.append(text)
        return [1]

    def encode_as_ids(self, text, *args, **kwargs):
        self.seen.append(text)
        return [2]

    def get_piece_size(self):
        return 48000


def test_normalisation_matches_the_fit_corpus_line_transformation():
    raw = "He said “hello” – it’s 10GHz…   done\n"
    expected = " ".join(normalize_scientific_text(raw).split())
    assert normalize_for_tokenizer(raw) == expected
    assert "“" not in expected and "–" not in expected and "10 GHz" in expected


def test_wrapper_normalises_single_and_batched_inputs_and_forwards_the_rest():
    inner = RecordingProcessor()
    wrapped = NormalizedSentencePiece(inner)
    assert wrapped.encode("a ’ b") == [1]
    assert wrapped.encode_as_ids(["x “y”", "z"]) == [2]
    assert inner.seen == ["a ' b", ['x "y"', "z"]]
    assert wrapped.get_piece_size() == 48000  # forwarded unchanged


def test_normalisation_id_is_a_stable_identifier():
    assert NORMALIZATION_ID == "normalize_scientific_text+collapse_whitespace"
