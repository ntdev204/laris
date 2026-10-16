"""Unit tests for discourse entity schemas and extraction boundary contracts.

Task ID: M4-SCINLP-001-SUB-01 (Issue #56)
Milestone: M4 (Scientific NLP & Discourse Intelligence)
Boundary D: MOD-SCINLP-001 (Scientific Language Intelligence)
"""

import pytest

from laris.core.errors import (
    ExtractionConfidenceBelowThresholdError,
    MalformedDiscourseSpanError,
    ModuleContractViolationError,
)
from laris.core.schemas import EpistemicStatus, EvidenceCoordinate
from laris.scientific import (
    AssumptionRecord,
    ClaimRecord,
    DatasetRecord,
    DiscourseEntityType,
    DiscourseExtractionSet,
    DiscourseExtractorContract,
    FormulaRecord,
    LimitationRecord,
    MethodRecord,
    MetricRecord,
    ResultRecord,
)
from laris.scientific.schemas import _validate_coordinate_span


@pytest.fixture
def sample_coordinate() -> EvidenceCoordinate:
    return EvidenceCoordinate(
        coordinate_id="COORD-001",
        document_id="DOC-STEM-001",
        document_sha256="a" * 64,
        page_number=1,
        section_identifier="sec_results",
        paragraph_index=2,
        sentence_index=1,
        char_start=100,
        char_end=175,
        verbatim_snippet="Target kinase phosphorylation was enhanced after administration.",
        extraction_confidence=0.98,
    )



class TestDiscourseEntityRecords:
    """Verifies typed discourse entity records with coordinate and confidence contracts."""

    def test_claim_record_creation_and_serialization(
        self, sample_coordinate: EvidenceCoordinate
    ) -> None:
        claim = ClaimRecord(
            claim_id="CLM-001",
            text="Target kinase phosphorylation was enhanced after molecule administration.",
            epistemic_status=EpistemicStatus.EMPIRICALLY_SUPPORTED_FINDING,
            confidence=0.95,
            coordinate=sample_coordinate,
            related_methods=("MET-001",),
            measured_metrics=("MTR-001",),
            is_hedged=False,
        )
        assert claim.claim_id == "CLM-001"
        assert claim.confidence == 0.95
        assert claim.epistemic_status == EpistemicStatus.EMPIRICALLY_SUPPORTED_FINDING

        d = claim.to_dict()
        reconstructed = ClaimRecord.from_dict(d)
        assert reconstructed == claim

    def test_method_record_creation_and_serialization(
        self, sample_coordinate: EvidenceCoordinate
    ) -> None:
        method = MethodRecord(
            method_id="MET-001",
            name="Flow Cytometry with Annexin V",
            category="experimental",
            confidence=0.92,
            coordinate=sample_coordinate,
            parameters={"voltage": "450V", "fluorophore": "FITC"},
            tools_software=("FlowJo v10",),
        )
        assert method.category == "experimental"
        assert method.parameters["voltage"] == "450V"

        d = method.to_dict()
        reconstructed = MethodRecord.from_dict(d)
        assert reconstructed == method

    def test_dataset_record_creation_and_serialization(
        self, sample_coordinate: EvidenceCoordinate
    ) -> None:
        dataset = DatasetRecord(
            dataset_id="DS-001",
            name="C. elegans Longevity Assay Callset",
            confidence=0.88,
            coordinate=sample_coordinate,
            sample_size=1200,
            organism_or_domain="Caenorhabditis elegans",
            accession_id="GSE12345",
        )
        assert dataset.sample_size == 1200
        assert dataset.accession_id == "GSE12345"

        d = dataset.to_dict()
        reconstructed = DatasetRecord.from_dict(d)
        assert reconstructed == dataset

    def test_metric_record_creation_and_serialization(
        self, sample_coordinate: EvidenceCoordinate
    ) -> None:
        metric = MetricRecord(
            metric_id="MTR-001",
            name="IC50 Binding Affinity",
            confidence=0.91,
            coordinate=sample_coordinate,
            value=14.2,
            unit="nM",
            comparison_operator="<=",
        )
        assert metric.value == 14.2
        assert metric.unit == "nM"

        d = metric.to_dict()
        reconstructed = MetricRecord.from_dict(d)
        assert reconstructed == metric

    def test_result_record_creation_and_serialization(
        self, sample_coordinate: EvidenceCoordinate
    ) -> None:
        result = ResultRecord(
            result_id="RES-001",
            description="Cellular proliferation rate was reduced by 40 percent.",
            confidence=0.89,
            coordinate=sample_coordinate,
            statistically_significant=True,
            p_value=0.003,
            effect_size=0.74,
            supporting_metric_ids=("MTR-001",),
        )
        assert result.statistically_significant is True
        assert result.p_value == 0.003

        d = result.to_dict()
        reconstructed = ResultRecord.from_dict(d)
        assert reconstructed == result

    def test_limitation_record_creation_and_serialization(
        self, sample_coordinate: EvidenceCoordinate
    ) -> None:
        limitation = LimitationRecord(
            limitation_id="LIM-001",
            description="Small animal cohort size restricts generalizability to humans.",
            confidence=0.85,
            coordinate=sample_coordinate,
            scope="sample_size",
            is_author_disclosed=True,
        )
        assert limitation.scope == "sample_size"
        assert limitation.is_author_disclosed is True

        d = limitation.to_dict()
        reconstructed = LimitationRecord.from_dict(d)
        assert reconstructed == limitation

    def test_assumption_record_creation_and_serialization(
        self, sample_coordinate: EvidenceCoordinate
    ) -> None:
        assumption = AssumptionRecord(
            assumption_id="ASM-001",
            statement="Reaction kinetics follow pseudo-first-order behavior.",
            confidence=0.87,
            coordinate=sample_coordinate,
            is_explicit=True,
        )
        assert assumption.is_explicit is True

        d = assumption.to_dict()
        reconstructed = AssumptionRecord.from_dict(d)
        assert reconstructed == assumption

    def test_formula_record_creation_and_serialization(
        self, sample_coordinate: EvidenceCoordinate
    ) -> None:
        formula = FormulaRecord(
            formula_id="FRM-001",
            latex_source=r"\Delta G = \Delta H - T \Delta S",
            confidence=0.96,
            coordinate=sample_coordinate,
            variables=("Delta G", "Delta H", "T", "Delta S"),
            is_inline=True,
        )
        assert formula.is_inline is True
        assert r"\Delta G" in formula.latex_source

        d = formula.to_dict()
        reconstructed = FormulaRecord.from_dict(d)
        assert reconstructed == formula


