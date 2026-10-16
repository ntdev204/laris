"""Unit tests for Layer 10 expert feedback capture, negative mining, and contamination guards.

Tests compliance with DOC-SPEC-MOD-001 (Boundary J), ADR-001, ADR-007, ADR-008, and Issue #72:
- Expert review feedback schemas, provenance lineage, and validation contracts
- Hard-negative sample perturbation strategies and deterministic SHA-256 identities
- Training split isolation and strict contamination prevention against frozen benchmark manifests
- Thread-safe repository operations and training dataset export
"""

from __future__ import annotations

import pytest

from laris.core.errors import (
    BenchmarkContaminationError,
    ModuleContractViolationError,
)
from laris.core.schemas import EvidenceCoordinate
from laris.layers.layer10_evaluation.benchmark_runner import BenchmarkRunner
from laris.layers.layer10_evaluation.feedback_mining import (
    ExpertFeedbackRecord,
    FeedbackMiningRepository,
    FeedbackSource,
    HardNegativeSample,
    HardNegativeStrategy,
    ReviewerDecision,
)
from laris.layers.layer10_evaluation.schemas import (
    BenchmarkSuiteType,
    ScientificErrorCategory,
)


class TestExpertFeedbackRecord:
    """Unit tests for ExpertFeedbackRecord data contracts and serialization."""

    @pytest.fixture
    def sample_coordinate(self) -> EvidenceCoordinate:
        """Provide a valid EvidenceCoordinate fixture."""
        return EvidenceCoordinate(
            coordinate_id="COORD-TEST#p1s1",
            document_id="DOC-TEST-001",
            document_sha256="1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
            page_number=1,
            section_identifier="Section 1",
            paragraph_index=0,
            sentence_index=0,
            char_start=0,
            char_end=50,
            verbatim_snippet="Test finding excerpt.",
            extraction_confidence=0.99,
        )

    def test_feedback_record_instantiation_and_auto_timestamp(
        self, sample_coordinate: EvidenceCoordinate
    ) -> None:
        """Verify successful instantiation and automatic ISO timestamp generation."""
        record = ExpertFeedbackRecord(
            feedback_id="FB-001",
            target_item_id="ITEM-100",
            reviewer_id="REV-EXPERT-42",
            decision=ReviewerDecision.FLAG_CONTRADICTION,
            rationale="Finding contradicts earlier trial under 10mg dosage.",
            provenance_coordinate=sample_coordinate,
            corrected_output={"label": "CONTRADICTION"},
            lineage_parent_ids=["FB-000"],
        )
        assert record.feedback_id == "FB-001"
        assert record.source == FeedbackSource.HUMAN_EXPERT
        assert record.decision == ReviewerDecision.FLAG_CONTRADICTION
        assert record.timestamp_iso != ""
        assert record.provenance_coordinate == sample_coordinate

    @pytest.mark.parametrize(
        ("kwargs", "match_err"),
        [
            (
                {
                    "feedback_id": "",
                    "target_item_id": "ITEM-1",
                    "reviewer_id": "REV-1",
                    "decision": ReviewerDecision.APPROVE,
                    "rationale": "OK",
                },
                "feedback_id cannot be empty",
            ),
            (
                {
                    "feedback_id": "FB-1",
                    "target_item_id": "",
                    "reviewer_id": "REV-1",
                    "decision": ReviewerDecision.APPROVE,
                    "rationale": "OK",
                },
                "target_item_id cannot be empty",
            ),
            (
                {
                    "feedback_id": "FB-1",
                    "target_item_id": "ITEM-1",
                    "reviewer_id": "",
                    "decision": ReviewerDecision.APPROVE,
                    "rationale": "OK",
                },
                "reviewer_id cannot be empty",
            ),
            (
                {
                    "feedback_id": "FB-1",
                    "target_item_id": "ITEM-1",
                    "reviewer_id": "REV-1",
                    "decision": ReviewerDecision.APPROVE,
                    "rationale": "",
                },
                "rationale cannot be empty",
            ),
        ],
    )
    def test_feedback_record_contract_violations(
        self, kwargs: dict[str, str], match_err: str
    ) -> None:
        """Verify contract exceptions on empty required feedback fields."""
        with pytest.raises(ModuleContractViolationError, match=match_err):
            ExpertFeedbackRecord(**kwargs)  # type: ignore[arg-type]

    def test_feedback_record_serialization_roundtrip(
        self, sample_coordinate: EvidenceCoordinate
    ) -> None:
        """Verify lossless serialization and reconstitution of feedback record."""
        record = ExpertFeedbackRecord(
            feedback_id="FB-ROUNDTRIP",
            target_item_id="ITEM-200",
            reviewer_id="REV-DR-SMITH",
            decision=ReviewerDecision.FLAG_OVERREACH,
            rationale="Unjustified causal claim regarding gene knockdown.",
            source=FeedbackSource.AUTOMATED_AUDITOR,
            provenance_coordinate=sample_coordinate,
            corrected_output={"claim_status": "HYPOTHESIS"},
            lineage_parent_ids=["FB-PREV"],
            context_metadata={"audit_score": 0.45},
        )
        data = record.to_dict()
        reconstituted = ExpertFeedbackRecord.from_dict(data)

        assert reconstituted.feedback_id == record.feedback_id
        assert reconstituted.decision == ReviewerDecision.FLAG_OVERREACH
        assert reconstituted.source == FeedbackSource.AUTOMATED_AUDITOR
        assert reconstituted.provenance_coordinate is not None
        assert reconstituted.provenance_coordinate.coordinate_id == "COORD-TEST#p1s1"
        assert reconstituted.context_metadata["audit_score"] == 0.45

    def test_feedback_record_serialization_without_coordinate(self) -> None:
        """Verify serialization handles optional coordinate being None."""
        record = ExpertFeedbackRecord(
            feedback_id="FB-NO-COORD",
            target_item_id="ITEM-300",
            reviewer_id="REV-USER",
            decision=ReviewerDecision.APPROVE,
            rationale="Claim accurately reflects abstract.",
        )
        data = record.to_dict()
        assert data["provenance_coordinate"] is None
        reconstituted = ExpertFeedbackRecord.from_dict(data)
        assert reconstituted.provenance_coordinate is None


