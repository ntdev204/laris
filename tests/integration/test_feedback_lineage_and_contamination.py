"""Integration tests for feedback lineage, hard-negative mining, and contamination isolation.

Tests compliance with DOC-SPEC-MOD-001 (Boundary J), ADR-001, ADR-007, ADR-008, and Issue #104:
- Multi-step expert review revision chains with full parent-child lineage tracking
- Hard-negative perturbation across all 5 strategies with contrastive label validity
- Strict zero-contamination isolation preventing test set leakage across all 6 benchmark suites
- Document-level, checksum-level, and split-level contamination prevention
- Concurrent reviewer feedback ingestion and mining repository thread safety
"""

from __future__ import annotations

import concurrent.futures
from typing import List

import pytest

from laris.core.errors import (
    BenchmarkContaminationError,
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
    FrozenBenchmarkManifest,
    ScientificErrorCategory,
)


class TestFeedbackLineageChains:
    """Integration tests for multi-generation expert feedback chains and coordinate re-anchoring."""

    def test_multi_generation_feedback_lineage(self) -> None:
        """Verify tracking of multi-turn feedback revisions through parent lineage chains."""
        repo = FeedbackMiningRepository()

        # Turn 1: Initial claim extraction flagged for provenance gap
        coord_orig = EvidenceCoordinate(
            coordinate_id="COORD-GEN1#p1s1",
            document_id="DOC-ARXIV-2401.1001",
            document_sha256="1111111111111111111111111111111111111111111111111111111111111111",
            page_number=1,
            section_identifier="Abstract",
            paragraph_index=0,
            sentence_index=1,
            char_start=50,
            char_end=120,
            verbatim_snippet="Protein phosphorylation increased 3-fold.",
            extraction_confidence=0.82,
        )

        fb_turn1 = ExpertFeedbackRecord(
            feedback_id="FB-CHAIN-01",
            target_item_id="CLAIM-101",
            reviewer_id="REV-PRIMARY-01",
            decision=ReviewerDecision.FLAG_PROVENANCE_GAP,
            rationale="Snippet lacks explicit baseline reference for 3-fold comparison.",
            source=FeedbackSource.HUMAN_EXPERT,
            provenance_coordinate=coord_orig,
            context_metadata={"turn": 1},
        )
        repo.record_feedback(fb_turn1)

        # Turn 2: Secondary review revises claim with re-anchored coordinate in Results section
        coord_revised = EvidenceCoordinate(
            coordinate_id="COORD-GEN2#p4s3",
            document_id="DOC-ARXIV-2401.1001",
            document_sha256="1111111111111111111111111111111111111111111111111111111111111111",
            page_number=4,
            section_identifier="Results Section 3.2",
            paragraph_index=2,
            sentence_index=2,
            char_start=340,
            char_end=450,
            verbatim_snippet=(
                "Relative to DMSO vehicle control, phosphorylation increased 3.1-fold."
            ),
            extraction_confidence=0.98,
        )

        fb_turn2 = ExpertFeedbackRecord(
            feedback_id="FB-CHAIN-02",
            target_item_id="CLAIM-101",
            reviewer_id="REV-SENIOR-02",
            decision=ReviewerDecision.REVISE,
            rationale="Re-anchored to Table 2 data confirming vehicle control baseline.",
            source=FeedbackSource.HUMAN_EXPERT,
            provenance_coordinate=coord_revised,
            corrected_output={"baseline": "DMSO vehicle", "fold_change": 3.1},
            lineage_parent_ids=[fb_turn1.feedback_id],
            context_metadata={"turn": 2},
        )
        repo.record_feedback(fb_turn2)

        # Turn 3: Senior curator certifies revision
        fb_turn3 = ExpertFeedbackRecord(
            feedback_id="FB-CHAIN-03",
            target_item_id="CLAIM-101",
            reviewer_id="REV-CURATOR-CHIEF",
            decision=ReviewerDecision.APPROVE,
            rationale="Verified against Fig 3C western blot; certified for graph indexing.",
            source=FeedbackSource.HUMAN_EXPERT,
            provenance_coordinate=coord_revised,
            lineage_parent_ids=[fb_turn1.feedback_id, fb_turn2.feedback_id],
            context_metadata={"turn": 3, "certified": True},
        )
        repo.record_feedback(fb_turn3)

        # Verify lineage reconstruction
        chain = repo.list_feedback()
        assert len(chain) == 3

        record_map = {r.feedback_id: r for r in chain}
        assert record_map["FB-CHAIN-01"].lineage_parent_ids == []
        assert record_map["FB-CHAIN-02"].lineage_parent_ids == ["FB-CHAIN-01"]
        assert record_map["FB-CHAIN-03"].lineage_parent_ids == ["FB-CHAIN-01", "FB-CHAIN-02"]

        # Verify coordinate audit progression
        assert record_map["FB-CHAIN-01"].provenance_coordinate.page_number == 1
        assert record_map["FB-CHAIN-03"].provenance_coordinate.page_number == 4


