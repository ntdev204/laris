"""Unit tests for Layer 9 adaptive task routing and degradation fallbacks.

Tests compliance with DOC-SPEC-MOD-001 (Boundary I), ADR-001, ADR-005, ADR-006, and Issue #70:
- RoutingPolicy, TaskRoutingRequest, RoutingDecision, and BenchmarkReport contracts
- Policy registration, default tier mapping, and retrieval
- Epistemic uncertainty escalation across computational tiers
- Latency budget degradation fallbacks
- Memory headroom degradation fallbacks on simulated VRAM pressure
- Cache eviction integration prior to degradation
- Audit trail logging and history preservation
- Hardware stress benchmark protocol validating peak VRAM <= 15.0 GB and zero CUDA OOM
"""

from typing import Optional

import pytest

from laris.core.errors import (
    ModuleContractViolationError,
    TaskRoutingError,
    UncertaintyCeilingExceededError,
)
from laris.layers.layer9_adaptive_execution.headroom_governor import (
    HeadroomBudgetGovernor,
)
from laris.layers.layer9_adaptive_execution.schemas import (
    HardwareTarget,
    TelemetryStatus,
)
from laris.layers.layer9_adaptive_execution.task_router import (
    ExecutionTier,
    HardwareBenchmarkReport,
    HardwareStressProtocol,
    RoutingDecision,
    RoutingPolicy,
    TaskDomain,
    TaskRouter,
    TaskRoutingRequest,
)
from laris.layers.layer9_adaptive_execution.telemetry import (
    HardwareTelemetryEngine,
    MockHardwareTelemetrySampler,
)
from laris.layers.layer9_adaptive_execution.weight_staging import (
    MockSpecialistWeightLoader,
    SpecialistLRUCache,
    SpecialistWeightDescriptor,
    StagingState,
    StorageTier,
)


