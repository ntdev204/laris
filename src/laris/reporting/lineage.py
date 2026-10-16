"""Corpus, run, and report version lineage with auditable user interventions.

Adheres to DOC-SPEC-REP-001, DOC-SPEC-MOD-001 (Boundary K), ADR-001, ADR-004, and ADR-007:
- Local-first version lineage tracking across corpus versions, execution runs, and reports
- Lineage DAG navigation (history tracing, ancestors, descendants, full provenance)
- Append-only immutable cryptographic SHA-256 audit chain for user interventions
- User intervention controls: accept, modify, reject with explicit rationale and attribution
- Versioned report derivation upon user intervention with non-destructive history
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from laris.core.errors import (
    AuditIntegrityError,
    InvalidInterventionError,
    LineageCycleError,
    LineageNotFoundError,
    ReportSchemaValidationError,
)
from laris.reporting.report_schema import (
    AssertionStatus,
    ReportAssertion,
    StructuredResearchReport,
)


@dataclass(frozen=True)
class CorpusVersionRecord:
    """Record of a corpus manifest snapshot at a given point in time."""

    corpus_version_id: str
    document_ids: List[str]
    document_checksums: Dict[str, str]
    corpus_hash: str
    created_at_iso: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert record to dictionary."""
        return {
            "corpus_version_id": self.corpus_version_id,
            "document_ids": list(self.document_ids),
            "document_checksums": dict(self.document_checksums),
            "corpus_hash": self.corpus_hash,
            "created_at_iso": self.created_at_iso,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CorpusVersionRecord:
        """Construct record from dictionary."""
        return cls(
            corpus_version_id=data["corpus_version_id"],
            document_ids=list(data["document_ids"]),
            document_checksums=dict(data["document_checksums"]),
            corpus_hash=data["corpus_hash"],
            created_at_iso=data["created_at_iso"],
            metadata=dict(data.get("metadata", {})),
        )


@dataclass(frozen=True)
class RunVersionRecord:
    """Record of an orchestrated research synthesis run."""

    run_id: str
    corpus_version_id: str
    query_statement: str
    config_hash: str
    executed_at_iso: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert record to dictionary."""
        return {
            "run_id": self.run_id,
            "corpus_version_id": self.corpus_version_id,
            "query_statement": self.query_statement,
            "config_hash": self.config_hash,
            "executed_at_iso": self.executed_at_iso,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> RunVersionRecord:
        """Construct record from dictionary."""
        return cls(
            run_id=data["run_id"],
            corpus_version_id=data["corpus_version_id"],
            query_statement=data["query_statement"],
            config_hash=data["config_hash"],
            executed_at_iso=data["executed_at_iso"],
            metadata=dict(data.get("metadata", {})),
        )


@dataclass(frozen=True)
class ReportVersionRecord:
    """Record of a structured report version in the lineage DAG."""

    version_id: str
    report_id: str
    run_id: str
    parent_version_id: Optional[str]
    content_sha256: str
    created_at_iso: str
    description: str = ""
    derived_by_intervention_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert record to dictionary."""
        return {
            "version_id": self.version_id,
            "report_id": self.report_id,
            "run_id": self.run_id,
            "parent_version_id": self.parent_version_id,
            "content_sha256": self.content_sha256,
            "created_at_iso": self.created_at_iso,
            "description": self.description,
            "derived_by_intervention_id": self.derived_by_intervention_id,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ReportVersionRecord:
        """Construct record from dictionary."""
        return cls(
            version_id=data["version_id"],
            report_id=data["report_id"],
            run_id=data["run_id"],
            parent_version_id=data.get("parent_version_id"),
            content_sha256=data["content_sha256"],
            created_at_iso=data["created_at_iso"],
            description=data.get("description", ""),
            derived_by_intervention_id=data.get("derived_by_intervention_id"),
            metadata=dict(data.get("metadata", {})),
        )


class InterventionType(str, Enum):
    """Supported human intervention actions on report entities."""

    ACCEPT = "accept"
    MODIFY = "modify"
    REJECT = "reject"


class TargetEntityType(str, Enum):
    """Entity types subject to human inspection and intervention."""

    ASSERTION = "assertion"
    GAP = "gap"
    CONTRADICTION = "contradiction"
    COORDINATE = "coordinate"


@dataclass(frozen=True)
class UserInterventionRecord:
    """Immutable record of a user intervention with cryptographic hash chaining."""

    intervention_id: str
    intervention_type: InterventionType
    target_type: TargetEntityType
    target_id: str
    author_id: str
    created_at_iso: str
    rationale: str
    previous_state: Dict[str, Any]
    modified_state: Optional[Dict[str, Any]]
    parent_entry_hash: str
    entry_hash: str

    def compute_expected_hash(self) -> str:
        """Deterministically compute SHA-256 hash of this entry and its parent hash."""
        payload = {
            "intervention_id": self.intervention_id,
            "intervention_type": self.intervention_type.value,
            "target_type": self.target_type.value,
            "target_id": self.target_id,
            "author_id": self.author_id,
            "created_at_iso": self.created_at_iso,
            "rationale": self.rationale,
            "previous_state": self.previous_state,
            "modified_state": self.modified_state,
            "parent_entry_hash": self.parent_entry_hash,
        }
        canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    def is_hash_valid(self) -> bool:
        """Check whether the recorded entry_hash matches the computed cryptographic hash."""
        return self.entry_hash == self.compute_expected_hash()

    def to_dict(self) -> Dict[str, Any]:
        """Convert intervention record to dictionary."""
        return {
            "intervention_id": self.intervention_id,
            "intervention_type": self.intervention_type.value,
            "target_type": self.target_type.value,
            "target_id": self.target_id,
            "author_id": self.author_id,
            "created_at_iso": self.created_at_iso,
            "rationale": self.rationale,
            "previous_state": dict(self.previous_state),
            "modified_state": dict(self.modified_state) if self.modified_state else None,
            "parent_entry_hash": self.parent_entry_hash,
            "entry_hash": self.entry_hash,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> UserInterventionRecord:
        """Construct intervention record from dictionary."""
        return cls(
            intervention_id=data["intervention_id"],
            intervention_type=InterventionType(data["intervention_type"]),
            target_type=TargetEntityType(data["target_type"]),
            target_id=data["target_id"],
            author_id=data["author_id"],
            created_at_iso=data["created_at_iso"],
            rationale=data["rationale"],
            previous_state=dict(data["previous_state"]),
            modified_state=dict(data["modified_state"]) if data.get("modified_state") else None,
            parent_entry_hash=data["parent_entry_hash"],
            entry_hash=data["entry_hash"],
        )


class InterventionAuditTrail:
    """Append-only cryptographic audit log enforcing sequential hash integrity."""

    GENESIS_HASH = "0" * 64

    def __init__(self, records: Optional[List[UserInterventionRecord]] = None) -> None:
        self._records: List[UserInterventionRecord] = []
        if records:
            for r in records:
                self.append_record(r)

    @property
    def records(self) -> List[UserInterventionRecord]:
        """Return shallow copy of recorded interventions."""
        return list(self._records)

    @property
    def latest_hash(self) -> str:
        """Return the cryptographic hash of the latest entry, or GENESIS_HASH if empty."""
        return self._records[-1].entry_hash if self._records else self.GENESIS_HASH

    def append_record(self, record: UserInterventionRecord) -> None:
        """Append an externally constructed record verifying chain linkage and hash validity."""
        expected_parent = self.latest_hash
        if record.parent_entry_hash != expected_parent:
            raise AuditIntegrityError(
                f"Audit chain broken: parent_entry_hash '{record.parent_entry_hash}' "
                f"does not match expected '{expected_parent}'."
            )
        if not record.is_hash_valid():
            raise AuditIntegrityError(
                f"Audit hash mismatch for intervention '{record.intervention_id}': "
                f"recorded '{record.entry_hash}' != computed '{record.compute_expected_hash()}'."
            )
        self._records.append(record)

    def record_intervention(
        self,
        intervention_id: str,
        intervention_type: InterventionType,
        target_type: TargetEntityType,
        target_id: str,
        author_id: str,
        created_at_iso: str,
        rationale: str,
        previous_state: Dict[str, Any],
        modified_state: Optional[Dict[str, Any]] = None,
    ) -> UserInterventionRecord:
        """Create, hash, and append a new user intervention record."""
        if not intervention_id.strip():
            raise InvalidInterventionError("intervention_id cannot be empty.")
        if not target_id.strip():
            raise InvalidInterventionError("target_id cannot be empty.")
        if not author_id.strip():
            raise InvalidInterventionError("author_id cannot be empty.")
        if not rationale.strip():
            raise InvalidInterventionError("rationale cannot be empty.")

        parent_hash = self.latest_hash

        # Compute payload hash
        payload = {
            "intervention_id": intervention_id,
            "intervention_type": intervention_type.value,
            "target_type": target_type.value,
            "target_id": target_id,
            "author_id": author_id,
            "created_at_iso": created_at_iso,
            "rationale": rationale,
            "previous_state": previous_state,
            "modified_state": modified_state,
            "parent_entry_hash": parent_hash,
        }
        canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        entry_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

        rec = UserInterventionRecord(
            intervention_id=intervention_id,
            intervention_type=intervention_type,
            target_type=target_type,
            target_id=target_id,
            author_id=author_id,
            created_at_iso=created_at_iso,
            rationale=rationale,
            previous_state=previous_state,
            modified_state=modified_state,
            parent_entry_hash=parent_hash,
            entry_hash=entry_hash,
        )
        self._records.append(rec)
        return rec

    def verify_integrity(self) -> bool:
        """Verify the full cryptographic chain from genesis to latest record."""
        expected_parent = self.GENESIS_HASH
        for idx, rec in enumerate(self._records):
            if rec.parent_entry_hash != expected_parent:
                raise AuditIntegrityError(
                    f"Integrity failure at index {idx}: parent hash {rec.parent_entry_hash} "
                    f"!= expected {expected_parent}."
                )
            if not rec.is_hash_valid():
                raise AuditIntegrityError(
                    f"Integrity failure at index {idx} ({rec.intervention_id}): hash corrupted."
                )
            expected_parent = rec.entry_hash
        return True

    def get_by_target(self, target_id: str) -> List[UserInterventionRecord]:
        """Return all interventions for a specified target entity ID."""
        return [r for r in self._records if r.target_id == target_id]

    def get_by_author(self, author_id: str) -> List[UserInterventionRecord]:
        """Return all interventions submitted by a specified author ID."""
        return [r for r in self._records if r.author_id == author_id]

    def to_dict(self) -> Dict[str, Any]:
        """Serialize complete audit trail to dictionary."""
        return {
            "genesis_hash": self.GENESIS_HASH,
            "latest_hash": self.latest_hash,
            "total_records": len(self._records),
            "records": [r.to_dict() for r in self._records],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> InterventionAuditTrail:
        """Construct audit trail from serialized dictionary."""
        records = [UserInterventionRecord.from_dict(r) for r in data.get("records", [])]
        return cls(records=records)


class LineageRegistry:
    """Registry maintaining corpus, run, and report version lineage DAGs."""

    def __init__(self) -> None:
        self.corpus_versions: Dict[str, CorpusVersionRecord] = {}
        self.run_versions: Dict[str, RunVersionRecord] = {}
        self.report_versions: Dict[str, ReportVersionRecord] = {}

    def register_corpus_version(self, record: CorpusVersionRecord) -> None:
        """Register a corpus version snapshot."""
        if not record.corpus_version_id.strip():
            raise ReportSchemaValidationError("corpus_version_id cannot be empty.")
        self.corpus_versions[record.corpus_version_id] = record

    def register_run_version(self, record: RunVersionRecord) -> None:
        """Register an execution run record."""
        if not record.run_id.strip():
            raise ReportSchemaValidationError("run_id cannot be empty.")
        if record.corpus_version_id not in self.corpus_versions:
            raise LineageNotFoundError(
                f"Referenced corpus version '{record.corpus_version_id}' is not registered."
            )
        self.run_versions[record.run_id] = record

    def register_report_version(self, record: ReportVersionRecord) -> None:
        """Register a report version in the lineage DAG with cycle detection."""
        if not record.version_id.strip():
            raise ReportSchemaValidationError("version_id cannot be empty.")
        if record.run_id not in self.run_versions:
            raise LineageNotFoundError(f"Referenced run_id '{record.run_id}' is not registered.")

        if record.parent_version_id is not None:
            if record.parent_version_id not in self.report_versions:
                raise LineageNotFoundError(
                    f"Parent report version '{record.parent_version_id}' is not registered."
                )
            # Cycle detection: traverse ancestors of parent_version_id
            curr: Optional[str] = record.parent_version_id
            while curr is not None:
                if curr == record.version_id:
                    raise LineageCycleError(
                        f"Cycle detected: version '{record.version_id}' is in its own ancestry."
                    )
                parent_rec = self.report_versions.get(curr)
                curr = parent_rec.parent_version_id if parent_rec else None

        self.report_versions[record.version_id] = record

    def get_report_version(self, version_id: str) -> ReportVersionRecord:
        """Retrieve a registered report version record."""
        rec = self.report_versions.get(version_id)
        if rec is None:
            raise LineageNotFoundError(f"Report version '{version_id}' not found in registry.")
        return rec

    def get_report_history(self, version_id: str) -> List[ReportVersionRecord]:
        """Navigate backwards to trace ordered ancestry from root to the specified version."""
        curr_rec = self.get_report_version(version_id)
        history: List[ReportVersionRecord] = [curr_rec]

        while curr_rec.parent_version_id is not None:
            curr_rec = self.get_report_version(curr_rec.parent_version_id)
            history.append(curr_rec)

        history.reverse()
        return history

    def get_child_versions(self, version_id: str) -> List[ReportVersionRecord]:
        """Find all direct child report versions branched from the specified version."""
        # Ensure version exists
        self.get_report_version(version_id)
        return [
            rec for rec in self.report_versions.values()
            if rec.parent_version_id == version_id
        ]

    def trace_full_lineage(self, version_id: str) -> Dict[str, Any]:
        """Produce full lineage trace linking report version to run and corpus versions."""
        report_rec = self.get_report_version(version_id)
        run_rec = self.run_versions[report_rec.run_id]
        corpus_rec = self.corpus_versions[run_rec.corpus_version_id]
        history = self.get_report_history(version_id)

        return {
            "report_version": report_rec.to_dict(),
            "execution_run": run_rec.to_dict(),
            "corpus_version": corpus_rec.to_dict(),
            "ancestor_version_count": len(history) - 1,
            "ancestor_chain": [r.version_id for r in history],
        }

    def diff_reports(
        self,
        base_report: StructuredResearchReport,
        target_report: StructuredResearchReport,
    ) -> Dict[str, Any]:
        """Compute structured difference between two versions of a research report."""
        base_assertions = {a.assertion_id: a for a in base_report.all_assertions()}
        target_assertions = {a.assertion_id: a for a in target_report.all_assertions()}

        added_assertions: List[Dict[str, Any]] = []
        removed_assertions: List[Dict[str, Any]] = []
        modified_assertions: List[Dict[str, Any]] = []

        for aid, t_assert in target_assertions.items():
            if aid not in base_assertions:
                added_assertions.append(t_assert.to_dict())
            else:
                b_assert = base_assertions[aid]
                if (
                    b_assert.statement != t_assert.statement
                    or b_assert.status != t_assert.status
                    or b_assert.confidence_score != t_assert.confidence_score
                    or b_assert.caveat != t_assert.caveat
                    or b_assert.coordinate_ids != t_assert.coordinate_ids
                ):
                    modified_assertions.append({
                        "assertion_id": aid,
                        "before": b_assert.to_dict(),
                        "after": t_assert.to_dict(),
                    })

        for aid, b_assert in base_assertions.items():
            if aid not in target_assertions:
                removed_assertions.append(b_assert.to_dict())

        return {
            "base_report_id": base_report.report_id,
            "target_report_id": target_report.report_id,
            "added_count": len(added_assertions),
            "removed_count": len(removed_assertions),
            "modified_count": len(modified_assertions),
            "added": added_assertions,
            "removed": removed_assertions,
            "modified": modified_assertions,
        }


class ProjectHistoryManager:
    """Integrated interface managing report versions, evidence inspection, and interventions."""

    def __init__(
        self,
        lineage_registry: Optional[LineageRegistry] = None,
        audit_trail: Optional[InterventionAuditTrail] = None,
    ) -> None:
        self.lineage: LineageRegistry = lineage_registry or LineageRegistry()
        self.audit: InterventionAuditTrail = audit_trail or InterventionAuditTrail()

    def apply_assertion_intervention(
        self,
        report: StructuredResearchReport,
        current_version_id: str,
        new_version_id: str,
        assertion_id: str,
        intervention_type: InterventionType,
        author_id: str,
        rationale: str,
        created_at_iso: str,
        modified_statement: Optional[str] = None,
        modified_confidence: Optional[float] = None,
        modified_caveat: Optional[str] = None,
    ) -> Tuple[StructuredResearchReport, UserInterventionRecord, ReportVersionRecord]:
        """Apply user intervention to an assertion, deriving a new version with audit trail."""
        # Verify parent report version exists
        parent_rec = self.lineage.get_report_version(current_version_id)

        # Deep copy report to preserve immutability of parent
        new_report = copy.deepcopy(report)

        # Locate assertion in new_report
        target_assertion: Optional[ReportAssertion] = None
        for sec in new_report.sections.values():
            for a in sec.assertions:
                if a.assertion_id == assertion_id:
                    target_assertion = a
                    break
            if target_assertion:
                break

        if target_assertion is None:
            raise InvalidInterventionError(
                f"Assertion '{assertion_id}' not found in report '{report.report_id}'."
            )

        previous_state = target_assertion.to_dict()

        if intervention_type == InterventionType.ACCEPT:
            target_assertion.status = AssertionStatus.VERIFIED
            modified_state = target_assertion.to_dict()
        elif intervention_type == InterventionType.REJECT:
            target_assertion.status = AssertionStatus.REJECTED
            if modified_caveat:
                target_assertion.caveat = modified_caveat
            modified_state = target_assertion.to_dict()
        elif intervention_type == InterventionType.MODIFY:
            if modified_statement is not None:
                target_assertion.statement = modified_statement
            if modified_confidence is not None:
                target_assertion.confidence_score = modified_confidence
            if modified_caveat is not None:
                target_assertion.caveat = modified_caveat
            target_assertion.status = AssertionStatus.VERIFIED
            modified_state = target_assertion.to_dict()
        else:
            raise InvalidInterventionError(f"Unsupported intervention type: {intervention_type}")

        # Record intervention in audit trail
        intervention_id = f"intv-{assertion_id}-{len(self.audit.records) + 1:04d}"
        intv_rec = self.audit.record_intervention(
            intervention_id=intervention_id,
            intervention_type=intervention_type,
            target_type=TargetEntityType.ASSERTION,
            target_id=assertion_id,
            author_id=author_id,
            created_at_iso=created_at_iso,
            rationale=rationale,
            previous_state=previous_state,
            modified_state=modified_state,
        )

        # Compute content hash of new report
        rendered_md = new_report.render_markdown()
        content_hash = hashlib.sha256(rendered_md.encode("utf-8")).hexdigest()

        # Register new report version in lineage
        version_rec = ReportVersionRecord(
            version_id=new_version_id,
            report_id=new_report.report_id,
            run_id=parent_rec.run_id,
            parent_version_id=current_version_id,
            content_sha256=content_hash,
            created_at_iso=created_at_iso,
            description=f"Derived via {intervention_type.value} intervention on {assertion_id}",
            derived_by_intervention_id=intervention_id,
        )
        self.lineage.register_report_version(version_rec)

        return new_report, intv_rec, version_rec