class TestHardNegativePerturbationStrategies:
    """Integration tests for all 5 scientific hard-negative generation strategies."""

    @pytest.fixture
    def feedback_repo(self) -> FeedbackMiningRepository:
        """Provide repository pre-populated with master review feedback."""
        repo = FeedbackMiningRepository()
        fb = ExpertFeedbackRecord(
            feedback_id="FB-BASE-001",
            target_item_id="CLAIM-GEN-01",
            reviewer_id="REV-SCIENTIST-01",
            decision=ReviewerDecision.FLAG_CONTRADICTION,
            rationale="Initial hypothesis overstated experimental results.",
        )
        repo.record_feedback(fb)
        return repo

    def test_condition_inversion_strategy(
        self, feedback_repo: FeedbackMiningRepository
    ) -> None:
        """Verify CONDITION_INVERSION creates contrastive sample with opposite effect."""
        fb = feedback_repo.get_feedback("FB-BASE-001")
        hn = feedback_repo.mine_hard_negative(
            feedback=fb,
            strategy=HardNegativeStrategy.CONDITION_INVERSION,
            premise="Treatment with 50 nM Bortezomib induced apoptosis in 85% of MM cells.",
            hypothesis="Treatment with 50 nM Bortezomib promoted proliferation in MM cells.",
            perturbed_condition="Apoptosis induction inverted to proliferation stimulation.",
            expected_label="CONTRADICTION",
            difficulty_score=0.90,
        )
        assert hn.strategy == HardNegativeStrategy.CONDITION_INVERSION
        assert hn.expected_label == "CONTRADICTION"
        assert hn.hard_negative_category == ScientificErrorCategory.REASONING_FAILURE

    def test_entity_substitution_strategy(
        self, feedback_repo: FeedbackMiningRepository
    ) -> None:
        """Verify ENTITY_SUBSTITUTION swaps homologous or interacting entities."""
        fb = feedback_repo.get_feedback("FB-BASE-001")
        hn = feedback_repo.mine_hard_negative(
            feedback=fb,
            strategy=HardNegativeStrategy.ENTITY_SUBSTITUTION,
            premise="BRCA1 mutations increase lifetime risk of early-onset ovarian cancer.",
            hypothesis="CDK4 mutations increase lifetime risk of early-onset ovarian cancer.",
            perturbed_condition="Replaced DNA repair BRCA1 with cell cycle regulator CDK4.",
            expected_label="NEUTRAL",
            difficulty_score=0.88,
        )
        assert hn.strategy == HardNegativeStrategy.ENTITY_SUBSTITUTION
        assert hn.expected_label == "NEUTRAL"

    def test_numerical_perturbation_strategy(
        self, feedback_repo: FeedbackMiningRepository
    ) -> None:
        """Verify NUMERICAL_PERTURBATION alters quantitative thresholds and magnitudes."""
        fb = feedback_repo.get_feedback("FB-BASE-001")
        hn = feedback_repo.mine_hard_negative(
            feedback=fb,
            strategy=HardNegativeStrategy.NUMERICAL_PERTURBATION,
            premise="The compound demonstrated an IC50 of 4.5 nM against target kinase.",
            hypothesis="The compound demonstrated an IC50 of 450 nM against target kinase.",
            perturbed_condition="Shifted potency by 2 orders of magnitude (4.5 nM -> 450 nM).",
            expected_label="CONTRADICTION",
            difficulty_score=0.95,
        )
        assert hn.strategy == HardNegativeStrategy.NUMERICAL_PERTURBATION
        assert hn.difficulty_score == 0.95

    def test_causal_direction_reversal_strategy(
        self, feedback_repo: FeedbackMiningRepository
    ) -> None:
        """Verify CAUSAL_DIRECTION_REVERSAL flips upstream/downstream causal pathways."""
        fb = feedback_repo.get_feedback("FB-BASE-001")
        hn = feedback_repo.mine_hard_negative(
            feedback=fb,
            strategy=HardNegativeStrategy.CAUSAL_DIRECTION_REVERSAL,
            premise="Elevated p53 expression triggers transcription of p21.",
            hypothesis="Elevated p21 expression triggers transcription of p53.",
            perturbed_condition="Swapped upstream transcription factor with downstream target.",
            expected_label="CONTRADICTION",
            difficulty_score=0.91,
        )
        assert hn.strategy == HardNegativeStrategy.CAUSAL_DIRECTION_REVERSAL
        assert hn.expected_label == "CONTRADICTION"

    def test_provenance_corruption_strategy(
        self, feedback_repo: FeedbackMiningRepository
    ) -> None:
        """Verify PROVENANCE_CORRUPTION perturbs coordinate grounding and document attribution."""
        fb = feedback_repo.get_feedback("FB-BASE-001")
        hn = feedback_repo.mine_hard_negative(
            feedback=fb,
            strategy=HardNegativeStrategy.PROVENANCE_CORRUPTION,
            premise="Study findings originated from cohort of 500 breast cancer patients.",
            hypothesis="Study findings originated from cohort of 500 prostate cancer patients.",
            perturbed_condition="Fabricated clinical cohort tissue site.",
            expected_label="CONTRADICTION",
            difficulty_score=0.87,
        )
        assert hn.strategy == HardNegativeStrategy.PROVENANCE_CORRUPTION
        assert hn.expected_label == "CONTRADICTION"