class TestTaskRouterContracts:
    """Tests schema contracts and invariant enforcement for routing dataclasses."""

    def test_valid_routing_policy(self) -> None:
        """Test valid RoutingPolicy instantiation."""
        policy = RoutingPolicy(
            task_domain=TaskDomain.DENSE_EMBEDDING,
            primary_tier=ExecutionTier.TIER_2_MIDSIZED,
            primary_specialist_id="scibert_encoder",
            fallback_tier=ExecutionTier.TIER_1_COMPACT,
            fallback_specialist_id="bm25_retriever",
            epistemic_uncertainty_threshold=0.20,
            estimated_base_vram_bytes=1000,
            activation_bytes_per_token=512,
            estimated_latency_ms=25.0,
            fallback_base_vram_bytes=100,
            fallback_activation_bytes_per_token=64,
            fallback_latency_ms=5.0,
        )
        assert policy.task_domain == TaskDomain.DENSE_EMBEDDING
        assert policy.primary_tier == ExecutionTier.TIER_2_MIDSIZED
        assert policy.fallback_specialist_id == "bm25_retriever"

    @pytest.mark.parametrize(
        ("kwargs", "expected_err"),
        [
            (
                {
                    "task_domain": TaskDomain.DENSE_EMBEDDING,
                    "primary_tier": ExecutionTier.TIER_2_MIDSIZED,
                    "primary_specialist_id": "",
                    "fallback_tier": ExecutionTier.TIER_1_COMPACT,
                    "fallback_specialist_id": "fallback_spec",
                },
                ModuleContractViolationError,
            ),
            (
                {
                    "task_domain": TaskDomain.DENSE_EMBEDDING,
                    "primary_tier": ExecutionTier.TIER_2_MIDSIZED,
                    "primary_specialist_id": "primary_spec",
                    "fallback_tier": ExecutionTier.TIER_1_COMPACT,
                    "fallback_specialist_id": "   ",
                },
                ModuleContractViolationError,
            ),
            (
                {
                    "task_domain": TaskDomain.DENSE_EMBEDDING,
                    "primary_tier": ExecutionTier.TIER_2_MIDSIZED,
                    "primary_specialist_id": "primary_spec",
                    "fallback_tier": ExecutionTier.TIER_1_COMPACT,
                    "fallback_specialist_id": "fallback_spec",
                    "epistemic_uncertainty_threshold": 1.5,
                },
                UncertaintyCeilingExceededError,
            ),
            (
                {
                    "task_domain": TaskDomain.DENSE_EMBEDDING,
                    "primary_tier": ExecutionTier.TIER_2_MIDSIZED,
                    "primary_specialist_id": "primary_spec",
                    "fallback_tier": ExecutionTier.TIER_1_COMPACT,
                    "fallback_specialist_id": "fallback_spec",
                    "estimated_base_vram_bytes": -1,
                },
                ModuleContractViolationError,
            ),
            (
                {
                    "task_domain": TaskDomain.DENSE_EMBEDDING,
                    "primary_tier": ExecutionTier.TIER_2_MIDSIZED,
                    "primary_specialist_id": "primary_spec",
                    "fallback_tier": ExecutionTier.TIER_1_COMPACT,
                    "fallback_specialist_id": "fallback_spec",
                    "activation_bytes_per_token": -10,
                },
                ModuleContractViolationError,
            ),
            (
                {
                    "task_domain": TaskDomain.DENSE_EMBEDDING,
                    "primary_tier": ExecutionTier.TIER_2_MIDSIZED,
                    "primary_specialist_id": "primary_spec",
                    "fallback_tier": ExecutionTier.TIER_1_COMPACT,
                    "fallback_specialist_id": "fallback_spec",
                    "estimated_latency_ms": -5.0,
                },
                ModuleContractViolationError,
            ),
            (
                {
                    "task_domain": TaskDomain.DENSE_EMBEDDING,
                    "primary_tier": ExecutionTier.TIER_2_MIDSIZED,
                    "primary_specialist_id": "primary_spec",
                    "fallback_tier": ExecutionTier.TIER_1_COMPACT,
                    "fallback_specialist_id": "fallback_spec",
                    "fallback_base_vram_bytes": -10,
                },
                ModuleContractViolationError,
            ),
            (
                {
                    "task_domain": TaskDomain.DENSE_EMBEDDING,
                    "primary_tier": ExecutionTier.TIER_2_MIDSIZED,
                    "primary_specialist_id": "primary_spec",
                    "fallback_tier": ExecutionTier.TIER_1_COMPACT,
                    "fallback_specialist_id": "fallback_spec",
                    "fallback_activation_bytes_per_token": -2,
                },
                ModuleContractViolationError,
            ),
            (
                {
                    "task_domain": TaskDomain.DENSE_EMBEDDING,
                    "primary_tier": ExecutionTier.TIER_2_MIDSIZED,
                    "primary_specialist_id": "primary_spec",
                    "fallback_tier": ExecutionTier.TIER_1_COMPACT,
                    "fallback_specialist_id": "fallback_spec",
                    "fallback_latency_ms": -1.0,
                },
                ModuleContractViolationError,
            ),
            (
                {
                    "task_domain": TaskDomain.DENSE_EMBEDDING,
                    "primary_tier": ExecutionTier.TIER_2_MIDSIZED,
                    "primary_specialist_id": "primary_spec",
                    "fallback_tier": ExecutionTier.TIER_1_COMPACT,
                    "fallback_specialist_id": "fallback_spec",
                    "escalation_tier": ExecutionTier.TIER_3_DEEP,
                    "escalation_specialist_id": None,
                },
                ModuleContractViolationError,
            ),
        ],
    )
    def test_invalid_routing_policy(self, kwargs: dict, expected_err: type) -> None:
        """Test rejection of malformed RoutingPolicy parameters."""
        with pytest.raises(expected_err):
            RoutingPolicy(**kwargs)

    def test_valid_task_routing_request(self) -> None:
        """Test valid TaskRoutingRequest creation."""
        req = TaskRoutingRequest(
            task_id="task_001",
            domain=TaskDomain.LEXICAL_RETRIEVAL,
            epistemic_uncertainty=0.10,
            batch_size=2,
            context_length=1024,
            latency_budget_ms=50.0,
        )
        assert req.task_id == "task_001"
        assert req.batch_size == 2
        assert req.context_length == 1024
        assert req.latency_budget_ms == 50.0

    @pytest.mark.parametrize(
        ("kwargs", "expected_err"),
        [
            (
                {"task_id": "", "domain": TaskDomain.LEXICAL_RETRIEVAL},
                ModuleContractViolationError,
            ),
            (
                {
                    "task_id": "t1",
                    "domain": TaskDomain.LEXICAL_RETRIEVAL,
                    "epistemic_uncertainty": -0.1,
                },
                UncertaintyCeilingExceededError,
            ),
            (
                {
                    "task_id": "t1",
                    "domain": TaskDomain.LEXICAL_RETRIEVAL,
                    "epistemic_uncertainty": 1.1,
                },
                UncertaintyCeilingExceededError,
            ),
            (
                {"task_id": "t1", "domain": TaskDomain.LEXICAL_RETRIEVAL, "batch_size": 0},
                ModuleContractViolationError,
            ),
            (
                {"task_id": "t1", "domain": TaskDomain.LEXICAL_RETRIEVAL, "context_length": -5},
                ModuleContractViolationError,
            ),
            (
                {"task_id": "t1", "domain": TaskDomain.LEXICAL_RETRIEVAL, "latency_budget_ms": 0.0},
                ModuleContractViolationError,
            ),
        ],
    )
    def test_invalid_task_routing_request(self, kwargs: dict, expected_err: type) -> None:
        """Test rejection of malformed TaskRoutingRequest parameters."""
        with pytest.raises(expected_err):
            TaskRoutingRequest(**kwargs)

    def test_valid_routing_decision(self) -> None:
        """Test valid RoutingDecision record."""
        dec = RoutingDecision(
            task_id="t1",
            domain=TaskDomain.SYMBOLIC_VALIDATION,
            selected_tier=ExecutionTier.TIER_0_SYMBOLIC,
            selected_specialist_id="spec_sym",
            fallback_applied=False,
            projected_vram_bytes=0,
            projected_latency_ms=1.5,
        )
        assert dec.task_id == "t1"
        assert dec.selected_tier == ExecutionTier.TIER_0_SYMBOLIC

    @pytest.mark.parametrize(
        ("kwargs", "expected_err"),
        [
            (
                {
                    "task_id": "",
                    "domain": TaskDomain.SYMBOLIC_VALIDATION,
                    "selected_tier": ExecutionTier.TIER_0_SYMBOLIC,
                    "selected_specialist_id": "spec_sym",
                },
                ModuleContractViolationError,
            ),
            (
                {
                    "task_id": "t1",
                    "domain": TaskDomain.SYMBOLIC_VALIDATION,
                    "selected_tier": ExecutionTier.TIER_0_SYMBOLIC,
                    "selected_specialist_id": "",
                },
                ModuleContractViolationError,
            ),
            (
                {
                    "task_id": "t1",
                    "domain": TaskDomain.SYMBOLIC_VALIDATION,
                    "selected_tier": ExecutionTier.TIER_0_SYMBOLIC,
                    "selected_specialist_id": "spec_sym",
                    "projected_vram_bytes": -10,
                },
                ModuleContractViolationError,
            ),
            (
                {
                    "task_id": "t1",
                    "domain": TaskDomain.SYMBOLIC_VALIDATION,
                    "selected_tier": ExecutionTier.TIER_0_SYMBOLIC,
                    "selected_specialist_id": "spec_sym",
                    "projected_latency_ms": -1.0,
                },
                ModuleContractViolationError,
            ),
        ],
    )
    def test_invalid_routing_decision(self, kwargs: dict, expected_err: type) -> None:
        """Test rejection of invalid RoutingDecision parameters."""
        with pytest.raises(expected_err):
            RoutingDecision(**kwargs)

    def test_valid_benchmark_report(self) -> None:
        """Test valid HardwareBenchmarkReport instantiation."""
        rep = HardwareBenchmarkReport(
            timestamp_iso="2026-10-16T00:00:00Z",
            device_name=HardwareTarget.DEVICE_NAME,
            total_tasks_routed=10,
            peak_vram_bytes=1000,
            peak_vram_gb=0.001,
            zero_cuda_oom=True,
            is_verified_hardware=False,
            fallback_count=1,
            status_label=TelemetryStatus.SIMULATED.value,
            passed_safety_gate=True,
        )
        assert rep.passed_safety_gate is True
        assert rep.zero_cuda_oom is True

    @pytest.mark.parametrize(
        ("kwargs", "expected_err"),
        [
            (
                {
                    "timestamp_iso": "",
                    "device_name": "RTX 5070 Ti",
                    "total_tasks_routed": 10,
                    "peak_vram_bytes": 0,
                    "peak_vram_gb": 0.0,
                    "zero_cuda_oom": True,
                    "is_verified_hardware": False,
                    "fallback_count": 0,
                    "status_label": "SIMULATED",
                    "passed_safety_gate": True,
                },
                ModuleContractViolationError,
            ),
            (
                {
                    "timestamp_iso": "2026-10-16",
                    "device_name": "",
                    "total_tasks_routed": 10,
                    "peak_vram_bytes": 0,
                    "peak_vram_gb": 0.0,
                    "zero_cuda_oom": True,
                    "is_verified_hardware": False,
                    "fallback_count": 0,
                    "status_label": "SIMULATED",
                    "passed_safety_gate": True,
                },
                ModuleContractViolationError,
            ),
            (
                {
                    "timestamp_iso": "2026-10-16",
                    "device_name": "RTX 5070 Ti",
                    "total_tasks_routed": -1,
                    "peak_vram_bytes": 0,
                    "peak_vram_gb": 0.0,
                    "zero_cuda_oom": True,
                    "is_verified_hardware": False,
                    "fallback_count": 0,
                    "status_label": "SIMULATED",
                    "passed_safety_gate": True,
                },
                ModuleContractViolationError,
            ),
            (
                {
                    "timestamp_iso": "2026-10-16",
                    "device_name": "RTX 5070 Ti",
                    "total_tasks_routed": 1,
                    "peak_vram_bytes": -10,
                    "peak_vram_gb": 0.0,
                    "zero_cuda_oom": True,
                    "is_verified_hardware": False,
                    "fallback_count": 0,
                    "status_label": "SIMULATED",
                    "passed_safety_gate": True,
                },
                ModuleContractViolationError,
            ),
        ],
    )
    def test_invalid_benchmark_report(self, kwargs: dict, expected_err: type) -> None:
        """Test rejection of malformed BenchmarkReport fields."""
        with pytest.raises(expected_err):
            HardwareBenchmarkReport(**kwargs)


