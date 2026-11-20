"""Pluggable hooks of the retrieval adapters, as structural types.

The self-trained tokenizer and sentence encoder these hooks were written for were removed (T233,
D48); any object with the same methods can still be plugged in, and nothing is required: the
adapters fall back to a regex tokenizer and to caller-supplied vectors.
"""

from typing import Any, List, Protocol


class Pretokenizer(Protocol):
    def pre_tokenize(self, text: str) -> List[str]: ...


class EncodedSentence(Protocol):
    embedding: List[float]


class EncoderContract(Protocol):
    embedding_dim: int


class SentenceEmbedder(Protocol):
    def get_contract(self) -> Any: ...

    def encode_sentence(self, text: str) -> Any: ...
