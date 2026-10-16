"""Integration tests for Layer 9 routing audit and target hardware benchmark report.

Tests compliance with DOC-SPEC-MOD-001 (Boundary I), ADR-001, ADR-005, ADR-006, and Issue #102:
- End-to-end route selection accuracy across all 6 scientific task domains
- Multi-threaded concurrent routing requests with thread-safe audit trail logging
- Epistemic uncertainty escalation and latency SLA degradation enforcement
- Graceful quality degradation cascade under progressive physical memory pressure
- Target hardware stress benchmark protocol validating peak VRAM <= 15.0 GB and zero CUDA OOM
- Strict distinction between simulated telemetry (SIMULATED) and verified hardware (MEASURED)
"""

from __future__ import annotations

import concurrent.futures
from dataclasses import asdict

from laris.execution.headroom_governor import (
    HeadroomBudgetGovernor,
)
from laris.execution.schemas import (
    TelemetryStatus,
)
from laris.execution.task_router import (
    ExecutionTier,
    HardwareStressProtocol,
    TaskDomain,
    TaskRouter,
    TaskRoutingRequest,
)
from laris.execution.telemetry import (
    HardwareTelemetryEngine,
    MockHardwareTelemetrySampler,
)


class TestRoutingDecisionAudit:
    """Integration tests for routing decisions, escalation policies, and audit trails."""

    def test_cross_domain_route_selection(self) -> None:
        """Verify accurate primary routing and complete audit trails across all domains."""
        router = TaskRouter()

        domain_tier_map = {
            TaskDomain.SYMBOLIC_VALIDATION: ExecutionTier.TIER_0_SYMBOLIC,
            TaskDomain.LEXICAL_RETRIEVAL: ExecutionTier.TIER_1_COMPACT,
            TaskDomain.DENSE_EMBEDDING: ExecutionTier.TIER_2_MIDSIZED,
            TaskDomain.NLI_VERIFICATION: ExecutionTier.TIER_2_MIDSIZED,
            TaskDomain.CROSS_PAPER_SYNTHESIS: ExecutionTier.TIER_3_DEEP,
            TaskDomain.GAP_DISCOVERY: ExecutionTier.TIER_3_DEEP,
        }

        for domain, expected_tier in domain_tier_map.items():
            req = TaskRoutingRequest(
                task_id=f"test_{domain.value.lower()}",
                domain=domain,
                epistemic_uncertainty=0.05,
            )
            decision = router.route(req)
            assert decision.selected_tier == expected_tier
            assert decision.fallback_applied is False
            assert decision.task_id == req.task_id

        # Audit trail must contain exactly one record per dispatched task
        trail = router.get_audit_trail()
        assert len(trail) == len(domain_tier_map)
        for i, (domain, expected_tier) in enumerate(domain_tier_map.items()):
            record = trail[i]
            assert record.domain == domain
            assert record.selected_tier == expected_tier
            assert record.telemetry_snapshot is not None

    def test_concurrent_multithreaded_routing_audit(self) -> None:
        """Verify thread-safety of router state and audit trail under high concurrency."""
        router = TaskRouter()
        total_requests = 50
        num_workers = 8

        def dispatch_route(idx: int) -> None:
            domain = list(TaskDomain)[idx % len(TaskDomain)]
            req = TaskRoutingRequest(
                task_id=f"concurrent_task_{idx:03d}",
                domain=domain,
                batch_size=1 + (idx % 4),
            )
            router.route(req)

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = [executor.submit(dispatch_route, i) for i in range(total_requests)]
            for future in concurrent.futures.as_completed(futures):
                future.result()

        trail = router.get_audit_trail()
        assert len(trail) == total_requests
        seen_ids = {r.task_id for r in trail}
        assert len(seen_ids) == total_requests

    def test_epistemic_uncertainty_escalation_audit(self) -> None:
        """Verify epistemic escalation logging and state across uncertainty gradients."""
        router = TaskRouter()
        uncertainty_levels = [0.05, 0.10, 0.15, 0.25, 0.60]

        for u in uncertainty_levels:
            req = TaskRoutingRequest(
                task_id=f"nli_u_{int(u*100)}",
                domain=TaskDomain.NLI_VERIFICATION,
                epistemic_uncertainty=u,
            )
            decision = router.route(req)

            # Threshold for NLI is 0.15: > 0.15 escalates to Tier 3 Deep
            if u > 0.15:
                assert decision.selected_tier == ExecutionTier.TIER_3_DEEP
                assert decision.escalated_due_to_uncertainty is True
                assert "escalated to TIER_3_DEEP" in decision.decision_rationale
            else:
                assert decision.selected_tier == ExecutionTier.TIER_2_MIDSIZED
                assert decision.escalated_due_to_uncertainty is False

    def test_latency_budget_downgrade_audit(self) -> None:
        """Verify latency budget constraints downgrade models and document justification."""
        router = TaskRouter()
        req = TaskRoutingRequest(
            task_id="tight_sla_task",
            domain=TaskDomain.CROSS_PAPER_SYNTHESIS,
            latency_budget_ms=100.0,  # Cross-paper synthesis takes ~300 ms
        )
        decision = router.route(req)
        assert decision.fallback_applied is True
        assert decision.selected_tier == ExecutionTier.TIER_2_MIDSIZED
        assert "exceeds budget 100.0 ms" in (decision.fallback_reason or "")


