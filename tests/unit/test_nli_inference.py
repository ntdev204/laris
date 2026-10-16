"""Unit and boundary tests for scientific NLI inference engine.

Task ID: M3-SEM-001-SUB-02 (Issue #85)
Boundary C: MOD-SEM-001 (Semantic Intelligence)
"""

import math

import pytest

from laris.core.errors import InvalidNLIInputError
from laris.language.encoder import CompactSentenceEncoder
from laris.language.schemas import VocabularyContract
from laris.language.stem_benchmark import get_stem_vocabulary_tokens
from laris.language.tokenizer import ScientificTokenizer
from laris.reasoning import (
    DeterministicScientificNLIEngine,
    NLILabel,
    SentencePairInput,
)


class TestNLIInferenceBehavior:
    """Verifies 3-way NLI inference behaviors across scientific semantic domains."""

    def setup_method(self) -> None:
        self.engine = DeterministicScientificNLIEngine()

        tokens = get_stem_vocabulary_tokens()
        general_words = [
            "the", "of", "in", "and", "to", "a", "with", "is", "for", "at",
            "on", "by", "from", "under", "where", "rates", "conditions",
            "demonstrates", "indicate", "yields", "exceeding", "mediate",
            "undergo", "compute", "optimizes", "characterize", "dominates",
        ]
        vocab = VocabularyContract.create(sorted(set(tokens + general_words)))
        tokenizer = ScientificTokenizer(vocab=vocab)
        encoder = CompactSentenceEncoder(tokenizer=tokenizer, embedding_dim=384, seed=42)
        self.encoder_engine = DeterministicScientificNLIEngine(encoder=encoder)

    def test_entailment_scientific_paraphrase(self) -> None:
        pair = SentencePairInput(
            premise="The alloy exhibited high tensile strength under extreme temperature.",
            hypothesis="Under extreme temperature, the alloy demonstrated high tensile strength.",
            pair_id="ENTAIL-001",
        )
        out = self.engine.infer(pair)
        assert out.prediction == NLILabel.ENTAILMENT
        assert out.probabilities[NLILabel.ENTAILMENT.value] >= 0.75
        assert math.isclose(sum(out.probabilities.values()), 1.0, abs_tol=1e-5)
        assert 0.0 <= out.uncertainty_score <= 1.0
        assert out.verify_contradiction_invariant() is True

    def test_entailment_with_dense_encoder(self) -> None:
        pair = SentencePairInput(
            premise="Superconductivity was confirmed below 93 Kelvin.",
            hypothesis="The material exhibited superconductivity below 93 Kelvin.",
            pair_id="ENTAIL-002",
        )
        out = self.encoder_engine.infer(pair)
        assert out.prediction == NLILabel.ENTAILMENT
        assert out.topical_similarity is not None
        assert out.topical_similarity >= 0.70

    def test_contradiction_antonym_clash_with_high_topical_similarity(self) -> None:
        """Core Invariant Test:

        Topical similarity must NEVER override NLI contradiction.
        Premise and hypothesis share ~85% vocabulary overlap, but express contradictory outcomes.
        """
        pair = SentencePairInput(
            premise="The alloy exhibited high tensile strength under extreme temperature.",
            hypothesis="The alloy suffered brittle fracture and failed under extreme temperature.",
            pair_id="CONTRA-001",
        )
        out = self.engine.infer(pair)
        assert out.prediction == NLILabel.CONTRADICTION
        assert out.probabilities[NLILabel.CONTRADICTION.value] >= 0.90
        assert out.verify_contradiction_invariant() is True

    def test_contradiction_directional_opposites(self) -> None:
        pairs = [
            (
                "The enzyme enhanced metabolic activity in the cellular assay.",
                "The enzyme inhibited metabolic activity in the cellular assay.",
            ),
            (
                "Target gene expression was upregulated following treatment.",
                "Target gene expression was downregulated following treatment.",
            ),
            (
                "Compound A is soluble in aqueous buffers.",
                "Compound A is insoluble in aqueous buffers.",
            ),
            (
                "The polymer behaved as an electrical conductor.",
                "The polymer behaved as an electrical insulator.",
            ),
        ]
        for premise, hypothesis in pairs:
            pair = SentencePairInput(premise=premise, hypothesis=hypothesis)
            out = self.engine.infer(pair)
            assert out.prediction == NLILabel.CONTRADICTION
            assert out.probabilities[NLILabel.CONTRADICTION.value] > 0.80
            assert out.verify_contradiction_invariant() is True

    def test_contradiction_direct_negation(self) -> None:
        pair = SentencePairInput(
            premise="The catalyst promotes hydrogen evolution reaction at low overpotential.",
            hypothesis="The catalyst does not promote hydrogen evolution reaction.",
            pair_id="CONTRA-NEG-001",
        )
        out = self.engine.infer(pair)
        assert out.prediction == NLILabel.CONTRADICTION
        assert out.probabilities[NLILabel.CONTRADICTION.value] >= 0.85

    def test_neutral_orthogonal_scientific_assertions(self) -> None:
        pair = SentencePairInput(
            premise="The crystal structure was resolved at 1.8 Angstrom resolution.",
            hypothesis="Specimens were incubated in a humidified atmosphere containing 5% CO2.",
            pair_id="NEUTRAL-001",
        )
        out = self.engine.infer(pair)
        assert out.prediction == NLILabel.NEUTRAL
        assert out.probabilities[NLILabel.NEUTRAL.value] >= 0.70
        assert 0.0 <= out.uncertainty_score <= 1.0


