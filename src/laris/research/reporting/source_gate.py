"""Source-backed certification for extractive reports, without semantic inference claims."""

import hashlib
from dataclasses import replace
from typing import Dict

from laris.research.reporting.report_schema import (
    AssertionStatus,
    EvidenceGate,
    ReportVerificationSummary,
    StructuredResearchReport,
)
from laris.shared.core.errors import ProvenanceViolationError, UnanchoredAssertionError
from laris.shared.retrieval.provenance import EvidenceCoordinateValidator


class SourceEvidenceGate(EvidenceGate):
    """Require exact source excerpts and complete registration of rendered section text.

    Unlike the legacy citation-ID gate, this gate needs the actual source texts.
    It deliberately refuses paraphrases and synthesis: matching a source coordinate
    alone does not establish entailment. Empty sections are permitted; empty reports
    and extra prose outside the registered assertions cannot be certified.
    """

    def __init__(self, source_documents: Dict[str, str]) -> None:
        super().__init__(minimum_coverage_ratio=1.0)
        self._sources = dict(source_documents)

    def verify_report(
        self, report: StructuredResearchReport, strict: bool = True
    ) -> ReportVerificationSummary:
        summary = super().verify_report(report, strict=strict)
        problems = []
        assertions = report.all_assertions()
        if not assertions:
            problems.append("Report contains no registered assertions.")
        ids = [a.assertion_id for a in assertions]
        if len(ids) != len(set(ids)):
            problems.append("Duplicate assertion IDs.")

        manifest = {entry.document_id: entry.sha256_hash for entry in report.corpus_manifest}
        if len(manifest) != len(report.corpus_manifest):
            problems.append("Duplicate corpus document IDs.")
        validator = EvidenceCoordinateValidator(corpus=self._sources, document_checksums=manifest)
        for section in report.sections.values():
            expected = "\n\n".join(a.statement for a in section.assertions)
            if section.content_markdown.strip() != expected.strip():
                problems.append(
                    f"Section '{section.section_type.value}' contains unregistered prose."
                )
            for assertion in section.assertions:
                try:
                    if assertion.section != section.section_type:
                        raise ProvenanceViolationError("Assertion is in the wrong section.")
                    excerpts = []
                    for cid in assertion.coordinate_ids:
                        coordinate = report.citation_index.get(cid)
                        if coordinate is None or coordinate.coordinate_id != cid:
                            raise ProvenanceViolationError("Citation identity mismatch.")
                        doc_id = coordinate.document_id
                        if doc_id not in self._sources or doc_id not in manifest:
                            raise ProvenanceViolationError("Citation source is not registered.")
                        actual = hashlib.sha256(self._sources[doc_id].encode("utf-8")).hexdigest()
                        if actual != manifest[doc_id]:
                            raise ProvenanceViolationError("Source checksum mismatch.")
                        page = self._sources[doc_id][:coordinate.char_start].count("\f") + 1
                        if coordinate.page_number != page or "\f" in coordinate.verbatim_snippet:
                            raise ProvenanceViolationError(
                                "Citation page does not match source span."
                            )
                        validator.validate_coordinate(coordinate)
                        excerpts.append(coordinate.verbatim_snippet)
                    if not excerpts or any(assertion.statement != text for text in excerpts):
                        raise ProvenanceViolationError(
                            "Assertion is not an exact source excerpt; "
                            "semantic support is unverified."
                        )
                except ProvenanceViolationError as exc:
                    problems.append(f"Assertion '{assertion.assertion_id}': {exc}")
                    assertion.status = AssertionStatus.UNVERIFIED
                    assertion.caveat = str(exc)
                    if assertion.assertion_id not in summary.missing_evidence_ids:
                        summary.missing_evidence_ids.append(assertion.assertion_id)

        verified = sum(
            a.status == AssertionStatus.VERIFIED for a in assertions
        )
        summary = replace(
            summary,
            verified_assertions=verified,
            unanchored_assertions=len(assertions) - verified,
            coverage_ratio=verified / len(assertions) if assertions else 0.0,
            is_valid=summary.is_valid and not problems,
        )
        report.metadata["verification_scope"] = "source_spans_and_extractive_assertions"
        report.metadata["verification_errors"] = problems
        if problems and strict:
            raise UnanchoredAssertionError(
                "Source evidence verification failed: " + "; ".join(problems)
            )
        return summary
