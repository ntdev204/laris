"""Adaptive task routing and hardware degradation fallbacks for Layer 9.

Adheres to DOC-SPEC-MOD-001 (Boundary I), ADR-001, ADR-005, ADR-006, and Issue #70:
- Multi-tier specialist execution hierarchy (Tier 0 Symbolic to Tier 3 Deep Reasoning)
- Dynamic task routing gated by task domain, epistemic uncertainty, and VRAM headroom
- Graceful degradation fallbacks from dense neural models to lexical/heuristic matchers
- Hardware stress benchmark protocol validating peak VRAM <= 15.0 GB and zero CUDA OOM
- Clear distinction between simulated telemetry and verified target hardware measurements
"""

from __future__ import annotations

import datetime
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from laris.core.errors import (
    ModuleContractViolationError,
    TaskRoutingError,
    UncertaintyCeilingExceededError,
)
from laris.execution.headroom_governor import (
    HeadroomBudgetGovernor,
)
from laris.execution.schemas import (
    SpecialistExecutionRequest,
    TelemetrySnapshot,
    TelemetryStatus,
)
from laris.execution.telemetry import (
    HardwareTelemetryEngine,
)
from laris.execution.weight_staging import (
    SpecialistLRUCache,
)


class ExecutionTier(str, Enum):
    """Multi-tier computational execution hierarchy defined in ADR-006 & MODEL_ROUTING.md."""

    TIER_0_SYMBOLIC = "TIER_0_SYMBOLIC"
    TIER_1_COMPACT = "TIER_1_COMPACT"
    TIER_2_MIDSIZED = "TIER_2_MIDSIZED"
    TIER_3_DEEP = "TIER_3_DEEP"


class TaskDomain(str, Enum):
    """Categorical domain of the incoming research subquery or scientific task."""

    SYMBOLIC_VALIDATION = "SYMBOLIC_VALIDATION"
    LEXICAL_RETRIEVAL = "LEXICAL_RETRIEVAL"
    DENSE_EMBEDDING = "DENSE_EMBEDDING"
    NLI_VERIFICATION = "NLI_VERIFICATION"
    CROSS_PAPER_SYNTHESIS = "CROSS_PAPER_SYNTHESIS"
    GAP_DISCOVERY = "GAP_DISCOVERY"


@dataclass(frozen=True)
class RoutingPolicy:
    """Configured execution policy and fallbacks for a specific task domain."""

    task_domain: TaskDomain
    primary_tier: ExecutionTier
    primary_specialist_id: str
    fallback_tier: ExecutionTier
    fallback_specialist_id: str
    epistemic_uncertainty_threshold: float = 0.15
    estimated_base_vram_bytes: int = 0
    activation_bytes_per_token: int = 1024
    estimated_latency_ms: float = 10.0
    fallback_base_vram_bytes: int = 0
    fallback_activation_bytes_per_token: int = 256
    fallback_latency_ms: float = 2.0
    escalation_tier: Optional[ExecutionTier] = None
    escalation_specialist_id: Optional[str] = None
    escalation_base_vram_bytes: int = 0
    escalation_latency_ms: float = 50.0

    def __post_init__(self) -> None:
        """Validate invariant constraints of the routing policy."""
        if not self.primary_specialist_id or not self.primary_specialist_id.strip():
            raise ModuleContractViolationError("primary_specialist_id cannot be empty.")
        if not self.fallback_specialist_id or not self.fallback_specialist_id.strip():
            raise ModuleContractViolationError("fallback_specialist_id cannot be empty.")
        if not 0.0 <= self.epistemic_uncertainty_threshold <= 1.0:
            raise UncertaintyCeilingExceededError(
                "epistemic_uncertainty_threshold must be within [0.0, 1.0]."
            )
        if self.estimated_base_vram_bytes < 0:
            raise ModuleContractViolationError("estimated_base_vram_bytes cannot be negative.")
        if self.activation_bytes_per_token < 0:
            raise ModuleContractViolationError("activation_bytes_per_token cannot be negative.")
        if self.estimated_latency_ms < 0.0:
            raise ModuleContractViolationError("estimated_latency_ms cannot be negative.")
        if self.fallback_base_vram_bytes < 0:
            raise ModuleContractViolationError("fallback_base_vram_bytes cannot be negative.")
        if self.fallback_activation_bytes_per_token < 0:
            raise ModuleContractViolationError(
                "fallback_activation_bytes_per_token cannot be negative."
            )
        if self.fallback_latency_ms < 0.0:
            raise ModuleContractViolationError("fallback_latency_ms cannot be negative.")
        if self.escalation_tier is not None and not self.escalation_specialist_id:
            raise ModuleContractViolationError(
                "escalation_specialist_id is required when escalation_tier is specified."
            )


