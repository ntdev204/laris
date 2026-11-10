"""Regression cases for source-backed report certification."""

import hashlib
from dataclasses import replace

import pytest

from laris.core.errors import UnanchoredAssertionError
from laris.core.schemas import EvidenceCoordinate
from laris.reporting.report_schema import (
    CorpusManifestEntry,
    ReportAssertion,
    ReportSection,
    ReportSectionType,
    StructuredResearchReport,
)
from laris.reporting.source_gate import SourceEvidenceGate

TEXT = "The benchmark contains 500 annotated abstracts."


def report():
    sha = hashlib.sha256(TEXT.encode()).hexdigest()
    coordinate = EvidenceCoordinate("c1", "d1", sha, 1, "abstract", 0, 0, 0, len(TEXT), TEXT)
    sections = {s: ReportSection(s, s.value, "", []) for s in ReportSectionType}
    section = sections[ReportSectionType.EXECUTIVE_SUMMARY]
    section.content_markdown = TEXT
    section.assertions = [ReportAssertion("a1", section.section_type, TEXT, ["c1"])]
    return StructuredResearchReport(
        "report", "Inspect the benchmark", "2026-11-10T00:00:00Z",
        [CorpusManifestEntry("d1", "Benchmark", sha, 2026, "test")], sections, {"c1": coordinate}
    )


def test_exact_excerpt_is_certified():
    r = report()
    assert SourceEvidenceGate({"d1": TEXT}).verify_report(r).is_valid


@pytest.mark.parametrize("defect", ["source", "offset", "snippet", "checksum", "identity",
                                    "unsupported", "prose", "empty", "missing_source"])
def test_false_certification_is_rejected(defect):
    r = report()
    sources = {"d1": TEXT}
    section = r.sections[ReportSectionType.EXECUTIVE_SUMMARY]
    if defect == "source":
        sources["d1"] = "Tampered source"
    elif defect == "offset":
        r.citation_index["c1"] = replace(r.citation_index["c1"], char_start=1)
    elif defect == "snippet":
        r.citation_index["c1"] = replace(r.citation_index["c1"], verbatim_snippet="Invented")
    elif defect == "checksum":
        r.citation_index["c1"] = replace(r.citation_index["c1"], document_sha256="a" * 64)
    elif defect == "identity":
        r.citation_index["c1"] = replace(r.citation_index["c1"], coordinate_id="other")
    elif defect == "unsupported":
        section.assertions[0].statement = "The model solves scientific reasoning."
        section.content_markdown = section.assertions[0].statement
    elif defect == "prose":
        section.content_markdown += " This proves human-level research ability."
    elif defect == "empty":
        section.assertions = []
    elif defect == "missing_source":
        sources = {}
    gate = SourceEvidenceGate(sources)
    with pytest.raises(UnanchoredAssertionError):
        gate.verify_report(r)
    assert not gate.verify_report(r, strict=False).is_valid
