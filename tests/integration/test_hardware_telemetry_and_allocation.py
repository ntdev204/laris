"""Integration and stress tests for Layer 9 telemetry adapter and headroom allocation.

Tests compliance with DOC-SPEC-MOD-001 (Boundary I), ADR-001, ADR-005, and Issue #100:
- Multi-model sequential allocation and cumulative VRAM headroom tracking
- Exact 14.5 GB ceiling threshold boundary conditions and OOM prevention
- Dynamic workload scaling across varying batch sizes and context lengths
- Telemetry adapter fail-safe behavior during driver errors or missing GPU metrics
- Strict distinction between simulated and verified hardware measurements
- Concurrent multi-threaded allocation registration and release safety
- Progressive memory pressure degradation signaling before ceiling breach
"""

from __future__ import annotations

import concurrent.futures
from unittest.mock import MagicMock, patch

import pytest

from laris.core.errors import HardwareBudgetExceededError
from laris.execution.headroom_governor import (
    HeadroomBudgetGovernor,
)
from laris.execution.schemas import (
    HardwareTarget,
    SpecialistExecutionRequest,
    TelemetryStatus,
)
from laris.execution.telemetry import (
    HardwareTelemetryEngine,
    MockHardwareTelemetrySampler,
    PyTorchCudaSampler,
)


class TestMultiModelSequentialAllocation:
    """Tests multi-model sequential loading, allocation tracking, and release lifecycles."""

    def test_multi_model_allocation_and_headroom_recovery(self) -> None:
        """Test sequential specialist allocation, ceiling breach, and headroom recovery."""
        governor = HeadroomBudgetGovernor()

        # Specialist 1: Sentence Encoder (2.0 GB)
        enc_bytes = 2 * 1024 * 1024 * 1024
        governor.register_allocation("SPEC-SENTENCE-ENCODER", enc_bytes)
        assert governor.get_total_registered_allocation() == enc_bytes

        # Specialist 2: Scientific NLI Specialist (4.0 GB) -> total 6.0 GB
        nli_bytes = 4 * 1024 * 1024 * 1024
        governor.register_allocation("SPEC-SCIENTIFIC-NLI", nli_bytes)
        assert governor.get_total_registered_allocation() == 6 * 1024**3

        # Specialist 3: Discourse Entity Resolver (3.5 GB) -> total 9.5 GB
        disc_bytes = int(3.5 * 1024**3)
        governor.register_allocation("SPEC-DISCOURSE-EXTRACTOR", disc_bytes)
        assert governor.get_total_registered_allocation() == int(9.5 * 1024**3)

        # Specialist 4: Cross-Paper Synthesis LLM (4.0 GB) -> total 13.5 GB
        synth_bytes = 4 * 1024 * 1024 * 1024
        governor.register_allocation("SPEC-SYNTHESIS-LLM", synth_bytes)
        assert governor.get_total_registered_allocation() == int(13.5 * 1024**3)

        # Specialist 5: Hypothesis Generator (2.0 GB) -> total 15.5 GB > 14.5 GB ceiling!
        hypo_bytes = 2 * 1024 * 1024 * 1024
        with pytest.raises(
            HardwareBudgetExceededError,
            match="Total registered allocation 15.50 GB exceeds ceiling of 14.50 GB",
        ):
            governor.register_allocation("SPEC-HYPOTHESIS-GEN", hypo_bytes)

        # Allocation total must remain at 13.5 GB after rejected registration
        assert governor.get_total_registered_allocation() == int(13.5 * 1024**3)

        # Offload NLI Specialist (release 4.0 GB) -> total drops to 9.5 GB
        released = governor.release_allocation("SPEC-SCIENTIFIC-NLI")
        assert released == nli_bytes
        assert governor.get_total_registered_allocation() == int(9.5 * 1024**3)

        # Now Hypothesis Generator (2.0 GB) can be successfully allocated -> total 11.5 GB
        governor.register_allocation("SPEC-HYPOTHESIS-GEN", hypo_bytes)
        assert governor.get_total_registered_allocation() == int(11.5 * 1024**3)

    def test_exact_14_point_5_gb_ceiling_boundary(self) -> None:
        """Test exact boundary at 14.5 GB ceiling (15,569,256,448 bytes)."""
        ceiling = HardwareTarget.VRAM_CEILING_BYTES
        governor = HeadroomBudgetGovernor(vram_ceiling_bytes=ceiling)

        # Allocate exactly ceiling - 1024 bytes (should succeed)
        governor.register_allocation("SPEC-NEAR-LIMIT", ceiling - 1024)
        assert governor.get_total_registered_allocation() == ceiling - 1024

        # Registering 1025 bytes more exceeds ceiling by 1 byte (should fail)
        with pytest.raises(HardwareBudgetExceededError):
            governor.register_allocation("SPEC-OVERFLOW", 1025)

        # Registering exactly 1024 bytes reaches exact ceiling (should succeed)
        governor.register_allocation("SPEC-EXACT-LIMIT", 1024)
        assert governor.get_total_registered_allocation() == ceiling