@dataclass(frozen=True)
class TaskRoutingRequest:
    """Input request for adaptive task routing across execution tiers."""

    task_id: str
    domain: TaskDomain
    epistemic_uncertainty: float = 0.0
    batch_size: int = 1
    context_length: int = 512
    latency_budget_ms: Optional[float] = None
    force_tier: Optional[ExecutionTier] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate request parameters."""
        if not self.task_id or not self.task_id.strip():
            raise ModuleContractViolationError("TaskRoutingRequest task_id cannot be empty.")
        if not 0.0 <= self.epistemic_uncertainty <= 1.0:
            raise UncertaintyCeilingExceededError(
                f"epistemic_uncertainty {self.epistemic_uncertainty} must be within [0.0, 1.0]."
            )
        if self.batch_size <= 0:
            raise ModuleContractViolationError("batch_size must be strictly positive.")
        if self.context_length <= 0:
            raise ModuleContractViolationError("context_length must be strictly positive.")
        if self.latency_budget_ms is not None and self.latency_budget_ms <= 0.0:
            raise ModuleContractViolationError("latency_budget_ms must be strictly positive.")


@dataclass(frozen=True)
class RoutingDecision:
    """Immutable record of a task routing decision and justification."""

    task_id: str
    domain: TaskDomain
    selected_tier: ExecutionTier
    selected_specialist_id: str
    fallback_applied: bool = False
    fallback_reason: Optional[str] = None
    escalated_due_to_uncertainty: bool = False
    epistemic_uncertainty: float = 0.0
    projected_vram_bytes: int = 0
    projected_latency_ms: float = 0.0
    telemetry_snapshot: Optional[TelemetrySnapshot] = None
    decision_rationale: str = ""

    def __post_init__(self) -> None:
        """Validate routing decision record."""
        if not self.task_id or not self.task_id.strip():
            raise ModuleContractViolationError("RoutingDecision task_id cannot be empty.")
        if not self.selected_specialist_id or not self.selected_specialist_id.strip():
            raise ModuleContractViolationError(
                "RoutingDecision selected_specialist_id cannot be empty."
            )
        if self.projected_vram_bytes < 0:
            raise ModuleContractViolationError("projected_vram_bytes cannot be negative.")
        if self.projected_latency_ms < 0.0:
            raise ModuleContractViolationError("projected_latency_ms cannot be negative.")


class TaskRouter:
    """Adaptive computational dispatcher for Layer 9 specialist models."""

    def __init__(
        self,
        governor: Optional[HeadroomBudgetGovernor] = None,
        cache: Optional[SpecialistLRUCache] = None,
    ) -> None:
        self._governor = governor or HeadroomBudgetGovernor()
        self._cache = cache
        self._policies: Dict[TaskDomain, RoutingPolicy] = {}
        self._audit_trail: List[RoutingDecision] = []
        self._lock = threading.Lock()
        self._initialize_default_policies()

    def _initialize_default_policies(self) -> None:
        """Register canonical default routing policies adhering to MODEL_ROUTING.md."""
        # Tier 0: Symbolic validation and normalizers (0 VRAM)
        self.register_policy(
            TaskDomain.SYMBOLIC_VALIDATION,
            RoutingPolicy(
                task_domain=TaskDomain.SYMBOLIC_VALIDATION,
                primary_tier=ExecutionTier.TIER_0_SYMBOLIC,
                primary_specialist_id="symbolic_unit_validator",
                fallback_tier=ExecutionTier.TIER_0_SYMBOLIC,
                fallback_specialist_id="regex_fallback_sanitizer",
                epistemic_uncertainty_threshold=0.15,
                estimated_base_vram_bytes=0,
                activation_bytes_per_token=0,
                estimated_latency_ms=2.0,
            ),
        )

        # Tier 1: Lexical retrieval (e.g. BM25 / token-level index)
        self.register_policy(
            TaskDomain.LEXICAL_RETRIEVAL,
            RoutingPolicy(
                task_domain=TaskDomain.LEXICAL_RETRIEVAL,
                primary_tier=ExecutionTier.TIER_1_COMPACT,
                primary_specialist_id="bm25_lexical_index",
                fallback_tier=ExecutionTier.TIER_0_SYMBOLIC,
                fallback_specialist_id="exact_string_matcher",
                epistemic_uncertainty_threshold=0.15,
                estimated_base_vram_bytes=250 * 1024 * 1024,  # 250 MB
                activation_bytes_per_token=256,
                estimated_latency_ms=15.0,
            ),
        )

        # Tier 2: Dense semantic embeddings (falls back to Tier 1 BM25 on memory pressure)
        self.register_policy(
            TaskDomain.DENSE_EMBEDDING,
            RoutingPolicy(
                task_domain=TaskDomain.DENSE_EMBEDDING,
                primary_tier=ExecutionTier.TIER_2_MIDSIZED,
                primary_specialist_id="scibert_sentence_encoder",
                fallback_tier=ExecutionTier.TIER_1_COMPACT,
                fallback_specialist_id="bm25_lexical_index",
                epistemic_uncertainty_threshold=0.15,
                estimated_base_vram_bytes=1024 * 1024 * 1024,  # 1.0 GB
                activation_bytes_per_token=1024,
                estimated_latency_ms=45.0,
                fallback_base_vram_bytes=250 * 1024 * 1024,
                fallback_activation_bytes_per_token=256,
                fallback_latency_ms=15.0,
            ),
        )

        # Tier 2: 3-way NLI Verification (escalates to Tier 3 on high uncertainty)
        self.register_policy(
            TaskDomain.NLI_VERIFICATION,
            RoutingPolicy(
                task_domain=TaskDomain.NLI_VERIFICATION,
                primary_tier=ExecutionTier.TIER_2_MIDSIZED,
                primary_specialist_id="scientific_nli_classifier",
                fallback_tier=ExecutionTier.TIER_1_COMPACT,
                fallback_specialist_id="lexical_heuristic_comparator",
                epistemic_uncertainty_threshold=0.15,
                estimated_base_vram_bytes=int(1.5 * 1024 * 1024 * 1024),  # 1.5 GB
                activation_bytes_per_token=1024,
                estimated_latency_ms=80.0,
                fallback_base_vram_bytes=300 * 1024 * 1024,
                fallback_activation_bytes_per_token=256,
                fallback_latency_ms=20.0,
                escalation_tier=ExecutionTier.TIER_3_DEEP,
                escalation_specialist_id="deep_multihop_nli_reasoner",
                escalation_base_vram_bytes=int(3.5 * 1024 * 1024 * 1024),
                escalation_latency_ms=250.0,
            ),
        )

        # Tier 3: Cross-paper contradiction analysis (falls back to Tier 2 NLI)
        self.register_policy(
            TaskDomain.CROSS_PAPER_SYNTHESIS,
            RoutingPolicy(
                task_domain=TaskDomain.CROSS_PAPER_SYNTHESIS,
                primary_tier=ExecutionTier.TIER_3_DEEP,
                primary_specialist_id="cross_paper_contradiction_engine",
                fallback_tier=ExecutionTier.TIER_2_MIDSIZED,
                fallback_specialist_id="scientific_nli_classifier",
                epistemic_uncertainty_threshold=0.20,
                estimated_base_vram_bytes=int(4.0 * 1024 * 1024 * 1024),  # 4.0 GB
                activation_bytes_per_token=2048,
                estimated_latency_ms=300.0,
                fallback_base_vram_bytes=int(1.5 * 1024 * 1024 * 1024),
                fallback_activation_bytes_per_token=1024,
                fallback_latency_ms=80.0,
            ),
        )

        # Tier 3: 12-Class Research Gap Typology
        self.register_policy(
            TaskDomain.GAP_DISCOVERY,
            RoutingPolicy(
                task_domain=TaskDomain.GAP_DISCOVERY,
                primary_tier=ExecutionTier.TIER_3_DEEP,
                primary_specialist_id="gap_typology_reasoner",
                fallback_tier=ExecutionTier.TIER_1_COMPACT,
                fallback_specialist_id="heuristic_gap_scanner",
                epistemic_uncertainty_threshold=0.15,
                estimated_base_vram_bytes=int(3.0 * 1024 * 1024 * 1024),  # 3.0 GB
                activation_bytes_per_token=1024,
                estimated_latency_ms=220.0,
                fallback_base_vram_bytes=200 * 1024 * 1024,
                fallback_activation_bytes_per_token=256,
                fallback_latency_ms=25.0,
            ),
        )

    def register_policy(self, domain: TaskDomain, policy: RoutingPolicy) -> None:
        """Register or override a routing policy for a specific task domain."""
        with self._lock:
            self._policies[domain] = policy

    def get_policy(self, domain: TaskDomain) -> RoutingPolicy:
        """Retrieve the configured policy for a domain."""
        with self._lock:
            if domain not in self._policies:
                raise TaskRoutingError(f"No routing policy registered for domain {domain.value}.")
            return self._policies[domain]

    def route(
        self,
        request: TaskRoutingRequest,
        current_snapshot: Optional[TelemetrySnapshot] = None,
    ) -> RoutingDecision:
        """Dynamically evaluate routing policy, uncertainty escalation, and budget headroom."""
        policy = self.get_policy(request.domain)
        snapshot = current_snapshot or self._governor._telemetry_engine.sample()

        selected_tier = policy.primary_tier
        selected_specialist_id = policy.primary_specialist_id
        base_vram = policy.estimated_base_vram_bytes
        act_per_token = policy.activation_bytes_per_token
        latency_ms = policy.estimated_latency_ms
        fallback_applied = False
        fallback_reason: Optional[str] = None
        escalated_due_to_uncertainty = False
        rationale_parts: List[str] = []

        # 1. Force tier override
        if request.force_tier is not None:
            selected_tier = request.force_tier
            rationale_parts.append(f"Tier forced to {request.force_tier.value}")

        # 2. Epistemic uncertainty escalation check
        elif (
            request.epistemic_uncertainty > policy.epistemic_uncertainty_threshold
            and policy.escalation_tier is not None
            and policy.escalation_specialist_id is not None
        ):
            selected_tier = policy.escalation_tier
            selected_specialist_id = policy.escalation_specialist_id
            base_vram = policy.escalation_base_vram_bytes
            latency_ms = policy.escalation_latency_ms
            escalated_due_to_uncertainty = True
            rationale_parts.append(
                f"Epistemic uncertainty {request.epistemic_uncertainty:.2f} > threshold "
                f"{policy.epistemic_uncertainty_threshold:.2f}; escalated to {selected_tier.value}"
            )
        else:
            rationale_parts.append(
                f"Routed to primary tier {selected_tier.value} for {request.domain.value}"
            )

        # 3. Latency budget constraint check
        if request.latency_budget_ms is not None and latency_ms > request.latency_budget_ms:
            # Latency budget exceeded: downgrade to fallback
            selected_tier = policy.fallback_tier
            selected_specialist_id = policy.fallback_specialist_id
            base_vram = policy.fallback_base_vram_bytes
            act_per_token = policy.fallback_activation_bytes_per_token
            latency_ms = policy.fallback_latency_ms
            fallback_applied = True
            fallback_reason = (
                f"Estimated latency {policy.estimated_latency_ms:.1f} ms exceeds budget "
                f"{request.latency_budget_ms:.1f} ms."
            )
            rationale_parts.append(f"Fallback triggered: {fallback_reason}")

        # 4. Hardware VRAM headroom safety check (Boundary I)
        if selected_tier != ExecutionTier.TIER_0_SYMBOLIC:
            spec_req = SpecialistExecutionRequest(
                specialist_id=selected_specialist_id,
                batch_size=request.batch_size,
                context_length=request.context_length,
                estimated_base_vram_bytes=base_vram,
                activation_bytes_per_token=act_per_token,
            )

            # Check if execution requires safe fallback
            is_unsafe = self._governor.evaluate_safe_fallback(spec_req, snapshot)

            if is_unsafe and self._cache is not None:
                # Attempt to free VRAM by evicting inactive specialists from cache
                needed_bytes = self._governor.project_required_vram(spec_req)
                self._attempt_cache_eviction(needed_bytes)
                # Resample snapshot after cache eviction
                snapshot = self._governor._telemetry_engine.sample()
                is_unsafe = self._governor.evaluate_safe_fallback(spec_req, snapshot)

            if is_unsafe:
                # Engage graceful degradation fallback
                selected_tier = policy.fallback_tier
                selected_specialist_id = policy.fallback_specialist_id
                base_vram = policy.fallback_base_vram_bytes
                act_per_token = policy.fallback_activation_bytes_per_token
                latency_ms = policy.fallback_latency_ms
                fallback_applied = True
                projected_gb = (
                    snapshot.vram_allocated_bytes + self._governor.project_required_vram(spec_req)
                ) / (1024.0**3)
                fallback_reason = (
                    f"Memory pressure: projected allocation {projected_gb:.2f} GB "
                    f"threatens safety margin on {snapshot.device_name}."
                )
                rationale_parts.append(f"Fallback triggered: {fallback_reason}")

        # Compute final projected VRAM
        final_projected_vram = (
            0
            if selected_tier == ExecutionTier.TIER_0_SYMBOLIC
            else base_vram + (request.batch_size * request.context_length * act_per_token)
        )

        decision = RoutingDecision(
            task_id=request.task_id,
            domain=request.domain,
            selected_tier=selected_tier,
            selected_specialist_id=selected_specialist_id,
            fallback_applied=fallback_applied,
            fallback_reason=fallback_reason,
            escalated_due_to_uncertainty=escalated_due_to_uncertainty,
            epistemic_uncertainty=request.epistemic_uncertainty,
            projected_vram_bytes=final_projected_vram,
            projected_latency_ms=latency_ms,
            telemetry_snapshot=snapshot,
            decision_rationale="; ".join(rationale_parts),
        )

        with self._lock:
            self._audit_trail.append(decision)

        return decision

    def _attempt_cache_eviction(self, needed_bytes: int) -> None:
        """Evict oldest unpinned inactive specialists to Tier 2 Host RAM to free VRAM."""
        if self._cache is None:
            return
        freed = 0
        while freed < needed_bytes:
            evicted = self._cache.evict_lru()
            if evicted is None:
                break
            freed += evicted.size_bytes


    def get_audit_trail(self) -> List[RoutingDecision]:
        """Return an immutable copy of the router's decision audit trail."""
        with self._lock:
            return list(self._audit_trail)

    def clear_audit_trail(self) -> None:
        """Clear recorded audit trail."""
        with self._lock:
            self._audit_trail.clear()