class TestTaskRouterRoutingLogic:
    """Tests routing decisions, escalations, fallbacks, and audit trails."""

    def test_default_policies_registered(self) -> None:
        """Verify default policies cover all defined task domains."""
        router = TaskRouter()
        for domain in TaskDomain:
            policy = router.get_policy(domain)
            assert policy.task_domain == domain

    def test_unregistered_domain_lookup_raises_error(self) -> None:
        """Verify attempting to lookup an unregistered policy raises TaskRoutingError."""
        router = TaskRouter()
        # Mock clearing policies
        router._policies.clear()
        with pytest.raises(TaskRoutingError, match="No routing policy registered"):
            router.get_policy(TaskDomain.SYMBOLIC_VALIDATION)

    def test_tier_0_symbolic_routing(self) -> None:
        """Tier 0 symbolic validation requires 0 VRAM and routes directly."""
        router = TaskRouter()
        req = TaskRoutingRequest(
            task_id="t_sym",
            domain=TaskDomain.SYMBOLIC_VALIDATION,
            epistemic_uncertainty=0.05,
        )
        decision = router.route(req)
        assert decision.selected_tier == ExecutionTier.TIER_0_SYMBOLIC
        assert decision.selected_specialist_id == "symbolic_unit_validator"
        assert decision.projected_vram_bytes == 0
        assert decision.fallback_applied is False
        assert decision.escalated_due_to_uncertainty is False

    def test_epistemic_uncertainty_escalation(self) -> None:
        """High epistemic uncertainty (> threshold) escalates from Tier 2 to Tier 3."""
        router = TaskRouter()
        # NLI verification threshold is 0.15; request uncertainty is 0.40
        req = TaskRoutingRequest(
            task_id="t_nli_escalate",
            domain=TaskDomain.NLI_VERIFICATION,
            epistemic_uncertainty=0.40,
        )
        decision = router.route(req)
        assert decision.selected_tier == ExecutionTier.TIER_3_DEEP
        assert decision.selected_specialist_id == "deep_multihop_nli_reasoner"
        assert decision.escalated_due_to_uncertainty is True
        assert decision.fallback_applied is False
        assert "escalated to TIER_3_DEEP" in decision.decision_rationale

    def test_force_tier_override(self) -> None:
        """Force tier option overrides default tier selection."""
        router = TaskRouter()
        req = TaskRoutingRequest(
            task_id="t_force",
            domain=TaskDomain.DENSE_EMBEDDING,
            force_tier=ExecutionTier.TIER_1_COMPACT,
        )
        decision = router.route(req)
        assert decision.selected_tier == ExecutionTier.TIER_1_COMPACT
        assert "Tier forced to TIER_1_COMPACT" in decision.decision_rationale

    def test_latency_budget_fallback(self) -> None:
        """When estimated latency exceeds latency budget, falls back to lighter tier."""
        router = TaskRouter()
        # Dense embedding estimated latency is 45.0 ms; set budget to 20.0 ms
        req = TaskRoutingRequest(
            task_id="t_latency",
            domain=TaskDomain.DENSE_EMBEDDING,
            latency_budget_ms=20.0,
        )
        decision = router.route(req)
        assert decision.selected_tier == ExecutionTier.TIER_1_COMPACT
        assert decision.selected_specialist_id == "bm25_lexical_index"
        assert decision.fallback_applied is True
        assert "exceeds budget 20.0 ms" in (decision.fallback_reason or "")

    def test_memory_pressure_graceful_degradation(self) -> None:
        """When memory pressure threatens safety ceiling, router degrades gracefully."""
        # Setup telemetry sampler near 14.0 GB (headroom only 0.5 GB, below 1.5 GB margin)
        sampler = MockHardwareTelemetrySampler(
            vram_allocated_bytes=int(14.0 * 1024 * 1024 * 1024)
        )
        engine = HardwareTelemetryEngine(sampler=sampler)
        governor = HeadroomBudgetGovernor(telemetry_engine=engine)
        router = TaskRouter(governor=governor)

        # Cross-paper synthesis requires ~4.0 GB VRAM
        req = TaskRoutingRequest(
            task_id="t_cross_degrade",
            domain=TaskDomain.CROSS_PAPER_SYNTHESIS,
            epistemic_uncertainty=0.10,
        )
        decision = router.route(req)
        assert decision.fallback_applied is True
        assert decision.selected_tier == ExecutionTier.TIER_2_MIDSIZED
        assert decision.selected_specialist_id == "scientific_nli_classifier"
        assert "Memory pressure" in (decision.fallback_reason or "")

    def test_cache_eviction_before_degradation(self) -> None:
        """Router evicts inactive models from attached LRU cache to recover headroom."""
        sampler = MockHardwareTelemetrySampler(
            vram_allocated_bytes=int(13.2 * 1024 * 1024 * 1024)
        )
        engine = HardwareTelemetryEngine(sampler=sampler)
        governor = HeadroomBudgetGovernor(telemetry_engine=engine)
        loader = MockSpecialistWeightLoader()
        cache = SpecialistLRUCache(
            governor=governor,
            loader=loader,
        )

        # Register unpinned specialist in Tier 1 GPU VRAM
        desc = SpecialistWeightDescriptor(
            specialist_id="OLD_INACTIVE_SPEC",
            parameter_count=100_000_000,
            size_bytes=int(2.0 * 1024 * 1024 * 1024),  # 2.0 GB
            tier=StorageTier.TIER1_GPU_VRAM,
            state=StagingState.ACTIVE_LOADED,
            last_accessed_iso="2026-10-15T00:00:00Z",
            is_pinned=False,
        )
        cache.register_specialist(desc)
        governor.register_allocation(desc.specialist_id, desc.size_bytes)

        router = TaskRouter(governor=governor, cache=cache)

        # Before routing, cache has 1 active specialist in GPU VRAM
        spec = cache.get_specialist("OLD_INACTIVE_SPEC")
        assert spec is not None and spec.tier == StorageTier.TIER1_GPU_VRAM

        # Route a dense embedding request (1.0 GB base VRAM)
        # Headroom was tight (14.5 - 13.2 = 1.3 GB < 1.5 GB margin). Eviction should free 2 GB.
        # Once evicted, sampler allocation drops by 2 GB
        def simulated_evict_effect() -> None:
            sampler.set_allocated_bytes(int(11.2 * 1024 * 1024 * 1024))

        # Hook eviction trigger
        original_evict = cache.evict_lru

        def hooked_evict() -> Optional[SpecialistWeightDescriptor]:
            res = original_evict()
            simulated_evict_effect()
            return res

        cache.evict_lru = hooked_evict  # type: ignore[assignment]

        req = TaskRoutingRequest(
            task_id="t_dense_cache",
            domain=TaskDomain.DENSE_EMBEDDING,
        )
        decision = router.route(req)

        # Should have successfully evicted and routed to primary tier without fallback
        spec_after = cache.get_specialist("OLD_INACTIVE_SPEC")
        assert spec_after is not None and spec_after.tier == StorageTier.TIER2_HOST_RAM
        assert decision.selected_tier == ExecutionTier.TIER_2_MIDSIZED
        assert decision.fallback_applied is False

    def test_audit_trail_and_clear(self) -> None:
        """Verify audit trail accumulates decisions and clears properly."""
        router = TaskRouter()
        req1 = TaskRoutingRequest(task_id="t1", domain=TaskDomain.SYMBOLIC_VALIDATION)
        req2 = TaskRoutingRequest(task_id="t2", domain=TaskDomain.LEXICAL_RETRIEVAL)

        router.route(req1)
        router.route(req2)

        trail = router.get_audit_trail()
        assert len(trail) == 2
        assert trail[0].task_id == "t1"
        assert trail[1].task_id == "t2"

        router.clear_audit_trail()
        assert len(router.get_audit_trail()) == 0