class TestDynamicWorkloadScalingStress:
    """Stress tests dynamic activation scaling across batch and context dimensions."""

    def test_dynamic_scaling_various_dimensions(self) -> None:
        """Test memory projection scaling with small, medium, and extreme workloads."""
        sampler = MockHardwareTelemetrySampler(vram_allocated_bytes=10 * 1024**3)
        engine = HardwareTelemetryEngine(sampler=sampler)
        governor = HeadroomBudgetGovernor(telemetry_engine=engine)

        # Small batch & context: batch=1, context=512 -> passes
        small_req = SpecialistExecutionRequest(
            specialist_id="SPEC-SMALL",
            batch_size=1,
            context_length=512,
            estimated_base_vram_bytes=1 * 1024**3,
            activation_bytes_per_token=1024,
        )
        snapshot = governor.pre_flight_check(small_req)
        assert snapshot.vram_allocated_bytes == 10 * 1024**3

        # Moderate batch & context: batch=4, context=2048 -> passes
        mod_req = SpecialistExecutionRequest(
            specialist_id="SPEC-MOD",
            batch_size=4,
            context_length=2048,
            estimated_base_vram_bytes=2 * 1024**3,
            activation_bytes_per_token=2048,
        )
        governor.pre_flight_check(mod_req)

        # Burst workload: batch=16, context=8192, base=4.5 GB -> exceeds 14.5 GB ceiling
        burst_req = SpecialistExecutionRequest(
            specialist_id="SPEC-BURST",
            batch_size=16,
            context_length=8192,
            estimated_base_vram_bytes=int(4.5 * 1024**3),
            activation_bytes_per_token=2048,
        )
        with pytest.raises(HardwareBudgetExceededError, match="exceeds hard ceiling of 14.50 GB"):
            governor.pre_flight_check(burst_req)


class TestTelemetryFailSafeAndHardwareLabeling:
    """Tests telemetry fail-safe degradation and explicit labeling of unverified hardware."""

    def test_driver_exception_resilient_fallback(self) -> None:
        """Test telemetry engine resilience when GPU driver raises unexpected exceptions."""
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.side_effect = RuntimeError("GPU bus lost or driver crashed")

        with patch.dict("sys.modules", {"torch": mock_torch}):
            sampler = PyTorchCudaSampler()
            engine = HardwareTelemetryEngine(sampler=sampler)

            # Sampling must not crash; must safely fall back
            snapshot = engine.sample()
            assert snapshot.is_simulated is True
            assert snapshot.is_verified_hardware is False
            assert snapshot.status_label == TelemetryStatus.FALLBACK.value

    def test_non_target_gpu_explicitly_unverified(self) -> None:
        """Test non-RTX-5070-Ti GPUs are strictly marked unverified."""
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.current_device.return_value = 0
        mock_torch.cuda.get_device_name.return_value = "NVIDIA A100-SXM4-80GB"
        mock_torch.cuda.memory_allocated.return_value = 2 * 1024**3
        mock_torch.cuda.memory_reserved.return_value = 4 * 1024**3
        mock_props = MagicMock()
        mock_props.total_memory = 80 * 1024**3
        mock_torch.cuda.get_device_properties.return_value = mock_props

        with patch.dict("sys.modules", {"torch": mock_torch}):
            sampler = PyTorchCudaSampler()
            engine = HardwareTelemetryEngine(sampler=sampler)
            snapshot = engine.sample()

            assert snapshot.device_name == "NVIDIA A100-SXM4-80GB"
            assert snapshot.is_verified_hardware is False
            assert snapshot.is_simulated is True
            assert snapshot.status_label == TelemetryStatus.UNVERIFIED_TARGET.value
            assert engine.is_hardware_verified() is False

    def test_rapid_burst_sampling_overhead(self) -> None:
        """Test that rapid consecutive telemetry sampling maintains sub-millisecond overhead."""
        sampler = MockHardwareTelemetrySampler()
        engine = HardwareTelemetryEngine(sampler=sampler, max_history_size=100)

        # 300 rapid samples
        for _ in range(300):
            engine.sample()

        history = engine.get_history()
        assert len(history) == 100
        avg_latency = sum(s.sampling_latency_ms for s in history) / len(history)
        # Average latency must remain under 1.0 millisecond for lightweight sampling
        assert avg_latency < 1.0