@dataclass(frozen=True)
class HardwareBenchmarkReport:
    """Benchmark stress evaluation report adhering to M8-EXEC-003 acceptance gate."""

    timestamp_iso: str
    device_name: str
    total_tasks_routed: int
    peak_vram_bytes: int
    peak_vram_gb: float
    zero_cuda_oom: bool
    is_verified_hardware: bool
    fallback_count: int
    status_label: str
    passed_safety_gate: bool

    def __post_init__(self) -> None:
        """Validate benchmark report invariants."""
        if not self.timestamp_iso:
            raise ModuleContractViolationError("timestamp_iso cannot be empty.")
        if not self.device_name:
            raise ModuleContractViolationError("device_name cannot be empty.")
        if self.total_tasks_routed < 0:
            raise ModuleContractViolationError("total_tasks_routed cannot be negative.")
        if self.peak_vram_bytes < 0:
            raise ModuleContractViolationError("peak_vram_bytes cannot be negative.")


class HardwareStressProtocol:
    """Stress suite validating routing decisions, peak memory ceiling, and zero OOM."""

    def __init__(
        self,
        router: TaskRouter,
        telemetry_engine: Optional[HardwareTelemetryEngine] = None,
    ) -> None:
        self._router = router
        self._telemetry_engine = telemetry_engine or HardwareTelemetryEngine()

    def run_stress_suite(
        self,
        workload: Optional[List[TaskRoutingRequest]] = None,
    ) -> HardwareBenchmarkReport:
        """Execute workload across routing tiers while auditing peak VRAM and OOM safety."""
        requests = workload or self._generate_default_stress_workload()
        peak_vram = 0
        zero_oom = True
        fallbacks = 0
        verified_hardware = False
        status_label = TelemetryStatus.SIMULATED.value

        for req in requests:
            snapshot = self._telemetry_engine.sample()
            verified_hardware = snapshot.is_verified_hardware
            status_label = snapshot.status_label

            try:
                decision = self._router.route(req, current_snapshot=snapshot)
                if decision.fallback_applied:
                    fallbacks += 1

                # Record projected/allocated peak
                current_total = snapshot.vram_allocated_bytes + decision.projected_vram_bytes
                if current_total > peak_vram:
                    peak_vram = current_total

                # Verify against the strict 15.0 GB maximum ceiling
                if current_total > 15 * 1024 * 1024 * 1024:
                    zero_oom = False
            except Exception:
                zero_oom = False

        peak_gb = round(peak_vram / (1024.0**3), 3)
        passed_gate = peak_gb <= 15.0 and zero_oom

        return HardwareBenchmarkReport(
            timestamp_iso=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            device_name=self._telemetry_engine.sample().device_name,
            total_tasks_routed=len(requests),
            peak_vram_bytes=peak_vram,
            peak_vram_gb=peak_gb,
            zero_cuda_oom=zero_oom,
            is_verified_hardware=verified_hardware,
            fallback_count=fallbacks,
            status_label=status_label,
            passed_safety_gate=passed_gate,
        )

    def _generate_default_stress_workload(self) -> List[TaskRoutingRequest]:
        """Generate high-concurrency multi-tier synthetic stress requests."""
        workload: List[TaskRoutingRequest] = []
        domains = list(TaskDomain)
        uncertainties = [0.05, 0.12, 0.25, 0.65, 0.90]
        batch_sizes = [1, 2, 4, 8]
        context_lengths = [512, 1024, 2048]

        idx = 0
        for domain in domains:
            for u in uncertainties:
                b = batch_sizes[idx % len(batch_sizes)]
                c = context_lengths[idx % len(context_lengths)]
                workload.append(
                    TaskRoutingRequest(
                        task_id=f"stress_task_{idx:03d}",
                        domain=domain,
                        epistemic_uncertainty=u,
                        batch_size=b,
                        context_length=c,
                    )
                )
                idx += 1

        return workload