class TestHardwareStressProtocol:
    """Tests stress protocol execution, peak VRAM accounting, and OOM verification."""

    def test_run_stress_suite_synthetic(self) -> None:
        """Verify stress suite on default synthetic workload satisfies the <= 15 GB gate."""
        sampler = MockHardwareTelemetrySampler(
            vram_allocated_bytes=int(4.0 * 1024 * 1024 * 1024)
        )

        engine = HardwareTelemetryEngine(sampler=sampler)
        governor = HeadroomBudgetGovernor(telemetry_engine=engine)
        router = TaskRouter(governor=governor)

        protocol = HardwareStressProtocol(router=router, telemetry_engine=engine)
        report = protocol.run_stress_suite()

        assert report.total_tasks_routed > 0
        assert report.peak_vram_gb <= 15.0
        assert report.zero_cuda_oom is True
        assert report.passed_safety_gate is True
        assert report.is_verified_hardware is False
        assert report.status_label == TelemetryStatus.SIMULATED.value

    def test_run_stress_suite_custom_workload(self) -> None:
        """Verify stress suite with custom task list."""
        router = TaskRouter()
        protocol = HardwareStressProtocol(router=router)
        workload = [
            TaskRoutingRequest(
                task_id=f"custom_{i}",
                domain=TaskDomain.LEXICAL_RETRIEVAL,
                batch_size=2,
            )
            for i in range(5)
        ]
        report = protocol.run_stress_suite(workload=workload)
        assert report.total_tasks_routed == 5
        assert report.passed_safety_gate is True

    def test_stress_suite_with_fallbacks_and_oom_failures(self) -> None:
        """Verify stress protocol captures fallbacks, OOM ceiling violations, and exceptions."""
        sampler = MockHardwareTelemetrySampler(
            vram_allocated_bytes=int(14.2 * 1024 * 1024 * 1024)
        )
        engine = HardwareTelemetryEngine(sampler=sampler)
        governor = HeadroomBudgetGovernor(telemetry_engine=engine)
        router = TaskRouter(governor=governor)

        protocol = HardwareStressProtocol(router=router, telemetry_engine=engine)

        workload = [
            TaskRoutingRequest(
                task_id="fallback_trigger_task",
                domain=TaskDomain.CROSS_PAPER_SYNTHESIS,
            )
        ]
        report = protocol.run_stress_suite(workload=workload)
        assert report.fallback_count > 0

        # Simulate OOM violation (> 15.0 GB)
        sampler.set_allocated_bytes(int(15.5 * 1024 * 1024 * 1024))
        oom_workload = [
            TaskRoutingRequest(
                task_id="oom_task",
                domain=TaskDomain.SYMBOLIC_VALIDATION,
            )
        ]
        report_oom = protocol.run_stress_suite(workload=oom_workload)
        assert report_oom.zero_cuda_oom is False
        assert report_oom.passed_safety_gate is False

        # Simulate routing exception handling
        def failing_route(*args, **kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("Hardware failure during routing")

        router.route = failing_route  # type: ignore[assignment]
        report_err = protocol.run_stress_suite(workload=oom_workload)
        assert report_err.zero_cuda_oom is False
        assert report_err.passed_safety_gate is False

    def test_cache_eviction_edge_cases(self) -> None:
        """Test cache eviction when cache is None or has no unpinned candidates."""
        router = TaskRouter(cache=None)
        # Calling directly should safely return without error
        router._attempt_cache_eviction(1000)

        # Cache with only pinned models
        cache = SpecialistLRUCache()
        desc = SpecialistWeightDescriptor(
            specialist_id="PINNED_SPEC",
            parameter_count=1000,
            size_bytes=1000,
            tier=StorageTier.TIER1_GPU_VRAM,
            state=StagingState.ACTIVE_LOADED,
            is_pinned=True,
        )
        cache.register_specialist(desc)
        router_with_cache = TaskRouter(cache=cache)
        # Should attempt eviction, find no unpinned candidate (evicted is None), and break cleanly
        router_with_cache._attempt_cache_eviction(5000)