class TestEvaluationSplitIsolationAndContaminationGuards:
    """Integration tests for Boundary J zero-contamination isolation against frozen suites."""

    @pytest.fixture
    def frozen_suites(self) -> List[FrozenBenchmarkManifest]:
        """Generate and freeze benchmark manifests across all 6 standardized domains."""
        runner = BenchmarkRunner()
        manifests: List[FrozenBenchmarkManifest] = []
        for suite_type in BenchmarkSuiteType:
            m = runner.create_synthetic_manifest(
                manifest_id=f"MANIFEST-FROZEN-{suite_type.value}",
                suite_type=suite_type,
                version="1.0.0",
                num_items=4,
            )
            manifests.append(m)
        return manifests

    def test_zero_contamination_clean_pool_passes_all_suites(
        self, frozen_suites: List[FrozenBenchmarkManifest]
    ) -> None:
        """Verify disjoint mined training pool passes contamination audit across all 6 suites."""
        repo = FeedbackMiningRepository()
        fb = ExpertFeedbackRecord(
            feedback_id="FB-CLEAN-AUDIT",
            target_item_id="DOC-TRAIN-001",
            reviewer_id="REV-AUDITOR",
            decision=ReviewerDecision.FLAG_CONTRADICTION,
            rationale="Valid training negative mined from non-evaluation corpus.",
        )

        samples: List[HardNegativeSample] = []
        for i in range(12):
            hn = repo.mine_hard_negative(
                feedback=fb,
                strategy=HardNegativeStrategy.CONDITION_INVERSION,
                premise=f"Training domain assertion {i} under condition A.",
                hypothesis=f"Training domain assertion {i} under condition B.",
                perturbed_condition=f"Perturbation {i}",
            )
            samples.append(hn)

        # Audit against all 6 manifests simultaneously
        repo.assert_zero_contamination(samples, frozen_suites)

        # Verify export produces clean training partition
        exported = repo.export_training_split(frozen_manifests=frozen_suites)
        assert len(exported) == 12
        assert all(item["partition"] == "train" for item in exported)
        assert all(item["is_training_eligible"] is True for item in exported)

    def test_contamination_detection_item_id_collision(
        self, frozen_suites: List[FrozenBenchmarkManifest]
    ) -> None:
        """Verify collision between training sample ID and frozen manifest item raises error."""
        repo = FeedbackMiningRepository()
        frozen_item = frozen_suites[2].items[1]  # Extraction suite, item 1

        colliding_sample = HardNegativeSample(
            sample_id=frozen_item.item_id,  # Direct ID collision
            source_feedback_id="FB-COLLIDE",
            hard_negative_category=ScientificErrorCategory.EXTRACTION_FAILURE,
            strategy=HardNegativeStrategy.ENTITY_SUBSTITUTION,
            premise="Different text.",
            hypothesis="Different hypothesis.",
            perturbed_condition="Entity swap.",
        )

        with pytest.raises(BenchmarkContaminationError, match="matches an item in frozen"):
            repo.assert_zero_contamination([colliding_sample], frozen_suites)

        with pytest.raises(BenchmarkContaminationError, match="matches an item in frozen"):
            repo.export_training_split(
                samples=[colliding_sample], frozen_manifests=frozen_suites
            )

    def test_contamination_detection_checksum_collision(
        self, frozen_suites: List[FrozenBenchmarkManifest]
    ) -> None:
        """Verify identical content hash collision raises contamination error."""
        repo = FeedbackMiningRepository()
        frozen_item = frozen_suites[0].items[0]

        # Construct candidate with distinct ID but force matching checksum
        colliding_hash_sample = HardNegativeSample(
            sample_id="HN-UNIQUE-ID-COLLIDING-HASH",
            source_feedback_id="FB-COLLIDE-HASH",
            hard_negative_category=ScientificErrorCategory.REASONING_FAILURE,
            strategy=HardNegativeStrategy.CONDITION_INVERSION,
            premise="Premise.",
            hypothesis="Hypothesis.",
            perturbed_condition="Perturbation.",
        )
        object.__setattr__(
            colliding_hash_sample, "checksum_sha256", frozen_item.checksum_sha256
        )

        with pytest.raises(BenchmarkContaminationError, match="checksum matches an item"):
            repo.assert_zero_contamination([colliding_hash_sample], frozen_suites)

    def test_contamination_detection_split_assignment_violation(
        self, frozen_suites: List[FrozenBenchmarkManifest]
    ) -> None:
        """Verify training sample mistakenly tagged with evaluation split is caught."""
        repo = FeedbackMiningRepository()
        sample = HardNegativeSample(
            sample_id="HN-SPLIT-VIOLATION",
            source_feedback_id="FB-SPLIT",
            hard_negative_category=ScientificErrorCategory.REASONING_FAILURE,
            strategy=HardNegativeStrategy.CONDITION_INVERSION,
            premise="Premise text.",
            hypothesis="Hypothesis text.",
            perturbed_condition="Perturbation.",
        )
        object.__setattr__(sample, "split_assignment", "test")

        with pytest.raises(BenchmarkContaminationError, match="assigned to evaluation split"):
            repo.assert_zero_contamination([sample], frozen_suites)


