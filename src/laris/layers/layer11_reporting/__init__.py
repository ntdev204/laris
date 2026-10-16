"""Layer 11: Reporting, Evidence Inspection and Productization.

Exports structured research report schemas, canonical section definitions,
evidence verification gates, local-first inspection interfaces, version lineage
with append-only cryptographic audit trails, and on-demand academic manuscript composer
adhering to Boundary K and DOC-SPEC-REP-001.
"""

from __future__ import annotations

from laris.layers.layer11_reporting.evidence_inspector import (
    EvidenceInspector,
    EvidenceSourceCard,
    InspectionSummary,
)
from laris.layers.layer11_reporting.lineage import (
    CorpusVersionRecord,
    InterventionAuditTrail,
    InterventionType,
    LineageRegistry,
    ProjectHistoryManager,
    ReportVersionRecord,
    RunVersionRecord,
    TargetEntityType,
    UserInterventionRecord,
)
from laris.layers.layer11_reporting.manuscript_composer import (
    AcademicManuscript,
    ManuscriptComposer,
    ManuscriptFormat,
    ManuscriptSection,
)
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
    "AcademicManuscript",
    "AssertionStatus",
    "CorpusManifestEntry",
    "CorpusVersionRecord",
    "EvidenceGate",
    "EvidenceInspector",
    "EvidenceSourceCard",
    "InspectionSummary",
    "InterventionAuditTrail",
    "InterventionType",
    "LineageRegistry",
    "ManuscriptComposer",
    "ManuscriptFormat",
    "ManuscriptSection",
    "ProjectHistoryManager",
    "ReportAssertion",
    "ReportSection",
    "ReportSectionType",
    "ReportVerificationSummary",
    "ReportVersionRecord",
    "RunVersionRecord",
    "StructuredReportGenerator",
    "StructuredResearchReport",
    "TargetEntityType",
    "UserInterventionRecord",
]
