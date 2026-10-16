"""Scientific tokenizer implementation and STEM fertility evaluation engine.

Implements Boundary B (MOD-LANG-001) WordPiece subword tokenization preserving:
- Mathematical expressions and LaTeX formulas ($...$)
- Greek alphabetic characters
- SI unit notations and numeric scientific quantities
- Reproducible STEM fertility metrics and report generation
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from laris.core.errors import ModuleContractViolationError
from laris.language.schemas import (
    CLS_TOKEN,
    DEFAULT_MAX_SEQUENCE_LENGTH,
    SEP_TOKEN,
    UNK_TOKEN,
    TokenizedSentenceOutput,
    VocabularyContract,
)
from laris.language.stem_benchmark import (
    STEM_BENCHMARK_FIXTURES,
    STEM_BENCHMARK_VERSION,
    StemBenchmarkSample,
)

# Regex pattern splitting text while preserving LaTeX inline math and punctuation
_MATH_OR_WORD_REGEX = re.compile(
    r"(\$\$[^\$]+\$\$|\$[^\$]+\$|[a-zA-Z0-9_\u0370-\u03ff]+|[^\s\w])"
)


class ScientificTokenizer:
    """Deterministic scientific tokenizer using WordPiece subword segmentation."""

    def __init__(
        self,
        vocab: VocabularyContract,
        do_lower_case: bool = True,
        max_sequence_length: int = DEFAULT_MAX_SEQUENCE_LENGTH,
    ) -> None:
        self.vocab = vocab
        self.do_lower_case = do_lower_case
        self.max_sequence_length = max_sequence_length

    @property
    def vocab_contract(self) -> VocabularyContract:
        """Returns the underlying vocabulary contract."""
        return self.vocab

    def pre_tokenize(self, text: str) -> List[str]:
        """Splits raw text into tokens while preserving math blocks and symbols."""
        if not text or not text.strip():
            return []
        tokens: List[str] = []
        for match in _MATH_OR_WORD_REGEX.finditer(text):
            tok = match.group(0).strip()
            if not tok:
                continue
            # Preserve LaTeX math verbatim; lower-case natural words if configured
            if tok.startswith("$"):
                tokens.append(tok)
            else:
                tokens.append(tok.lower() if self.do_lower_case else tok)
        return tokens

    def _wordpiece_tokenize(self, word: str) -> List[str]:
        """Applies greedy longest-match WordPiece tokenization to a single word."""
        if word in self.vocab.token_to_id:
            return [word]

        # WordPiece segmentation with ## continuation prefix
        subwords: List[str] = []
        start = 0
        word_len = len(word)
        is_bad = False

        while start < word_len:
            end = word_len
            cur_substr: Optional[str] = None
            while start < end:
                substr = word[start:end]
                if start > 0:
                    substr = "##" + substr
                if substr in self.vocab.token_to_id:
                    cur_substr = substr
                    break
                end -= 1

            if cur_substr is None:
                is_bad = True
                break

            subwords.append(cur_substr)
            start = end

        if is_bad:
            return [UNK_TOKEN]
        return subwords

    def tokenize(self, text: str) -> List[str]:
        """Tokenizes scientific text into subwords."""
        raw_tokens = self.pre_tokenize(text)
        subword_tokens: List[str] = []
        for token in raw_tokens:
            if token.startswith("$") or token in self.vocab.token_to_id:
                subword_tokens.append(token if token in self.vocab.token_to_id else UNK_TOKEN)
            else:
                subword_tokens.extend(self._wordpiece_tokenize(token))
        return subword_tokens

    def encode(self, text: str, add_special_tokens: bool = True) -> TokenizedSentenceOutput:
        """Encodes text into a validated TokenizedSentenceOutput payload."""
        if not isinstance(text, str):
            raise ModuleContractViolationError("Input text must be a string")

        subwords = self.tokenize(text)
        tokens: List[str] = []
        token_ids: List[int] = []

        if add_special_tokens:
            tokens.append(CLS_TOKEN)
            token_ids.append(self.vocab.token_to_id[CLS_TOKEN])

        for tok in subwords:
            tid = self.vocab.token_to_id.get(tok, self.vocab.token_to_id[UNK_TOKEN])
            tokens.append(tok)
            token_ids.append(tid)

        if add_special_tokens:
            tokens.append(SEP_TOKEN)
            token_ids.append(self.vocab.token_to_id[SEP_TOKEN])

        return TokenizedSentenceOutput(
            token_ids=token_ids,
            tokens=tokens,
            max_sequence_length=self.max_sequence_length,
        )

    def decode(self, token_ids: List[int], skip_special_tokens: bool = True) -> str:
        """Decodes token IDs back into readable scientific text."""
        special_tokens_set = set(self.vocab.special_tokens.to_dict().keys())
        words: List[str] = []

        for tid in token_ids:
            tok = self.vocab.id_to_token.get(tid, UNK_TOKEN)
            if skip_special_tokens and tok in special_tokens_set:
                continue
            if tok.startswith("##"):
                if words:
                    words[-1] = words[-1] + tok[2:]
                else:
                    words.append(tok[2:])
            else:
                words.append(tok)

        return " ".join(words)


def compute_token_fertility(text: str, tokenizer: ScientificTokenizer) -> Tuple[float, int, int]:
    """Computes the token-to-word fertility ratio for a given text.

    Returns:
        (fertility, word_count, token_count)
    """
    words = text.strip().split()
    word_count = len(words)
    if word_count == 0:
        return 0.0, 0, 0

    tokens = tokenizer.tokenize(text)
    token_count = len(tokens)
    fertility = token_count / word_count
    return fertility, word_count, token_count


@dataclass(frozen=True)
class StemFertilityReport:
    """Immutable, auditable evaluation report measuring tokenizer fertility on STEM text."""

    benchmark_version: str
    vocab_size: int
    vocab_sha256: str
    num_samples: int
    total_words: int
    total_tokens: int
    average_fertility: float
    max_fertility: float
    min_fertility: float
    domain_fertility: Dict[str, float]
    baseline_fertility: Optional[float] = None
    fertility_reduction_pct: Optional[float] = None
    report_sha256: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serializes report to dictionary."""
        return {
            "benchmark_version": self.benchmark_version,
            "vocab_size": self.vocab_size,
            "vocab_sha256": self.vocab_sha256,
            "num_samples": self.num_samples,
            "total_words": self.total_words,
            "total_tokens": self.total_tokens,
            "average_fertility": round(self.average_fertility, 4),
            "max_fertility": round(self.max_fertility, 4),
            "min_fertility": round(self.min_fertility, 4),
            "domain_fertility": {k: round(v, 4) for k, v in self.domain_fertility.items()},
            "baseline_fertility": (
                round(self.baseline_fertility, 4) if self.baseline_fertility else None
            ),
            "fertility_reduction_pct": (
                round(self.fertility_reduction_pct, 2) if self.fertility_reduction_pct else None
            ),
            "report_sha256": self.report_sha256,
            "metadata": dict(self.metadata),
        }

    def to_json(self, indent: int = 2) -> str:
        """Serializes report to JSON string."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


def evaluate_stem_fertility(
    tokenizer: ScientificTokenizer,
    samples: Optional[List[StemBenchmarkSample]] = None,
    baseline_tokenizer: Optional[ScientificTokenizer] = None,
) -> StemFertilityReport:
    """Generates a comprehensive, reproducible STEM fertility evaluation report."""
    benchmark_samples = samples or STEM_BENCHMARK_FIXTURES
    domain_words: Dict[str, int] = {}
    domain_tokens: Dict[str, int] = {}

    total_words = 0
    total_tokens = 0
    sample_fertilities: List[float] = []

    for sample in benchmark_samples:
        fert, wc, tc = compute_token_fertility(sample.text, tokenizer)
        total_words += wc
        total_tokens += tc
        sample_fertilities.append(fert)

        domain_words[sample.domain] = domain_words.get(sample.domain, 0) + wc
        domain_tokens[sample.domain] = domain_tokens.get(sample.domain, 0) + tc

    domain_fertility = {
        domain: (domain_tokens[domain] / domain_words[domain]) if domain_words[domain] > 0 else 0.0
        for domain in domain_words
    }

    avg_fertility = total_tokens / total_words if total_words > 0 else 0.0
    max_fertility = max(sample_fertilities) if sample_fertilities else 0.0
    min_fertility = min(sample_fertilities) if sample_fertilities else 0.0

    # Optional baseline comparison
    baseline_fertility = None
    reduction_pct = None
    if baseline_tokenizer is not None:
        base_words = 0
        base_tokens = 0
        for sample in benchmark_samples:
            _, b_wc, b_tc = compute_token_fertility(sample.text, baseline_tokenizer)
            base_words += b_wc
            base_tokens += b_tc
        if base_words > 0:
            baseline_fertility = base_tokens / base_words
            if baseline_fertility > 0:
                reduction_pct = ((baseline_fertility - avg_fertility) / baseline_fertility) * 100.0

    raw_report_data = (
        f"{STEM_BENCHMARK_VERSION}:{tokenizer.vocab.vocab_sha256}:{total_words}:{total_tokens}:"
        f"{avg_fertility:.6f}"
    )
    report_sha256 = hashlib.sha256(raw_report_data.encode("utf-8")).hexdigest()

    return StemFertilityReport(
        benchmark_version=STEM_BENCHMARK_VERSION,
        vocab_size=tokenizer.vocab.vocab_size,
        vocab_sha256=tokenizer.vocab.vocab_sha256,
        num_samples=len(benchmark_samples),
        total_words=total_words,
        total_tokens=total_tokens,
        average_fertility=avg_fertility,
        max_fertility=max_fertility,
        min_fertility=min_fertility,
        domain_fertility=domain_fertility,
        baseline_fertility=baseline_fertility,
        fertility_reduction_pct=reduction_pct,
        report_sha256=report_sha256,
    )


# Alias for backwards compatibility / domain terminology
STEMSubwordTokenizer = ScientificTokenizer