class TestGracefulDegradationUnderMemoryPressure:
    """Tests degradation cascades, OOM prevention, and headroom safety buffers."""

    def test_progressive_memory_pressure_cascade(self) -> None:
        """Verify progressive fallback cascades as memory pressure tightens towards ceiling."""
        sampler = MockHardwareTelemetrySampler()
        engine = HardwareTelemetryEngine(sampler=sampler)
        governor = HeadroomBudgetGovernor(telemetry_engine=engine)
        router = TaskRouter(governor=governor)

        # Level 1: Low memory (4.0 GB) -> Dense embedding and cross-paper both execute normally
        sampler.set_allocated_bytes(int(4.0 * 1024**3))
        d1 = router.route(
            TaskRoutingRequest(task_id="p1", domain=TaskDomain.DENSE_EMBEDDING)
        )
        assert d1.selected_tier == ExecutionTier.TIER_2_MIDSIZED
        assert d1.fallback_applied is False

        # Level 2: Moderate memory (11.0 GB) -> Headroom = 3.5 GB
        # Dense embedding (1.0 GB) fits; Cross-paper (4.0 GB) would exceed ceiling -> degrades!
        sampler.set_allocated_bytes(int(11.0 * 1024**3))
        d2 = router.route(
            TaskRoutingRequest(task_id="p2", domain=TaskDomain.CROSS_PAPER_SYNTHESIS)
        )
        assert d2.fallback_applied is True
        assert d2.selected_tier == ExecutionTier.TIER_2_MIDSIZED

        # Level 3: Critical memory (13.8 GB) -> Headroom = 0.7 GB (< 1.5 GB safety reserve)
        # Even Dense embedding (1.0 GB) cannot fit safely -> degrades to Tier 1 BM25!
        sampler.set_allocated_bytes(int(13.8 * 1024**3))
        d3 = router.route(
            TaskRoutingRequest(task_id="p3", domain=TaskDomain.DENSE_EMBEDDING)
        )
        assert d3.fallback_applied is True
        assert d3.selected_tier == ExecutionTier.TIER_1_COMPACT
        assert d3.selected_specialist_id == "bm25_lexical_index"
        assert "Memory pressure" in (d3.fallback_reason or "")

    def test_zero_cuda_oom_under_pressure(self) -> None:
        """Verify zero CUDA OOM exceptions occur even under rapid high-load requests."""
        sampler = MockHardwareTelemetrySampler(
            vram_allocated_bytes=int(14.0 * 1024**3)
        )
        engine = HardwareTelemetryEngine(sampler=sampler)
        governor = HeadroomBudgetGovernor(telemetry_engine=engine)
        router = TaskRouter(governor=governor)

        oom_occurred = False
        for i in range(25):
            try:
                router.route(
                    TaskRoutingRequest(
                        task_id=f"stress_{i}",
                        domain=TaskDomain.CROSS_PAPER_SYNTHESIS,
                        batch_size=4,
                        context_length=2048,
                    )
                )
            except Exception:
                oom_occurred = True

        assert oom_occurred is False
        trail = router.get_audit_trail()
        assert len(trail) == 25
        assert all(t.fallback_applied for t in trail)


class TestTargetHardwareBenchmarkProtocol:
    """Tests target hardware benchmark reporting, safety gate verification, and serialization."""

    def test_hardware_stress_suite_execution(self) -> None:
        """Run standard stress protocol and assert M8 exit gate compliance."""
        sampler = MockHardwareTelemetrySampler(
            vram_allocated_bytes=int(6.0 * 1024**3)
        )
        engine = HardwareTelemetryEngine(sampler=sampler)
        governor = HeadroomBudgetGovernor(telemetry_engine=engine)
        router = TaskRouter(governor=governor)

        protocol = HardwareStressProtocol(router=router, telemetry_engine=engine)
        report = protocol.run_stress_suite()

        # Exit criteria verification:
        # Peak VRAM <= 15.0 GB, zero CUDA OOM, and safety gate passed
        assert report.total_tasks_routed > 0
        assert report.peak_vram_gb <= 15.0
        assert report.zero_cuda_oom is True
        assert report.passed_safety_gate is True

    def test_distinction_between_simulated_and_verified_hardware(self) -> None:
        """Ensure benchmark report strictly distinguishes simulation from measured hardware."""
        # Simulated profile
        sim_sampler = MockHardwareTelemetrySampler()
        sim_engine = HardwareTelemetryEngine(sampler=sim_sampler)
        sim_router = TaskRouter(governor=HeadroomBudgetGovernor(telemetry_engine=sim_engine))
        sim_protocol = HardwareStressProtocol(router=sim_router, telemetry_engine=sim_engine)

        sim_report = sim_protocol.run_stress_suite()
        assert sim_report.is_verified_hardware is False
        assert sim_report.status_label == TelemetryStatus.SIMULATED.value

        # Target verified hardware profile
        verified_sampler = MockHardwareTelemetrySampler(
            is_verified_hardware=True,
            status_label=TelemetryStatus.MEASURED.value,
        )
        ver_engine = HardwareTelemetryEngine(sampler=verified_sampler)
        ver_router = TaskRouter(governor=HeadroomBudgetGovernor(telemetry_engine=ver_engine))
        ver_protocol = HardwareStressProtocol(router=ver_router, telemetry_engine=ver_engine)

        ver_report = ver_protocol.run_stress_suite()
        assert ver_report.is_verified_hardware is True
        assert ver_report.status_label == TelemetryStatus.MEASURED.value

    def test_benchmark_report_serialization(self) -> None:
        """Verify benchmark report data serialization into standard dictionaries."""
        router = TaskRouter()
        protocol = HardwareStressProtocol(router=router)
        report = protocol.run_stress_suite()

        report_dict = asdict(report)
        assert "timestamp_iso" in report_dict
        assert "peak_vram_gb" in report_dict
        assert "zero_cuda_oom" in report_dict
        assert "is_verified_hardware" in report_dict
        assert "passed_safety_gate" in report_dict
        assert report_dict["passed_safety_gate"] is True