class TestNLIBoundaryAndResourceGates:
    """Verifies edge cases, context span absence, empty inputs, and latency budgets."""

    def setup_method(self) -> None:
        self.engine = DeterministicScientificNLIEngine()

    def test_context_absence_graceful_handling(self) -> None:
        pair = SentencePairInput(
            premise="Quantum phase transitions occur at absolute zero.",
            hypothesis="Thermal fluctuations vanish at absolute zero.",
            context_span=None,
        )
        out = self.engine.infer(pair)
        assert out.context_span is None
        assert out.prediction in (NLILabel.ENTAILMENT, NLILabel.NEUTRAL)

    def test_context_presence_preservation(self) -> None:
        pair = SentencePairInput(
            premise="Premise text here.",
            hypothesis="Hypothesis text here.",
            context_span="Discourse unit paragraph 4, page 12.",
        )
        out = self.engine.infer(pair)
        assert out.context_span == "Discourse unit paragraph 4, page 12."

    def test_empty_input_rejection(self) -> None:
        with pytest.raises(InvalidNLIInputError):
            SentencePairInput(premise="", hypothesis="Valid hypothesis")

        with pytest.raises(InvalidNLIInputError):
            SentencePairInput(premise="Valid premise", hypothesis="   \n")

    def test_invalid_type_to_infer_raises(self) -> None:
        with pytest.raises(InvalidNLIInputError, match="pair must be an instance"):
            self.engine.infer("not a sentence pair input")  # type: ignore[arg-type]

    def test_batch_inference_and_latency_budget(self) -> None:
        """Boundary C requirement: Latency < 50 ms per pair."""
        pairs = [
            SentencePairInput(
                premise=f"Scientific premise statement number {i} regarding thermodynamics.",
                hypothesis=f"Scientific hypothesis statement number {i} regarding thermodynamics.",
                pair_id=f"PAIR-BATCH-{i:03d}",
            )
            for i in range(20)
        ]
        outputs = self.engine.infer_batch(pairs)
        assert len(outputs) == 20
        for out in outputs:
            latency = out.metadata.get("latency_ms", 0.0)
            assert latency < 50.0, f"Latency {latency} ms exceeded 50 ms ceiling"
            assert math.isclose(sum(out.probabilities.values()), 1.0, abs_tol=1e-5)
            assert 0.0 <= out.uncertainty_score <= 1.0
            assert out.metadata["tier_resource"] == "Tier 2 (<= 2.0 GB VRAM)"

    def test_pair_metadata_and_empty_tokens_edge_cases(self) -> None:
        # Pair with custom metadata
        pair = SentencePairInput(
            premise="Theorem A holds.",
            hypothesis="Theorem A holds unconditionally.",
            metadata={"source_experiment": "exp_01", "run_id": 99},
        )
        out = self.engine.infer(pair)
        assert out.metadata["source_experiment"] == "exp_01"
        assert out.metadata["run_id"] == 99

        # Text with no multi-char words (single chars)
        single_char_pair = SentencePairInput(
            premise="a b c",
            hypothesis="x y z",
        )
        sim = self.engine._compute_topical_similarity(
            single_char_pair.premise, single_char_pair.hypothesis
        )
        assert sim == 0.0

    def test_invariant_violation_raises_runtime_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from laris.reasoning import NLIOutput

        monkeypatch.setattr(NLIOutput, "verify_contradiction_invariant", lambda self: False)
        pair = SentencePairInput(premise="A holds.", hypothesis="A holds.")
        with pytest.raises(RuntimeError, match="MOD-SEM-001 Invariant Violation"):
            self.engine.infer(pair)
