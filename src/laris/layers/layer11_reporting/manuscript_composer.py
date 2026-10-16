"""On-demand academic manuscript composer adhering to Boundary K and DOC-SPEC-REP-001.

Adheres to DOC-SPEC-REP-001, DOC-SPEC-MOD-001 (Boundary K), ADR-001, and ADR-004:
- Strictly opt-in execution (rejects unprompted generation to preserve default report)
- Maps canonical 7-section structured reports to academic IMRAD paper format:
  1. Title & Abstract
  2. Introduction & Problem Formulation
  3. Related Work
  4. Methodology & Contradiction Analysis
  5. Experimental Design & Validation Protocols
  6. Discussion, Limitations & Epistemic Boundaries
  7. References & Primary Evidence Index
- Produces publication-grade Markdown and standard LaTeX article drafts
- Guarantees complete evidence provenance preservation with coordinate traceability
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from laris.core.errors import (
    ModuleContractViolationError,
    ReportSchemaValidationError,
)
from laris.core.schemas import EvidenceCoordinate
from laris.layers.layer11_reporting.report_schema import (
    ReportSectionType,
    StructuredResearchReport,
)


class ManuscriptFormat(str, Enum):
    """Supported output rendering formats for academic manuscripts."""

    MARKDOWN = "markdown"
    LATEX = "latex"


@dataclass
class ManuscriptSection:
    """A discrete academic section following IMRAD format."""

    section_id: str
    heading: str
    body: str
    citations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert manuscript section to dictionary."""
        return {
            "section_id": self.section_id,
            "heading": self.heading,
            "body": self.body,
            "citations": list(self.citations),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ManuscriptSection:
        """Construct manuscript section from dictionary."""
        return cls(
            section_id=data["section_id"],
            heading=data["heading"],
            body=data["body"],
            citations=list(data.get("citations", [])),
        )


@dataclass
class AcademicManuscript:
    """Full academic paper deliverable generated strictly on-demand."""

    manuscript_id: str
    report_id: str
    title: str
    abstract: str
    authors: List[str]
    sections: Dict[str, ManuscriptSection]
    citation_index: Dict[str, EvidenceCoordinate]
    created_at_iso: str
    target_venue: str = "General Scientific Proceedings"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.manuscript_id.strip():
            raise ReportSchemaValidationError("manuscript_id cannot be empty.")
        if not self.title.strip():
            raise ReportSchemaValidationError("title cannot be empty.")
        if not self.abstract.strip():
            raise ReportSchemaValidationError("abstract cannot be empty.")

    def render_markdown(self) -> str:
        """Render complete academic manuscript in GitHub-flavored markdown."""
        author_str = ", ".join(self.authors) if self.authors else "LARIS Research Synthesizer"
        lines = [
            f"# {self.title}",
            f"**Authors:** {author_str}",
            f"**Target Venue:** {self.target_venue}",
            f"**Derived From Report:** `{self.report_id}` ({self.created_at_iso})",
            "",
            "## Abstract",
            self.abstract,
            "",
            "---",
            "",
        ]

        for sec in self.sections.values():
            lines.append(f"## {sec.heading}")
            lines.append("")
            lines.append(sec.body)
            lines.append("")

        lines.append("## References & Evidence Coordinate Index")
        lines.append("")
        for cid, coord in sorted(self.citation_index.items()):
            lines.append(
                f"- `[{cid}]` **{coord.document_id}** (page {coord.page_number}, "
                f"sec: {coord.section_identifier}): \"{coord.verbatim_snippet}\" "
                f"(SHA-256: `{coord.document_sha256[:16]}...`)"
            )

        return "\n".join(lines)

    def render_latex(self) -> str:
        """Render complete academic manuscript as clean LaTeX article source."""
        escaped_authors = [
            a.replace("_", "\\_").replace("&", "\\&") for a in self.authors
        ]
        author_str = (
            " \\and ".join(escaped_authors) if escaped_authors else "LARIS Research Synthesizer"
        )
        escaped_title = self.title.replace("_", "\\_").replace("&", "\\&")
        lines = [
            "\\documentclass[11pt,a4paper]{article}",
            "\\usepackage[utf8]{inputenc}",
            "\\usepackage{amsmath,amssymb}",
            "\\usepackage{hyperref}",
            "\\usepackage{booktabs}",
            "",
            f"\\title{{{escaped_title}}}",
            f"\\author{{{author_str}}}",
            f"\\date{{{self.created_at_iso[:10]}}}",
            "",
            "\\begin{document}",
            "\\maketitle",
            "",
            "\\begin{abstract}",
            self.abstract,
            "\\end{abstract}",
            "",
        ]

        for sec in self.sections.values():
            escaped_heading = sec.heading.replace("_", "\\_").replace("&", "\\&")
            lines.append(f"\\section{{{escaped_heading}}}")
            lines.append(sec.body)
            lines.append("")

        lines.append("\\section*{References \\& Evidence Provenance Index}")
        lines.append("\\begin{itemize}")
        for cid, coord in sorted(self.citation_index.items()):
            escaped_snippet = coord.verbatim_snippet.replace("_", "\\_").replace("&", "\\&")
            lines.append(
                f"  \\item \\texttt{{{cid}}}: \\textbf{{{coord.document_id}}} "
                f"(p. {coord.page_number}, {coord.section_identifier}). "
                f"\\emph{{{escaped_snippet}}}"
            )
        lines.append("\\end{itemize}")
        lines.append("")
        lines.append("\\end{document}")

        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize academic manuscript to dictionary."""
        return {
            "manuscript_id": self.manuscript_id,
            "report_id": self.report_id,
            "title": self.title,
            "abstract": self.abstract,
            "authors": list(self.authors),
            "target_venue": self.target_venue,
            "created_at_iso": self.created_at_iso,
            "sections": {k: v.to_dict() for k, v in self.sections.items()},
            "citation_index": {k: v.coordinate_id for k, v in self.citation_index.items()},
            "metadata": dict(self.metadata),
        }


class ManuscriptComposer:
    """Agent composing publication-ready manuscripts strictly upon explicit command."""

    def compose_from_report(
        self,
        report: StructuredResearchReport,
        explicit_command: bool = False,
        authors: Optional[List[str]] = None,
        target_venue: str = "General Scientific Proceedings",
        custom_title: Optional[str] = None,
    ) -> AcademicManuscript:
        """Compose IMRAD academic manuscript from a verified StructuredResearchReport."""
        if not explicit_command:
            raise ModuleContractViolationError(
                "Manuscript composition is an on-demand deliverable that requires explicit user "
                "opt-in (explicit_command=True). The default canonical deliverable is always "
                "the Structured Research Report."
            )

        if not report.verify_all_sections_present():
            raise ReportSchemaValidationError(
                "Cannot compose manuscript: source report is missing mandatory canonical sections."
            )

        title = custom_title or f"Empirical Synthesis: {report.query_statement}"

        # Extract executive summary for abstract and introduction
        exec_sec = report.sections[ReportSectionType.EXECUTIVE_SUMMARY]
        query_text = report.query_statement.lower()
        num_docs = len(report.corpus_manifest)
        abstract = (
            f"This paper presents a systematic synthesis investigating {query_text}. "
            f"Based on a rigorous corpus boundary comprising {num_docs} sources, "
            f"we analyze experimental consensus, identify empirical contradictions, "
            f"and present calibrated research gaps and validation protocols."
        )

        sections: Dict[str, ManuscriptSection] = {}

        # 1. Introduction & Problem Formulation
        intro_content = (
            f"{exec_sec.content_markdown}\n\n"
            f"The primary inquiry addressed is: \"{report.query_statement}\". "
            f"We establish strict evidence-anchored boundaries across all analyzed claims."
        )
        sections["introduction"] = ManuscriptSection(
            section_id="sec-1-intro",
            heading="Introduction & Problem Formulation",
            body=intro_content,
            citations=[c for a in exec_sec.assertions for c in a.coordinate_ids],
        )

        # 2. Related Work & Corpus Provenance
        corpus_sec = report.sections[ReportSectionType.CORPUS_PROVENANCE_MANIFEST]
        synthesis_sec = report.sections[ReportSectionType.COMPARATIVE_SYNTHESIS]
        related_content = (
            f"### Literature Boundary & Corpus Provenance\n{corpus_sec.content_markdown}\n\n"
            f"### Comparative Methodological Analysis\n{synthesis_sec.content_markdown}"
        )
        sections["related_work"] = ManuscriptSection(
            section_id="sec-2-related",
            heading="Related Work & Methodological Synthesis",
            body=related_content,
            citations=[
                c for a in corpus_sec.assertions + synthesis_sec.assertions
                for c in a.coordinate_ids
            ],
        )

        # 3. Conflicting Evidence & Contradiction Analysis
        contra_sec = report.sections[ReportSectionType.CONTRADICTION_ANALYSIS]
        contra_content = (
            f"Empirical literature frequently exhibits divergent findings under varying "
            f"experimental regimes. Direct contradictions observed across studies:\n\n"
            f"{contra_sec.content_markdown}"
        )
        sections["contradictions"] = ManuscriptSection(
            section_id="sec-3-contra",
            heading="Conflicting Evidence & Contradiction Analysis",
            body=contra_content,
            citations=[c for a in contra_sec.assertions for c in a.coordinate_ids],
        )

        # 4. Ranked Research Gaps & Validation Protocols
        gaps_sec = report.sections[ReportSectionType.RESEARCH_GAPS]
        gaps_content = (
            f"Systematic gap analysis reveals targeted opportunities for empirical advance:\n\n"
            f"{gaps_sec.content_markdown}"
        )
        sections["research_gaps"] = ManuscriptSection(
            section_id="sec-4-gaps",
            heading="Ranked Research Gaps & Validation Protocols",
            body=gaps_content,
            citations=[c for a in gaps_sec.assertions for c in a.coordinate_ids],
        )

        # 5. Discussion, Limitations & Epistemic Boundaries
        limits_sec = report.sections[ReportSectionType.LIMITATIONS_AND_BOUNDARIES]
        limits_content = (
            f"### Limitations & Inherent Boundary Conditions\n{limits_sec.content_markdown}\n\n"
            f"All findings must be interpreted strictly within the bounded scope of literature."
        )
        sections["discussion"] = ManuscriptSection(
            section_id="sec-5-disc",
            heading="Discussion, Limitations & Epistemic Boundaries",
            body=limits_content,
            citations=[c for a in limits_sec.assertions for c in a.coordinate_ids],
        )

        manuscript_id = f"MS-{report.report_id}"
        return AcademicManuscript(
            manuscript_id=manuscript_id,
            report_id=report.report_id,
            title=title,
            abstract=abstract,
            authors=list(authors or ["LARIS Autonomous Research System"]),
            sections=sections,
            citation_index=dict(report.citation_index),
            created_at_iso=report.created_at_iso,
            target_venue=target_venue,
        )