class TestDiscourseSpanValidation:
    """Verifies strict span boundary checking, coordinate anchoring, and malformed span errors."""

    def test_malformed_span_empty_text(self, sample_coordinate: EvidenceCoordinate) -> None:
        with pytest.raises(MalformedDiscourseSpanError, match="cannot be empty"):
            ClaimRecord(
                claim_id="CLM-001",
                text="",
                epistemic_status=EpistemicStatus.HYPOTHESIS,
                confidence=0.9,
                coordinate=sample_coordinate,
            )

    def test_malformed_span_whitespace_text(self, sample_coordinate: EvidenceCoordinate) -> None:
        with pytest.raises(MalformedDiscourseSpanError, match="cannot be empty"):
            MethodRecord(
                method_id="MET-001",
                name="   \t\n  ",
                category="experimental",
                confidence=0.9,
                coordinate=sample_coordinate,
            )

    def test_invalid_coordinate_type(self) -> None:
        with pytest.raises(ModuleContractViolationError, match="Expected EvidenceCoordinate"):
            _validate_coordinate_span("not-a-coord", "Some text", 0.9)  # type: ignore[arg-type]

    def test_invalid_confidence_range(self, sample_coordinate: EvidenceCoordinate) -> None:
        with pytest.raises(ModuleContractViolationError, match="Confidence score"):
            ClaimRecord(
                claim_id="CLM-001",
                text="Valid text",
                epistemic_status=EpistemicStatus.HYPOTHESIS,
                confidence=1.5,
                coordinate=sample_coordinate,
            )

        with pytest.raises(ModuleContractViolationError, match="Confidence score"):
            ClaimRecord(
                claim_id="CLM-001",
                text="Valid text",
                epistemic_status=EpistemicStatus.HYPOTHESIS,
                confidence=-0.1,
                coordinate=sample_coordinate,
            )

    def test_confidence_below_threshold(self, sample_coordinate: EvidenceCoordinate) -> None:
        with pytest.raises(
            ExtractionConfidenceBelowThresholdError, match="below minimum threshold"
        ):
            _validate_coordinate_span(sample_coordinate, "Valid text", 0.3, min_confidence=0.5)

    def test_dataset_negative_sample_size(self, sample_coordinate: EvidenceCoordinate) -> None:
        with pytest.raises(ModuleContractViolationError, match="sample_size must be non-negative"):
            DatasetRecord(
                dataset_id="DS-001",
                name="Valid dataset name",
                confidence=0.9,
                coordinate=sample_coordinate,
                sample_size=-10,
            )

    def test_result_invalid_p_value(self, sample_coordinate: EvidenceCoordinate) -> None:
        with pytest.raises(ModuleContractViolationError, match="p_value must be in range"):
            ResultRecord(
                result_id="RES-001",
                description="Valid result description",
                confidence=0.9,
                coordinate=sample_coordinate,
                p_value=1.5,
            )


