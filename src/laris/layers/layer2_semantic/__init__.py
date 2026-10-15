"""Layer 2: Semantic Intelligence & Relational Logic.

Provides Natural Language Inference (NLI), semantic equivalence, coreference resolution,
and discourse parsing conforming to Boundary C (MOD-SEM-001).
"""

from laris.layers.layer2_semantic.engine import (
    DIRECT_NEGATIONS,
    SCIENTIFIC_OPPOSITES,
    DeterministicScientificNLIEngine,
)
from laris.layers.layer2_semantic.schemas import (
    LN_3,
    PROBABILITY_SUM_TOLERANCE,
    NLIEngineContract,
    NLILabel,
    NLIOutput,
    NLIOutputBatch,
    NLIPairBatch,
    NLIProbabilities,
    SentencePairInput,
)

__all__ = [
    "NLILabel",
    "SentencePairInput",
    "NLIProbabilities",
    "NLIOutput",
    "NLIPairBatch",
    "NLIOutputBatch",
    "NLIEngineContract",
    "DeterministicScientificNLIEngine",
    "SCIENTIFIC_OPPOSITES",
    "DIRECT_NEGATIONS",
    "PROBABILITY_SUM_TOLERANCE",
    "LN_3",
]
