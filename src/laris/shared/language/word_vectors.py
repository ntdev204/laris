"""Word vectors read out of the encoder without training (T186).

Static vectors come from the token embedding table: a word is the mean of the embeddings of its
`NormalizedSentencePiece` pieces. Contextual vectors come from one inference-only forward pass: a
word is the mean of the final states of its pieces. Nothing is fitted and no gradient is taken.
The foundation model is NOT QUALIFIED: vectors from an untrained or unqualified encoder carry no
claim of quality, and neighbours are only as meaningful as the checkpoint they come from.
"""

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from laris.shared.language.loading.dataloader import build_sequence

_EPS = 1e-12


def embedding_table(model: Any) -> np.ndarray:
    """The (vocab, d_model) token embedding matrix of a torch or NumPy encoder, as float32."""
    table = getattr(model, "token_embeddings", None)
    if table is not None and hasattr(table, "weight"):  # torch.nn.Embedding
        return table.weight.detach().float().cpu().numpy()
    weights = getattr(model, "weights", None)
    if isinstance(weights, Mapping) and "token_embeddings" in weights:
        return np.asarray(weights["token_embeddings"], dtype=np.float32)
    raise TypeError("model has no token embedding table")


def _piece_ids(tokenizer: Any, word: str) -> List[int]:
    return [int(i) for i in tokenizer.encode_as_ids(word)] if word else []


def static_word_vector(embeddings: np.ndarray, tokenizer: Any, word: str) -> Optional[np.ndarray]:
    """Mean embedding of the pieces of `word`; None when the tokenizer yields no piece."""
    ids = _piece_ids(tokenizer, word)
    if not ids:
        return None
    return embeddings[ids].astype(np.float32).mean(axis=0)


def static_word_vectors(
    embeddings: np.ndarray, tokenizer: Any, words: Sequence[str]
) -> Dict[str, np.ndarray]:
    """One static vector per distinct word (first-seen order); words without pieces are skipped."""
    out: Dict[str, np.ndarray] = {}
    for word in words:
        if word not in out:
            vec = static_word_vector(embeddings, tokenizer, word)
            if vec is not None:
                out[word] = vec
    return out


def contextual_word_vectors(
    model: Any,
    tokenizer: Any,
    words: Sequence[str],
    seq_len: int,
    device: Optional[str] = None,
) -> List[Optional[np.ndarray]]:
    """One vector per word of a sentence: the mean final state of its pieces in one forward pass.

    The sentence is `[CLS] pieces [SEP]` as in every other inference path. A word with no piece,
    or one cut by the sequence limit, gets None. `model.forward` runs without gradient here.
    """
    import torch

    spans: List[Optional[Tuple[int, int]]] = []
    flat: List[int] = []
    for word in words:
        ids = _piece_ids(tokenizer, word)
        spans.append((len(flat), len(flat) + len(ids)) if ids else None)
        flat.extend(ids)
    ids_padded, mask = build_sequence(flat, None, seq_len)
    target = device or next(model.parameters()).device
    out = model(
        torch.tensor([ids_padded], dtype=torch.long, device=target),
        attention_mask=torch.tensor([mask], dtype=torch.long, device=target),
        task="embedding",
    )
    states = out["hidden_states"][0].float().cpu().numpy()
    kept = min(len(flat), max(0, seq_len - 2))  # pieces that fit between [CLS] and [SEP]
    result: List[Optional[np.ndarray]] = []
    for span in spans:
        if span is None or span[1] > kept:
            result.append(None)
        else:  # +1 skips [CLS]
            result.append(states[1 + span[0] : 1 + span[1]].mean(axis=0))
    return result


def contextual_vocabulary(
    model: Any,
    tokenizer: Any,
    sentences: Sequence[str],
    seq_len: int,
    device: Optional[str] = None,
) -> Dict[str, np.ndarray]:
    """Mean contextual vector per distinct word over every occurrence in `sentences`.

    Words are the whitespace-separated tokens of each sentence.
    """
    sums: Dict[str, np.ndarray] = {}
    counts: Dict[str, int] = {}
    for sentence in sentences:
        words = sentence.split()
        for word, vec in zip(
            words, contextual_word_vectors(model, tokenizer, words, seq_len, device)
        ):
            if vec is None:
                continue
            sums[word] = sums[word] + vec if word in sums else vec.astype(np.float64)
            counts[word] = counts.get(word, 0) + 1
    return {w: (s / counts[w]).astype(np.float32) for w, s in sums.items()}


class WordVectorIndex:
    """Cosine nearest-neighbour lookup over a fixed set of word vectors (exact, brute force)."""

    def __init__(self, vectors: Mapping[str, np.ndarray]) -> None:
        self.words: List[str] = list(vectors)
        if self.words:
            matrix = np.stack([np.asarray(vectors[w], dtype=np.float32) for w in self.words])
            norms = np.linalg.norm(matrix, axis=1, keepdims=True)
            self._unit = matrix / np.maximum(norms, _EPS)
        else:
            self._unit = np.zeros((0, 0), dtype=np.float32)

    def __len__(self) -> int:
        return len(self.words)

    def nearest(
        self, query: "np.ndarray | str", k: int = 5, exclude_self: bool = True
    ) -> List[Tuple[str, float]]:
        """The `k` most similar words; a str query is a member word, an array any vector.

        Ties are broken alphabetically so the order is deterministic.
        """
        if not self.words:
            if isinstance(query, str):
                raise KeyError(query)
            return []
        if isinstance(query, str):
            if query not in self.words:
                raise KeyError(query)
            vector = self._unit[self.words.index(query)]
            skip = query if exclude_self else None
        else:
            raw = np.asarray(query, dtype=np.float32)
            vector = raw / max(float(np.linalg.norm(raw)), _EPS)
            skip = None
        sims = self._unit @ vector
        scored = [(w, float(s)) for w, s in zip(self.words, sims) if w != skip]
        return sorted(scored, key=lambda x: (-x[1], x[0]))[: max(0, k)]