class TestDiscourseExtractionSetBundle:
    """Verifies DiscourseExtractionSet bundle integrity, provenance digests, and protocol."""

    def test_discourse_extraction_set_aggregation(
        self, sample_coordinate: EvidenceCoordinate
    ) -> None:
        claim = ClaimRecord(
            claim_id="CLM-001",
            text="Kinase phosphorylation was enhanced.",
            epistemic_status=EpistemicStatus.EMPIRICALLY_SUPPORTED_FINDING,
            confidence=0.95,
            coordinate=sample_coordinate,
        )
        method = MethodRecord(
            method_id="MET-001",
            name="Western Blotting",
            category="experimental",
            confidence=0.90,
            coordinate=sample_coordinate,
        )
        dataset = DatasetRecord(
            dataset_id="DS-001",
            name="Genomic Assay",
            confidence=0.88,
            coordinate=sample_coordinate,
        )
        metric = MetricRecord(
            metric_id="MTR-001",
            name="IC50",
            confidence=0.91,
            coordinate=sample_coordinate,
        )
        result = ResultRecord(
            result_id="RES-001",
            description="Reduced proliferation",
            confidence=0.89,
            coordinate=sample_coordinate,
        )
        limitation = LimitationRecord(
            limitation_id="LIM-001",
            description="Limited sample size",
            confidence=0.85,
            coordinate=sample_coordinate,
        )
        assumption = AssumptionRecord(
            assumption_id="ASM-001",
            statement="Constant temperature",
            confidence=0.87,
            coordinate=sample_coordinate,
        )
        formula = FormulaRecord(
            formula_id="FRM-001",
            latex_source="E = mc^2",
            confidence=0.99,
            coordinate=sample_coordinate,
        )

        extraction_set = DiscourseExtractionSet(
            document_id="DOC-STEM-001",
            extraction_id="EXT-001",
            timestamp_iso="2026-10-15T12:00:00Z",
            claims=[claim],
            methods=[method],
            datasets=[dataset],
            metrics=[metric],
            results=[result],
            limitations=[limitation],
            assumptions=[assumption],
            formulas=[formula],
        )

        assert extraction_set.total_entities_count() == 8
        digest = extraction_set.compute_manifest_hash()
        assert len(digest) == 64

        d = extraction_set.to_dict()
        reconstructed = DiscourseExtractionSet.from_dict(d)
        assert reconstructed.document_id == "DOC-STEM-001"
        assert reconstructed.total_entities_count() == 8
        assert len(reconstructed.claims) == 1
        assert len(reconstructed.methods) == 1
        assert len(reconstructed.datasets) == 1
        assert len(reconstructed.metrics) == 1
        assert len(reconstructed.results) == 1
        assert len(reconstructed.limitations) == 1
        assert len(reconstructed.assumptions) == 1
        assert len(reconstructed.formulas) == 1

        json_str = extraction_set.to_json()
        from_json_set = DiscourseExtractionSet.from_json(json_str)
        assert from_json_set.total_entities_count() == 8

    def test_malformed_coordinate_bounds_direct_check(
        self, sample_coordinate: EvidenceCoordinate
    ) -> None:
        object.__setattr__(sample_coordinate, "char_end", 50)  # char_start is 100
        with pytest.raises(MalformedDiscourseSpanError, match="Invalid character offset"):
            _validate_coordinate_span(sample_coordinate, "Valid text", 0.9)

    def test_discourse_extractor_runtime_contract(
        self, sample_coordinate: EvidenceCoordinate
    ) -> None:
        """Verify that a compliant class satisfies DiscourseExtractorContract Protocol."""

        class MockExtractor:
            def extract(
                self,
                document_id: str,
                text: str,
                coordinates: list[EvidenceCoordinate] | None = None,
            ) -> DiscourseExtractionSet:
                claim = ClaimRecord(
                    claim_id=f"{document_id}-CLM-1",
                    text=text[:50],
                    epistemic_status=EpistemicStatus.DIRECT_AUTHOR_CLAIM,
                    confidence=0.9,
                    coordinate=sample_coordinate,
                )
                return DiscourseExtractionSet(
                    document_id=document_id,
                    extraction_id="EXT-MOCK-1",
                    timestamp_iso="2026-10-15T12:00:00Z",
                    claims=[claim],
                )

        mock_ext = MockExtractor()
        assert isinstance(mock_ext, DiscourseExtractorContract)

        result = mock_ext.extract("DOC-TEST-1", "A sample scientific premise text.")
        assert result.total_entities_count() == 1
        assert result.claims[0].claim_id == "DOC-TEST-1-CLM-1"

    def test_discourse_entity_type_enum(self) -> None:
        """Verify all DiscourseEntityType values."""
        assert DiscourseEntityType.CLAIM.value == "CLAIM"
        assert DiscourseEntityType.METHOD.value == "METHOD"
        assert DiscourseEntityType.DATASET.value == "DATASET"
        assert DiscourseEntityType.METRIC.value == "METRIC"
        assert DiscourseEntityType.RESULT.value == "RESULT"
        assert DiscourseEntityType.LIMITATION.value == "LIMITATION"
        assert DiscourseEntityType.ASSUMPTION.value == "ASSUMPTION"
        assert DiscourseEntityType.FORMULA.value == "FORMULA"
