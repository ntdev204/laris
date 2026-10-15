"""Twelve-class research gap typology classifier for Layer 7 Reasoning Engine.

Adheres to DOC-SPEC-MOD-001 (Boundary G), DATA_SCHEMAS.md, and ADR-004:
- Deterministic classification into canonical 12 GapClass categories
- Conflict-guided typology mapping for empirical discrepancies and boundary breakdowns
- Pure local rule-based execution with zero network dependencies
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from laris.core.errors import ModuleContractViolationError
from laris.layers.layer7_reasoning.schemas import (
    ConflictRecord,
    ConflictType,
    GapClass,
)


class RuleBasedGapClassifier:
    """Classifies candidate scientific gaps into the canonical 12-class taxonomy."""

    def __init__(self) -> None:
        self._indicators: Dict[GapClass, List[str]] = {
            GapClass.DEPLOYMENT_RESOURCE_GAP: [
                r"\b(vram|memory|latency|throughput|hardware|compute|footprint|real-time)\b",
                r"\b(resource-constrained|computational cost|embedded|deployment)\b",
            ],
            GapClass.REPRODUCIBILITY_GAP: [
                r"\b(reproducib\w*|replicate|replication|failed to replicate|irreproducib\w*)\b",
                r"\b(missing artifacts|code availability|re-implementation)\b",
            ],
            GapClass.MEASUREMENT_EVALUATION_GAP: [
                r"\b(metric|evaluation protocol|benchmark leakage|scoring rubric)\b",
                r"\b(flawed measurement|eval metric|incompatible metric)\b",
            ],
            GapClass.DATASET_DOMAIN_GAP: [
                r"\b(dataset scarcity|unannotated|domain shift|cross-domain|dataset gap)\b",
                r"\b(low-resource language|specialized domain|niche corpus)\b",
            ],
            GapClass.GENERALIZATION_GAP: [
                r"\b(out-of-distribution|ood|distribution shift|generaliz\w*|transfer)\b",
                r"\b(fails under shift|cross-environment|covariate shift)\b",
            ],
            GapClass.ASSUMPTION_BOUNDARY_GAP: [
                r"\b(boundary condition|operating limit|parameter threshold|assumption)\b",
                r"\b(thermal limit|unstated assumption|breakdown condition)\b",
            ],
            GapClass.INTEGRATION_INTERDISCIPLINARY_GAP: [
                r"\b(interdisciplinary|cross-discipline|bridging|siloed|multimodal)\b",
                r"\b(cross-domain synthesis|inter-field|unifying framework)\b",
            ],
            GapClass.TEMPORAL_GAP: [
                r"\b(temporal|concept drift|outdated|obsolete|longitudinal)\b",
                r"\b(stale baseline|time-decay|historical)\b",
            ],
            GapClass.CONFLICTING_EVIDENCE_GAP: [
                r"\b(contradict\w*|conflicting evidence|empirical disagreement|inconsistent)\b",
                r"\b(discrepanc\w*|disparate outcome|opposing result)\b",
            ],
            GapClass.METHODOLOGICAL_GAP: [
                r"\b(methodolog\w*|algorithmic limitation|architecture flaw|technique)\b",
                r"\b(lack of method|computational approach|modeling strategy)\b",
            ],
            GapClass.KNOWLEDGE_GAP: [
                r"\b(mechanism|theoretical foundation|fundamental principle|phenomenon)\b",
                r"\b(unknown cause|scientific explanation|unresolved theory)\b",
            ],
            GapClass.UNDEREXPLORED_RESEARCH_QUESTION: [
                r"\b(underexplored|open question|uncharted|scarce literature)\b",
                r"\b(unexamined|nascent direction|open problem)\b",
            ],
        }

    def classify_from_conflict(self, conflict: ConflictRecord) -> GapClass:
        """Derives a gap classification directly from an empirical ConflictRecord."""
        if conflict.conflict_type in (
            ConflictType.DIRECT_EMPIRICAL_CONTRADICTION,
            ConflictType.CROSS_METHOD_SUPERIORITY_CONTRADICTION,
        ):
            return GapClass.CONFLICTING_EVIDENCE_GAP

        if conflict.conflict_type == ConflictType.BOUNDARY_CONDITION_DISCREPANCY:
            return GapClass.ASSUMPTION_BOUNDARY_GAP

        if conflict.conflict_type == ConflictType.APPARENT_CONFLICT_INCOMPARABLE:
            desc_lower = conflict.description.lower()
            caveat_types = [c.caveat_type.lower() for c in conflict.comparability_caveats]
            combined = " ".join(caveat_types) + " " + desc_lower

            if "metric" in combined or "unit" in combined:
                return GapClass.MEASUREMENT_EVALUATION_GAP
            if "split" in combined or "domain" in combined:
                return GapClass.DATASET_DOMAIN_GAP
            return GapClass.GENERALIZATION_GAP

        return GapClass.KNOWLEDGE_GAP

    def classify_text(self, text: str) -> GapClass:
        """Classifies text into one of the 12 GapClass categories using indicator density."""
        if not text or not text.strip():
            raise ModuleContractViolationError("Text to classify must not be empty.")

        text_lower = text.lower()
        scored_classes: List[tuple[int, GapClass]] = []

        for gap_class, patterns in self._indicators.items():
            match_count = 0
            for pattern in patterns:
                matches = re.findall(pattern, text_lower)
                match_count += len(matches)
            if match_count > 0:
                scored_classes.append((match_count, gap_class))

        if scored_classes:
            scored_classes.sort(key=lambda x: x[0], reverse=True)
            return scored_classes[0][1]

        return GapClass.UNDEREXPLORED_RESEARCH_QUESTION

    def classify_candidate(
        self,
        title: str,
        description: str,
        conflict: Optional[ConflictRecord] = None,
    ) -> GapClass:
        """Primary classification dispatch evaluating conflicts, title, and description."""
        if conflict is not None:
            return self.classify_from_conflict(conflict)

        combined = f"{title}. {description}"
        return self.classify_text(combined)
