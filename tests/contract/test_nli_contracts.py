"""Contract validation tests for Layer 2 Semantic Intelligence and NLI.

Module ID: MOD-SEM-001 (Boundary C)
Governed by: docs/specifications/MODULE_CONTRACTS.md and ADR-002
"""

import math

import pytest

from laris.core.errors import (
    InvalidNLIInputError,
    ProbabilityValidationError,
    UncertaintyCeilingExceededError,
)
from laris.reasoning import (
    NLIEngineContract,
    NLILabel,
    NLIOutput,
    NLIOutputBatch,
    NLIPairBatch,
    NLIProbabilities,
    SentencePairInput,
)


class TestSentencePairInputContract:
    """Verifies interface invariants for SentencePairInput."""

    def test_valid_input_creation(self) -> None:
        inp = SentencePairInput(
            premise="The superconductor exhibits zero electrical resistance below 93 Kelvin.",
            hypothesis="The material conducts electricity without resistance at low temperatures.",
            context_span="Cuprate high-temperature superconductors section.",
            pair_id="PAIR-001",
            metadata={"domain": "condensed_matter"},
        )
        assert inp.premise.startswith("The superconductor")
        assert inp.hypothesis.startswith("The material conducts")
        assert inp.context_span == "Cuprate high-temperature superconductors section."
        assert inp.pair_id == "PAIR-001"
        assert inp.metadata["domain"] == "condensed_matter"

    def test_empty_or_whitespace_premise_raises_invalid_input(self) -> None:
        with pytest.raises(InvalidNLIInputError, match="Premise must be non-empty string"):
            SentencePairInput(premise="", hypothesis="Valid hypothesis")

        with pytest.raises(InvalidNLIInputError, match="Premise must be non-empty string"):
            SentencePairInput(premise="   \n\t  ", hypothesis="Valid hypothesis")

    def test_non_string_premise_raises_invalid_input(self) -> None:
        with pytest.raises(InvalidNLIInputError, match="Premise must be non-empty string"):
            SentencePairInput(premise=12345, hypothesis="Valid hypothesis")  # type: ignore[arg-type]

    def test_empty_or_whitespace_hypothesis_raises_invalid_input(self) -> None:
        with pytest.raises(InvalidNLIInputError, match="Hypothesis must be non-empty string"):
            SentencePairInput(premise="Valid premise", hypothesis="")

        with pytest.raises(InvalidNLIInputError, match="Hypothesis must be non-empty string"):
            SentencePairInput(premise="Valid premise", hypothesis="   ")

    def test_non_string_hypothesis_raises_invalid_input(self) -> None:
        with pytest.raises(InvalidNLIInputError, match="Hypothesis must be non-empty string"):
            SentencePairInput(premise="Valid premise", hypothesis=None)  # type: ignore[arg-type]

    def test_invalid_context_span_type_raises(self) -> None:
        with pytest.raises(InvalidNLIInputError, match="context_span must be string or None"):
            SentencePairInput(premise="Premise", hypothesis="Hypothesis", context_span=100)  # type: ignore[arg-type]

    def test_serialization_round_trip(self) -> None:
        inp = SentencePairInput(
            premise="Theorem 1 guarantees convergence.",
            hypothesis="Convergence is guaranteed under Theorem 1.",
            context_span="Section 4 proof sketch.",
            pair_id="PAIR-002",
        )
        d = inp.to_dict()
        restored = SentencePairInput.from_dict(d)
        assert restored == inp

        json_str = inp.to_json()
        from_json = SentencePairInput.from_json(json_str)
        assert from_json == inp


