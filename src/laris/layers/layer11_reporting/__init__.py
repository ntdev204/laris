"""Layer 11: Reporting, Evidence Inspection and Productization.

Exports structured research report schemas, canonical section definitions,
and evidence verification gates adhering to Boundary K and DOC-SPEC-REP-001.
"""

from __future__ import annotations

from laris.layers.layer11_reporting.report_generator import (
    StructuredReportGenerator,
)
from laris.layers.layer11_reporting.report_schema import (
    AssertionStatus,
    CorpusManifestEntry,
    EvidenceGate,
    ReportAssertion,
    ReportSection,
    ReportSectionType,
    ReportVerificationSummary,
    StructuredResearchReport,
)

__all__ = [
    "AssertionStatus",
    "CorpusManifestEntry",
    "EvidenceGate",
    "ReportAssertion",
    "ReportSection",
    "ReportSectionType",
    "ReportVerificationSummary",
    "StructuredReportGenerator",
    "StructuredResearchReport",
]