class TestHardNegativeSample:
    """Unit tests for HardNegativeSample contracts, contamination isolation, and hashes."""

    def test_hard_negative_sample_valid_creation(self) -> None:
        """Verify valid hard negative sample creation and automatic deterministic checksum."""
        sample = HardNegativeSample(
            sample_id="HN-001",
            source_feedback_id="FB-001",
            hard_negative_category=ScientificErrorCategory.REASONING_FAILURE,
            strategy=HardNegativeStrategy.CONDITION_INVERSION,
            premise="Compound A inhibits kinase activity at 10 uM in vitro.",
            hypothesis="Compound A increases kinase activity at 10 uM in vitro.",
            perturbed_condition="Activity direction inverted (inhibition -> activation)",
            expected_label="CONTRADICTION",
            difficulty_score=0.92,
        )
        assert sample.sample_id == "HN-001"
        assert sample.is_training_eligible is True
        assert sample.split_assignment == "train"
        assert len(sample.checksum_sha256) == 64

    @pytest.mark.parametrize(
        ("field_name", "bad_val", "expected_err"),
        [
            ("sample_id", "", "sample_id cannot be empty"),
            ("source_feedback_id", "", "source_feedback_id cannot be empty"),
            ("premise", "", "premise cannot be empty"),
            ("hypothesis", "", "hypothesis cannot be empty"),
            ("perturbed_condition", "", "perturbed_condition cannot be empty"),
        ],
    )
    def test_hard_negative_empty_field_validations(
        self, field_name: str, bad_val: str, expected_err: str
    ) -> None:
        """Verify contract violations on empty required sample fields."""
        valid_kwargs = {
            "sample_id": "HN-VALID",
            "source_feedback_id": "FB-VALID",
            "hard_negative_category": ScientificErrorCategory.REASONING_FAILURE,
            "strategy": HardNegativeStrategy.CONDITION_INVERSION,
            "premise": "Premise text.",
            "hypothesis": "Hypothesis text.",
            "perturbed_condition": "Inversion condition.",
        }
        valid_kwargs[field_name] = bad_val
        with pytest.raises(ModuleContractViolationError, match=expected_err):
            HardNegativeSample(**valid_kwargs)  # type: ignore[arg-type]

    def test_hard_negative_difficulty_score_bounds(self) -> None:
        """Verify difficulty score must be within [0.0, 1.0]."""
        valid_kwargs = {
            "sample_id": "HN-DIFF",
            "source_feedback_id": "FB-01",
            "hard_negative_category": ScientificErrorCategory.REASONING_FAILURE,
            "strategy": HardNegativeStrategy.CONDITION_INVERSION,
            "premise": "Premise text.",
            "hypothesis": "Hypothesis text.",
            "perturbed_condition": "Perturbed.",
        }
        with pytest.raises(ModuleContractViolationError, match="difficulty_score"):
            HardNegativeSample(**valid_kwargs, difficulty_score=1.5)  # type: ignore[arg-type]

        with pytest.raises(ModuleContractViolationError, match="difficulty_score"):
            HardNegativeSample(**valid_kwargs, difficulty_score=-0.1)  # type: ignore[arg-type]

    def test_hard_negative_contamination_split_assignment_rejection(self) -> None:
        """Verify training-eligible sample cannot be assigned to test or val evaluation splits."""
        with pytest.raises(BenchmarkContaminationError, match="Cross-split leakage prohibited"):
            HardNegativeSample(
                sample_id="HN-LEAK-TEST",
                source_feedback_id="FB-01",
                hard_negative_category=ScientificErrorCategory.REASONING_FAILURE,
                strategy=HardNegativeStrategy.CONDITION_INVERSION,
                premise="Premise.",
                hypothesis="Hypothesis.",
                perturbed_condition="Perturbed.",
                is_training_eligible=True,
                split_assignment="test",
            )

        with pytest.raises(BenchmarkContaminationError, match="Cross-split leakage prohibited"):
            HardNegativeSample(
                sample_id="HN-LEAK-VAL",
                source_feedback_id="FB-01",
                hard_negative_category=ScientificErrorCategory.REASONING_FAILURE,
                strategy=HardNegativeStrategy.CONDITION_INVERSION,
                premise="Premise.",
                hypothesis="Hypothesis.",
                perturbed_condition="Perturbed.",
                is_training_eligible=True,
                split_assignment="val",
            )

    def test_hard_negative_checksum_mismatch(self) -> None:
        """Verify tampering with checksum raises contract violation."""
        with pytest.raises(ModuleContractViolationError, match="checksum mismatch"):
            HardNegativeSample(
                sample_id="HN-BAD-HASH",
                source_feedback_id="FB-01",
                hard_negative_category=ScientificErrorCategory.REASONING_FAILURE,
                strategy=HardNegativeStrategy.CONDITION_INVERSION,
                premise="Premise.",
                hypothesis="Hypothesis.",
                perturbed_condition="Perturbed.",
                checksum_sha256="0000000000000000000000000000000000000000000000000000000000000000",
            )

    def test_hard_negative_serialization_roundtrip(self) -> None:
        """Verify dictionary serialization round-trip for hard negative sample."""
        coord = EvidenceCoordinate(
            coordinate_id="COORD-HN#p2",
            document_id="DOC-ARXIV-01",
            document_sha256="abcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcd",
            page_number=2,
            section_identifier="Methods",
            paragraph_index=1,
            sentence_index=0,
            char_start=10,
            char_end=40,
            verbatim_snippet="Snippet.",
        )
        sample = HardNegativeSample(
            sample_id="HN-ROUNDTRIP",
            source_feedback_id="FB-100",
            hard_negative_category=ScientificErrorCategory.EPISTEMIC_FAILURE,
            strategy=HardNegativeStrategy.CAUSAL_DIRECTION_REVERSAL,
            premise="Gene X promotes tumor progression.",
            hypothesis="Tumor progression activates Gene X.",
            perturbed_condition="Causal direction flipped.",
            expected_label="NEUTRAL",
            difficulty_score=0.88,
            provenance_coordinate=coord,
        )
        data = sample.to_dict()
        reconstituted = HardNegativeSample.from_dict(data)

        assert reconstituted.sample_id == sample.sample_id
        assert reconstituted.strategy == HardNegativeStrategy.CAUSAL_DIRECTION_REVERSAL
        assert reconstituted.hard_negative_category == ScientificErrorCategory.EPISTEMIC_FAILURE
        assert reconstituted.checksum_sha256 == sample.checksum_sha256
        assert reconstituted.provenance_coordinate is not None
        assert reconstituted.provenance_coordinate.coordinate_id == "COORD-HN#p2"