class TestNLIProbabilitiesContract:
    """Verifies mathematical constraints on 3-way NLI probability distributions."""

    def test_valid_probabilities(self) -> None:
        probs = NLIProbabilities(entailment=0.85, contradiction=0.05, neutral=0.10)
        assert probs.entailment == 0.85
        assert probs.contradiction == 0.05
        assert probs.neutral == 0.10
        assert probs.predicted_label() == NLILabel.ENTAILMENT
        assert math.isclose(probs.margin(), 0.75, abs_tol=1e-6)

    def test_sum_tolerance_boundary(self) -> None:
        # 0.850004 + 0.05 + 0.10 = 1.000004 (diff = 4e-6 < 1e-5 tolerance)
        probs = NLIProbabilities(entailment=0.850004, contradiction=0.05, neutral=0.10)
        d = probs.to_dict()
        assert d[NLILabel.ENTAILMENT.value] == 0.850004

    def test_sum_exceeding_tolerance_raises(self) -> None:
        with pytest.raises(ProbabilityValidationError, match="must sum to 1.0 within tolerance"):
            NLIProbabilities(entailment=0.85, contradiction=0.15, neutral=0.10)

        with pytest.raises(ProbabilityValidationError, match="must sum to 1.0 within tolerance"):
            NLIProbabilities(entailment=0.20, contradiction=0.20, neutral=0.20)

    def test_negative_probability_raises(self) -> None:
        with pytest.raises(ProbabilityValidationError, match="out of bounds"):
            NLIProbabilities(entailment=-0.01, contradiction=0.51, neutral=0.50)

    def test_greater_than_one_probability_raises(self) -> None:
        with pytest.raises(ProbabilityValidationError, match="out of bounds"):
            NLIProbabilities(entailment=1.05, contradiction=-0.02, neutral=-0.03)

    def test_nan_or_inf_probability_raises(self) -> None:
        with pytest.raises(ProbabilityValidationError, match="must be a valid real number"):
            NLIProbabilities(entailment=float("nan"), contradiction=0.5, neutral=0.5)

        with pytest.raises(ProbabilityValidationError, match="must be a valid real number"):
            NLIProbabilities(entailment=float("inf"), contradiction=0.5, neutral=0.5)

    def test_tie_breaking_prioritizes_contradiction(self) -> None:
        probs = NLIProbabilities(entailment=0.5, contradiction=0.5, neutral=0.0)
        assert probs.predicted_label() == NLILabel.CONTRADICTION

    def test_normalized_entropy(self) -> None:
        # Deterministic: entropy = 0.0
        det_probs = NLIProbabilities(entailment=1.0, contradiction=0.0, neutral=0.0)
        assert math.isclose(det_probs.normalized_entropy(), 0.0, abs_tol=1e-6)

        # Uniform: entropy = 1.0
        unif_probs = NLIProbabilities(
            entailment=1.0 / 3.0, contradiction=1.0 / 3.0, neutral=1.0 / 3.0
        )
        assert math.isclose(unif_probs.normalized_entropy(), 1.0, abs_tol=1e-6)

        # In-between
        skewed = NLIProbabilities(entailment=0.7, contradiction=0.2, neutral=0.1)
        ent = skewed.normalized_entropy()
        assert 0.0 < ent < 1.0

    def test_dictionary_round_trip(self) -> None:
        raw = {"entailment": 0.1, "contradiction": 0.8, "neutral": 0.1}
        probs = NLIProbabilities.from_dict(raw)
        assert probs.predicted_label() == NLILabel.CONTRADICTION
        assert probs.to_dict()["CONTRADICTION"] == 0.8

    def test_missing_key_in_dict_raises(self) -> None:
        with pytest.raises(ProbabilityValidationError, match="Missing required NLI probability"):
            NLIProbabilities.from_dict({"entailment": 0.5, "neutral": 0.5})


