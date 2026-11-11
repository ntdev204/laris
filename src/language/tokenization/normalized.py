"""SentencePiece processor that applies the corpus normalisation before encoding.

The tokenizer is fitted on text that went through `normalize_scientific_text` (typographic quotes
and dashes folded, ligatures unfolded, SI spacing standardised, whitespace collapsed). Raw text
fed to the bare processor contains characters the vocabulary never saw, so they become [UNK].
Wrapping the processor makes training and inference see the same text as the fit corpus.
Everything except the encode calls is forwarded unchanged.
"""

from typing import Any, List, Sequence, Union

from corpus.normalizer import normalize_scientific_text

NORMALIZATION_ID = "normalize_scientific_text+collapse_whitespace"


def normalize_for_tokenizer(text: str) -> str:
    """The exact transformation applied to every line of the tokenizer-fitting corpus."""
    return " ".join(normalize_scientific_text(text).split())


class NormalizedSentencePiece:
    """Forwarding wrapper whose encode methods normalise their input first."""

    def __init__(self, processor: Any) -> None:
        self._processor = processor

    def _prepare(self, text: Union[str, Sequence[str]]) -> Union[str, List[str]]:
        if isinstance(text, str):
            return normalize_for_tokenizer(text)
        return [normalize_for_tokenizer(item) for item in text]

    def encode(self, text: Union[str, Sequence[str]], *args: Any, **kwargs: Any) -> Any:
        return self._processor.encode(self._prepare(text), *args, **kwargs)

    def encode_as_ids(self, text: Union[str, Sequence[str]], *args: Any, **kwargs: Any) -> Any:
        return self._processor.encode_as_ids(self._prepare(text), *args, **kwargs)

    def encode_as_pieces(self, text: Union[str, Sequence[str]], *args: Any, **kwargs: Any) -> Any:
        return self._processor.encode_as_pieces(self._prepare(text), *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._processor, name)