class TestFeedbackMiningRepository:
    """Unit tests for feedback repository storage, mining operations, and contamination checks."""

    @pytest.fixture
    def repository(self) -> FeedbackMiningRepository:
        """Provide an empty FeedbackMiningRepository."""
        return FeedbackMiningRepository()

    def test_record_and_retrieve_feedback(self, repository: FeedbackMiningRepository) -> None:
        """Verify recording and querying feedback records."""
        fb = ExpertFeedbackRecord(
            feedback_id="FB-STORE-01",
            target_item_id="ITEM-10",
            reviewer_id="REV-1",
            decision=ReviewerDecision.APPROVE,
            rationale="Approved without edits.",
        )
        repository.record_feedback(fb)
        assert len(repository.list_feedback()) == 1
        fetched = repository.get_feedback("FB-STORE-01")
        assert fetched.feedback_id == "FB-STORE-01"

        with pytest.raises(ModuleContractViolationError, match="not found"):
            repository.get_feedback("NON-EXISTENT")

    def test_mine_hard_negative_derives_categories_and_registers(
        self, repository: FeedbackMiningRepository
    ) -> None:
        """Verify category derivation based on reviewer decision across strategies."""
        # Contradiction flag -> REASONING_FAILURE
        fb1 = ExpertFeedbackRecord(
            feedback_id="FB-MINE-01",
            target_item_id="ITEM-01",
            reviewer_id="REV-1",
            decision=ReviewerDecision.FLAG_CONTRADICTION,
            rationale="Findings conflict with control group.",
        )
        hn1 = repository.mine_hard_negative(
            feedback=fb1,
            strategy=HardNegativeStrategy.CONDITION_INVERSION,
            premise="Control showed 10% response.",
            hypothesis="Control showed 90% response.",
            perturbed_condition="Control response inverted.",
        )
        assert hn1.hard_negative_category == ScientificErrorCategory.REASONING_FAILURE
        assert len(repository.list_hard_negatives()) == 1

        # Overreach flag -> EPISTEMIC_FAILURE
        fb2 = ExpertFeedbackRecord(
            feedback_id="FB-MINE-02",
            target_item_id="ITEM-02",
            reviewer_id="REV-2",
            decision=ReviewerDecision.FLAG_OVERREACH,
            rationale="Correlation reported as causal.",
        )
        hn2 = repository.mine_hard_negative(
            feedback=fb2,
            strategy=HardNegativeStrategy.CAUSAL_DIRECTION_REVERSAL,
            premise="Biomarker correlates with symptom severity.",
            hypothesis="Biomarker causes symptom severity.",
            perturbed_condition="Correlation promoted to causation.",
        )
        assert hn2.hard_negative_category == ScientificErrorCategory.EPISTEMIC_FAILURE

        # Provenance gap flag -> PROVENANCE_FAILURE
        fb3 = ExpertFeedbackRecord(
            feedback_id="FB-MINE-03",
            target_item_id="ITEM-03",
            reviewer_id="REV-3",
            decision=ReviewerDecision.FLAG_PROVENANCE_GAP,
            rationale="Snippet not found on cited page.",
        )
        hn3 = repository.mine_hard_negative(
            feedback=fb3,
            strategy=HardNegativeStrategy.PROVENANCE_CORRUPTION,
            premise="Finding cited from page 12.",
            hypothesis="Finding cited from page 99.",
            perturbed_condition="Corrupted page citation.",
        )
        assert hn3.hard_negative_category == ScientificErrorCategory.PROVENANCE_FAILURE

        # Default fallback flag -> EXTRACTION_FAILURE
        fb4 = ExpertFeedbackRecord(
            feedback_id="FB-MINE-04",
            target_item_id="ITEM-04",
            reviewer_id="REV-4",
            decision=ReviewerDecision.REVISE,
            rationale="Typo in extracted entity name.",
        )
        hn4 = repository.mine_hard_negative(
            feedback=fb4,
            strategy=HardNegativeStrategy.ENTITY_SUBSTITUTION,
            premise="Protein EGFR was measured.",
            hypothesis="Protein KRAS was measured.",
            perturbed_condition="Substituted entity.",
        )
        assert hn4.hard_negative_category == ScientificErrorCategory.EXTRACTION_FAILURE

        # Explicit category override
        hn5 = repository.mine_hard_negative(
            feedback=fb4,
            strategy=HardNegativeStrategy.NUMERICAL_PERTURBATION,
            premise="Measurement was 5.2 mM.",
            hypothesis="Measurement was 52.0 mM.",
            perturbed_condition="Shifted decimal point.",
            category=ScientificErrorCategory.SYSTEM_FAILURE,
        )
        assert hn5.hard_negative_category == ScientificErrorCategory.SYSTEM_FAILURE

    def test_record_and_get_hard_negative(self, repository: FeedbackMiningRepository) -> None:
        """Verify recording and querying hard negative samples directly."""
        sample = HardNegativeSample(
            sample_id="HN-DIRECT",
            source_feedback_id="FB-DIRECT",
            hard_negative_category=ScientificErrorCategory.REASONING_FAILURE,
            strategy=HardNegativeStrategy.CONDITION_INVERSION,
            premise="Premise.",
            hypothesis="Hypothesis.",
            perturbed_condition="Perturbed.",
        )
        repository.record_hard_negative(sample)
        assert repository.get_hard_negative("HN-DIRECT").sample_id == "HN-DIRECT"

        with pytest.raises(ModuleContractViolationError, match="not found"):
            repository.get_hard_negative("NON-EXISTENT-HN")

    def test_zero_contamination_guard_detects_overlaps(
        self, repository: FeedbackMiningRepository
    ) -> None:
        """Verify assert_zero_contamination detects ID, checksum, and split violations."""
        runner = BenchmarkRunner()
        manifest = runner.create_synthetic_manifest(
            "SUITE-FROZEN-TEST",
            BenchmarkSuiteType.NLI_CONTRADICTION,
            num_items=3,
        )
        frozen_item = manifest.items[0]

        # 1. Clean sample: passes contamination check
        clean_sample = HardNegativeSample(
            sample_id="HN-CLEAN-01",
            source_feedback_id="FB-01",
            hard_negative_category=ScientificErrorCategory.REASONING_FAILURE,
            strategy=HardNegativeStrategy.CONDITION_INVERSION,
            premise="Independent training premise.",
            hypothesis="Independent training hypothesis.",
            perturbed_condition="Unique perturbation.",
        )
        repository.assert_zero_contamination([clean_sample], [manifest])

        # 2. Overlapping sample ID: fails contamination check
        colliding_id_sample = HardNegativeSample(
            sample_id=frozen_item.item_id,  # Colliding ID with frozen eval set!
            source_feedback_id="FB-01",
            hard_negative_category=ScientificErrorCategory.REASONING_FAILURE,
            strategy=HardNegativeStrategy.CONDITION_INVERSION,
            premise="Different text.",
            hypothesis="Different hyp.",
            perturbed_condition="Perturbed.",
        )
        with pytest.raises(BenchmarkContaminationError, match="matches an item in frozen"):
            repository.assert_zero_contamination([colliding_id_sample], [manifest])

        # 3. Overlapping checksum: fails contamination check
        object.__setattr__(clean_sample, "checksum_sha256", frozen_item.checksum_sha256)
        with pytest.raises(BenchmarkContaminationError, match="checksum matches an item"):
            repository.assert_zero_contamination([clean_sample], [manifest])

        # 4. Evaluation split assignment: fails contamination check
        object.__setattr__(clean_sample, "checksum_sha256", "clean_hash_value")
        object.__setattr__(clean_sample, "split_assignment", "val")
        with pytest.raises(BenchmarkContaminationError, match="is assigned to evaluation split"):
            repository.assert_zero_contamination([clean_sample], [manifest])

    def test_export_training_split_with_contamination_check(
        self, repository: FeedbackMiningRepository
    ) -> None:
        """Verify export_training_split attaches partition metadata and filters ineligible."""
        fb = ExpertFeedbackRecord(
            feedback_id="FB-EXP",
            target_item_id="ITEM-1",
            reviewer_id="REV-1",
            decision=ReviewerDecision.FLAG_CONTRADICTION,
            rationale="Rationale.",
        )
        hn_eligible = repository.mine_hard_negative(
            feedback=fb,
            strategy=HardNegativeStrategy.CONDITION_INVERSION,
            premise="P1",
            hypothesis="H1",
            perturbed_condition="C1",
        )
        hn_ineligible = HardNegativeSample(
            sample_id="HN-INELIGIBLE",
            source_feedback_id="FB-EXP",
            hard_negative_category=ScientificErrorCategory.REASONING_FAILURE,
            strategy=HardNegativeStrategy.CONDITION_INVERSION,
            premise="P2",
            hypothesis="H2",
            perturbed_condition="C2",
            is_training_eligible=False,
        )
        repository.record_hard_negative(hn_ineligible)

        runner = BenchmarkRunner()
        manifest = runner.create_synthetic_manifest(
            "SUITE-MANIFEST-CLEAN",
            BenchmarkSuiteType.NLI_CONTRADICTION,
            num_items=2,
        )

        exported = repository.export_training_split(frozen_manifests=[manifest])
        assert len(exported) == 1
        assert exported[0]["sample_id"] == hn_eligible.sample_id
        assert exported[0]["partition"] == "train"