class TestNLIOutputContract:
    """Verifies output contracts for Boundary C NLIOutput."""

    def test_valid_output(self) -> None:
        out = NLIOutput(
            prediction=NLILabel.ENTAILMENT,
            probabilities={"ENTAILMENT": 0.92, "CONTRADICTION": 0.02, "NEUTRAL": 0.06},
            uncertainty_score=0.15,
            pair_id="PAIR-003",
            topical_similarity=0.88,
            context_span="Background literature section.",
        )
        assert out.prediction == NLILabel.ENTAILMENT
        assert out.uncertainty_score == 0.15
        assert out.topical_similarity == 0.88
        assert out.verify_contradiction_invariant() is True

    def test_string_prediction_coercion(self) -> None:
        out = NLIOutput(
            prediction="CONTRADICTION",  # type: ignore[arg-type]
            probabilities={"ENTAILMENT": 0.05, "CONTRADICTION": 0.90, "NEUTRAL": 0.05},
            uncertainty_score=0.10,
        )
        assert out.prediction == NLILabel.CONTRADICTION

    def test_invalid_prediction_string_raises(self) -> None:
        with pytest.raises(InvalidNLIInputError, match="Unknown NLI label"):
            NLIOutput(
                prediction="UNKNOWN_LABEL",  # type: ignore[arg-type]
                probabilities={"ENTAILMENT": 0.05, "CONTRADICTION": 0.90, "NEUTRAL": 0.05},
                uncertainty_score=0.10,
            )

    def test_uncertainty_score_bounds_enforcement(self) -> None:
        probs = {"ENTAILMENT": 0.8, "CONTRADICTION": 0.1, "NEUTRAL": 0.1}
        with pytest.raises(UncertaintyCeilingExceededError, match="out of range"):
            NLIOutput(
                prediction=NLILabel.ENTAILMENT,
                probabilities=probs,
                uncertainty_score=1.05,
            )

        with pytest.raises(UncertaintyCeilingExceededError, match="out of range"):
            NLIOutput(
                prediction=NLILabel.ENTAILMENT,
                probabilities=probs,
                uncertainty_score=-0.01,
            )

    def test_topical_similarity_bounds_enforcement(self) -> None:
        probs = {"ENTAILMENT": 0.8, "CONTRADICTION": 0.1, "NEUTRAL": 0.1}
        with pytest.raises(InvalidNLIInputError, match="out of range"):
            NLIOutput(
                prediction=NLILabel.ENTAILMENT,
                probabilities=probs,
                uncertainty_score=0.2,
                topical_similarity=1.5,
            )

    def test_contradiction_invariant_topical_similarity_override_protection(self) -> None:
        """Invariant: High topical similarity MUST NOT override a contradiction."""
        # Case 1: High topical similarity (0.94), model correctly predicts CONTRADICTION
        valid_out = NLIOutput(
            prediction=NLILabel.CONTRADICTION,
            probabilities={"ENTAILMENT": 0.05, "CONTRADICTION": 0.90, "NEUTRAL": 0.05},
            uncertainty_score=0.10,
            topical_similarity=0.94,
        )
        assert valid_out.verify_contradiction_invariant() is True

        # Case 2: High topical similarity (0.94), but contradiction probability is dominant (0.90)
        # while prediction was wrongfully overridden to ENTAILMENT
        invalid_out = NLIOutput(
            prediction=NLILabel.ENTAILMENT,
            probabilities={"ENTAILMENT": 0.05, "CONTRADICTION": 0.90, "NEUTRAL": 0.05},
            uncertainty_score=0.10,
            topical_similarity=0.94,
        )
        assert invalid_out.verify_contradiction_invariant() is False

    def test_serialization_round_trip(self) -> None:
        out = NLIOutput(
            prediction=NLILabel.NEUTRAL,
            probabilities={"ENTAILMENT": 0.25, "CONTRADICTION": 0.25, "NEUTRAL": 0.50},
            uncertainty_score=0.65,
            pair_id="PAIR-TEST-ROUNDTRIP",
            topical_similarity=0.45,
            context_span="Discourse unit 3",
            metadata={"source": "synthetic_benchmark"},
        )
        d = out.to_dict()
        restored = NLIOutput.from_dict(d)
        assert restored == out

        s = out.to_json()
        from_json = NLIOutput.from_json(s)
        assert from_json == out


class TestNLIBatchesAndProtocol:
    """Verifies batch containers and NLIEngineContract protocol."""

    def test_batch_containers(self) -> None:
        p1 = SentencePairInput(premise="Premise 1", hypothesis="Hypothesis 1")
        p2 = SentencePairInput(premise="Premise 2", hypothesis="Hypothesis 2")
        pair_batch = NLIPairBatch(items=[p1, p2])
        assert len(pair_batch) == 2

        raw_list = pair_batch.to_list()
        restored = NLIPairBatch.from_list(raw_list)
        assert len(restored) == 2
        assert restored.items[0] == p1

        out1 = NLIOutput(
            prediction=NLILabel.ENTAILMENT,
            probabilities={"ENTAILMENT": 0.8, "CONTRADICTION": 0.1, "NEUTRAL": 0.1},
            uncertainty_score=0.2,
        )
        out2 = NLIOutput(
            prediction=NLILabel.CONTRADICTION,
            probabilities={"ENTAILMENT": 0.1, "CONTRADICTION": 0.8, "NEUTRAL": 0.1},
            uncertainty_score=0.2,
        )
        out_batch = NLIOutputBatch(outputs=[out1, out2])
        assert len(out_batch) == 2
        restored_out = NLIOutputBatch.from_list(out_batch.to_list())
        assert len(restored_out) == 2

    def test_engine_contract_protocol_conformance(self) -> None:
        class DummyNLIEngine:
            def infer(self, pair: SentencePairInput) -> NLIOutput:
                return NLIOutput(
                    prediction=NLILabel.ENTAILMENT,
                    probabilities={"ENTAILMENT": 1.0, "CONTRADICTION": 0.0, "NEUTRAL": 0.0},
                    uncertainty_score=0.0,
                    pair_id=pair.pair_id,
                )

            def infer_batch(self, pairs: list[SentencePairInput]) -> list[NLIOutput]:
                return [self.infer(p) for p in pairs]

        engine = DummyNLIEngine()
        assert isinstance(engine, NLIEngineContract)
        pair = SentencePairInput(premise="A implies B.", hypothesis="B follows from A.")
        result = engine.infer(pair)
        assert result.prediction == NLILabel.ENTAILMENT