class TestConcurrentFeedbackMiningOperations:
    """Integration tests for concurrent multi-threaded ingestion and repository safety."""

    def test_concurrent_feedback_and_mining(self) -> None:
        """Verify thread-safe concurrent recording of reviews and negative mining."""
        repo = FeedbackMiningRepository()

        def worker_task(worker_id: int) -> int:
            fb = ExpertFeedbackRecord(
                feedback_id=f"FB-CONCURRENT-{worker_id:03d}",
                target_item_id=f"ITEM-{worker_id:03d}",
                reviewer_id=f"REV-{worker_id:02d}",
                decision=ReviewerDecision.FLAG_CONTRADICTION,
                rationale=f"Concurrent worker {worker_id} finding audit.",
            )
            repo.record_feedback(fb)

            # Mine two negatives per worker
            _ = repo.mine_hard_negative(
                feedback=fb,
                strategy=HardNegativeStrategy.CONDITION_INVERSION,
                premise=f"Premise from worker {worker_id}.",
                hypothesis=f"Inverted hypothesis from worker {worker_id}.",
                perturbed_condition=f"Inversion {worker_id}",
            )
            _ = repo.mine_hard_negative(
                feedback=fb,
                strategy=HardNegativeStrategy.NUMERICAL_PERTURBATION,
                premise=f"Quantitative measurement {worker_id} mM.",
                hypothesis=f"Perturbed measurement {worker_id * 10} mM.",
                perturbed_condition=f"Scalar perturbation {worker_id}",
            )
            return worker_id

        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            futures = [executor.submit(worker_task, i) for i in range(15)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        assert len(results) == 15
        assert len(repo.list_feedback()) == 15
        # 15 workers * 2 negatives each = 30 mined samples
        assert len(repo.list_hard_negatives()) == 30