class TestConcurrentAllocationSafety:
    """Tests thread-safety and race-condition immunity for allocation registry."""

    def test_multithreaded_allocation_and_release(self) -> None:
        """Test concurrent threads registering and releasing memory allocations."""
        governor = HeadroomBudgetGovernor(
            vram_ceiling_bytes=int(14.5 * 1024**3),
        )
        spec_size = 500 * 1024 * 1024  # 500 MB per specialist

        def worker_cycle(thread_id: int) -> None:
            spec_id = f"SPEC-THREAD-{thread_id}"
            governor.register_allocation(spec_id, spec_size)
            allocations = governor.get_active_allocations()
            assert spec_id in allocations
            released = governor.release_allocation(spec_id)
            assert released == spec_size

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(worker_cycle, i) for i in range(20)]
            for future in concurrent.futures.as_completed(futures):
                future.result()

        assert governor.get_total_registered_allocation() == 0


class TestProgressiveDegradationSignaling:
    """Tests progressive safe fallback signals before reaching the allocation ceiling."""

    def test_progressive_fallback_triggering(self) -> None:
        """Test evaluate_safe_fallback behavior across progressive memory levels."""
        sampler = MockHardwareTelemetrySampler()
        engine = HardwareTelemetryEngine(sampler=sampler)
        governor = HeadroomBudgetGovernor(
            telemetry_engine=engine,
            vram_ceiling_bytes=HardwareTarget.VRAM_CEILING_BYTES,
            vram_safety_margin_bytes=HardwareTarget.SAFETY_RESERVE_BYTES,  # 1.5 GB
        )

        req = SpecialistExecutionRequest(
            specialist_id="SPEC-TEST",
            batch_size=1,
            context_length=512,
            estimated_base_vram_bytes=500 * 1024 * 1024,  # 500 MB
        )

        # Level 1: Low pressure (6 GB allocated) -> Fallback False
        sampler.set_allocated_bytes(6 * 1024**3)
        assert governor.evaluate_safe_fallback(req) is False

        # Level 2: Moderate pressure (12 GB allocated -> 2.5 GB headroom left)
        # 2.5 GB headroom - 500 MB request = 2.0 GB > 1.5 GB margin -> Fallback False
        sampler.set_allocated_bytes(12 * 1024**3)
        assert governor.evaluate_safe_fallback(req) is False

        # Level 3: High pressure (12.8 GB allocated -> 1.7 GB headroom left)
        # 1.7 GB headroom - 500 MB request = 1.2 GB < 1.5 GB margin -> Fallback True!
        sampler.set_allocated_bytes(int(12.8 * 1024**3))
        assert governor.evaluate_safe_fallback(req) is True

        # Level 4: Critical pressure (13.5 GB allocated -> 1.0 GB headroom < 1.5 GB margin)
        sampler.set_allocated_bytes(int(13.5 * 1024**3))
        assert governor.evaluate_safe_fallback(req) is True
