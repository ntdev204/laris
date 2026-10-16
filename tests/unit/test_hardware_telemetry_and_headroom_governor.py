"""Unit tests for Layer 9 hardware telemetry and headroom budgeting engine.

Tests compliance with DOC-SPEC-MOD-001 (Boundary I), ADR-001, ADR-005, and Issue #68:
- Telemetry snapshot schema contracts and invariant enforcement
- Telemetry engine sampling and sub-millisecond overhead measurement
- Distinction between simulated and verified hardware measurements
- Dynamic memory reservation scaling with batch size and context length
- Pre-flight headroom checks raising HardwareBudgetExceededError at the 14.5 GB ceiling
- Safe fallback triggering when headroom drops below safety margin (1.5 GB)
- Active specialist allocation registration and release lifecycle
"""

from unittest.mock import MagicMock, patch

import pytest

from laris.core.errors import HardwareBudgetExceededError, ModuleContractViolationError
from laris.layers.layer9_adaptive_execution.headroom_governor import (
    HeadroomBudgetGovernor,
)
from laris.layers.layer9_adaptive_execution.schemas import (
    HardwareTarget,
    SpecialistExecutionRequest,
    SpecialistExecutionResult,
    TelemetrySnapshot,
    TelemetryStatus,
)
from laris.layers.layer9_adaptive_execution.telemetry import (
    HardwareTelemetryEngine,
    MockHardwareTelemetrySampler,
    PyTorchCudaSampler,
)


class TestTelemetrySnapshotSchemas:
    """Test suite for TelemetrySnapshot and related execution schemas."""

    def test_valid_telemetry_snapshot_defaults(self) -> None:
        """Test constructing valid TelemetrySnapshot with default constants."""
        snapshot = TelemetrySnapshot(timestamp_iso="2026-10-16T00:00:00Z")
        assert snapshot.device_name == HardwareTarget.DEVICE_NAME
        assert snapshot.vram_allocated_bytes == 0
        assert snapshot.vram_total_bytes == HardwareTarget.TOTAL_VRAM_BYTES
        assert snapshot.vram_ceiling_bytes == HardwareTarget.VRAM_CEILING_BYTES
        assert snapshot.is_simulated is True
        assert snapshot.is_verified_hardware is False
        assert snapshot.status_label == TelemetryStatus.UNVERIFIED_TARGET.value
        assert snapshot.is_within_ceiling is True
        assert snapshot.vram_headroom_bytes == HardwareTarget.VRAM_CEILING_BYTES
        assert snapshot.vram_allocated_gb == 0.0

    def test_telemetry_snapshot_properties(self) -> None:
        """Test computed properties of TelemetrySnapshot."""
        four_gb = 4 * 1024 * 1024 * 1024
        snapshot = TelemetrySnapshot(
            timestamp_iso="2026-10-16T00:00:00Z",
            vram_allocated_bytes=four_gb,
        )
        assert snapshot.vram_allocated_gb == 4.0
        expected_headroom = HardwareTarget.VRAM_CEILING_BYTES - four_gb
        assert snapshot.vram_headroom_bytes == expected_headroom
        assert snapshot.vram_headroom_gb == round(expected_headroom / (1024.0**3), 3)
        assert snapshot.is_within_ceiling is True

    @pytest.mark.parametrize(
        ("kwargs", "expected_err"),
        [
            ({"timestamp_iso": ""}, "timestamp_iso cannot be empty"),
            ({"timestamp_iso": "T", "device_name": ""}, "device_name cannot be empty"),
            ({"timestamp_iso": "T", "vram_allocated_bytes": -1}, "vram_allocated_bytes cannot"),
            ({"timestamp_iso": "T", "vram_reserved_bytes": -1}, "vram_reserved_bytes cannot"),
            ({"timestamp_iso": "T", "vram_total_bytes": 0}, "vram_total_bytes must be strictly"),
            (
                {"timestamp_iso": "T", "vram_ceiling_bytes": 0},
                "vram_ceiling_bytes must be strictly",
            ),
            (
                {
                    "timestamp_iso": "T",
                    "vram_total_bytes": 1000,
                    "vram_ceiling_bytes": 2000,
                },
                "cannot exceed vram_total_bytes",
            ),
            ({"timestamp_iso": "T", "host_ram_used_bytes": -1}, "host_ram_used_bytes cannot"),
            (
                {"timestamp_iso": "T", "host_ram_total_bytes": 0},
                "host_ram_total_bytes must be strictly",
            ),
            ({"timestamp_iso": "T", "sampling_latency_ms": -0.1}, "sampling_latency_ms cannot"),
            (
                {"timestamp_iso": "T", "throughput_tokens_per_sec": -1.0},
                "throughput_tokens_per_sec cannot",
            ),
        ],
    )
    def test_invalid_telemetry_snapshot_raises(self, kwargs: dict, expected_err: str) -> None:
        """Test invalid TelemetrySnapshot inputs raise ModuleContractViolationError."""
        with pytest.raises(ModuleContractViolationError, match=expected_err):
            TelemetrySnapshot(**kwargs)

    def test_specialist_execution_request_validation(self) -> None:
        """Test SpecialistExecutionRequest contract validation."""
        req = SpecialistExecutionRequest(
            specialist_id="SPEC-NLI-001",
            batch_size=4,
            context_length=1024,
            estimated_base_vram_bytes=2 * 1024 * 1024 * 1024,
            activation_bytes_per_token=2048,
        )
        assert req.specialist_id == "SPEC-NLI-001"
        assert req.batch_size == 4
        assert req.context_length == 1024

        with pytest.raises(ModuleContractViolationError, match="specialist_id cannot be empty"):
            SpecialistExecutionRequest(specialist_id="   ")

        with pytest.raises(ModuleContractViolationError, match="batch_size must be strictly"):
            SpecialistExecutionRequest(specialist_id="SPEC-01", batch_size=0)

        with pytest.raises(ModuleContractViolationError, match="context_length must be strictly"):
            SpecialistExecutionRequest(specialist_id="SPEC-01", context_length=-5)

        with pytest.raises(
            ModuleContractViolationError, match="estimated_base_vram_bytes cannot be negative"
        ):
            SpecialistExecutionRequest(specialist_id="SPEC-01", estimated_base_vram_bytes=-100)

        with pytest.raises(
            ModuleContractViolationError, match="activation_bytes_per_token cannot be negative"
        ):
            SpecialistExecutionRequest(specialist_id="SPEC-01", activation_bytes_per_token=-1)

    def test_specialist_execution_result_validation(self) -> None:
        """Test SpecialistExecutionResult contract validation."""
        result = SpecialistExecutionResult(
            specialist_id="SPEC-NLI-001",
            output_tensor_batch={"prediction": "entailment"},
            fallback_triggered=False,
            execution_latency_ms=12.5,
        )
        assert result.specialist_id == "SPEC-NLI-001"
        assert result.execution_latency_ms == 12.5

        with pytest.raises(ModuleContractViolationError, match="specialist_id cannot be empty"):
            SpecialistExecutionResult(specialist_id="")

        with pytest.raises(
            ModuleContractViolationError, match="execution_latency_ms cannot be negative"
        ):
            SpecialistExecutionResult(specialist_id="SPEC-01", execution_latency_ms=-1.0)


class TestHardwareTelemetryEngine:
    """Test suite for HardwareTelemetryEngine and hardware samplers."""

    def test_mock_sampler_behavior_and_updates(self) -> None:
        """Test MockHardwareTelemetrySampler mutations and contract enforcement."""
        sampler = MockHardwareTelemetrySampler()
        snapshot = sampler.sample()
        assert snapshot.is_simulated is True
        assert snapshot.is_verified_hardware is False
        assert snapshot.status_label == TelemetryStatus.SIMULATED.value

        sampler.set_allocated_bytes(2 * 1024 * 1024 * 1024)
        sampler.set_reserved_bytes(3 * 1024 * 1024 * 1024)
        sampler.set_host_ram_used_bytes(8 * 1024 * 1024 * 1024)

        updated = sampler.sample()
        assert updated.vram_allocated_bytes == 2 * 1024 * 1024 * 1024
        assert updated.vram_reserved_bytes == 3 * 1024 * 1024 * 1024
        assert updated.host_ram_used_bytes == 8 * 1024 * 1024 * 1024

        with pytest.raises(
            ModuleContractViolationError, match="Allocated VRAM bytes cannot be negative"
        ):
            sampler.set_allocated_bytes(-1)

        with pytest.raises(
            ModuleContractViolationError, match="Reserved VRAM bytes cannot be negative"
        ):
            sampler.set_reserved_bytes(-1)

        with pytest.raises(ModuleContractViolationError, match="Host RAM bytes cannot be negative"):
            sampler.set_host_ram_used_bytes(-1)

    def test_pytorch_cuda_sampler_safe_fallback(self) -> None:
        """Test PyTorchCudaSampler safely falls back when non-target/mock device."""
        sampler = PyTorchCudaSampler()
        snapshot = sampler.sample()
        # Even if running on a dev system without target RTX 5070 Ti, must label unverified
        assert isinstance(snapshot, TelemetrySnapshot)
        assert snapshot.vram_total_bytes > 0
        if not snapshot.is_verified_hardware:
            assert snapshot.status_label in (
                TelemetryStatus.UNVERIFIED_TARGET.value,
                TelemetryStatus.FALLBACK.value,
                TelemetryStatus.SIMULATED.value,
            )

    def test_pytorch_cuda_sampler_with_mocked_cuda_target(self) -> None:
        """Test PyTorchCudaSampler when running on target RTX 5070 Ti hardware."""
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.current_device.return_value = 0
        mock_torch.cuda.get_device_name.return_value = "NVIDIA GeForce RTX 5070 Ti"
        mock_torch.cuda.memory_allocated.return_value = 4 * 1024 * 1024 * 1024
        mock_torch.cuda.memory_reserved.return_value = 5 * 1024 * 1024 * 1024
        mock_props = MagicMock()
        mock_props.total_memory = HardwareTarget.TOTAL_VRAM_BYTES
        mock_torch.cuda.get_device_properties.return_value = mock_props

        with patch.dict("sys.modules", {"torch": mock_torch}):
            sampler = PyTorchCudaSampler()
            snapshot = sampler.sample()
            assert snapshot.device_name == "NVIDIA GeForce RTX 5070 Ti"
            assert snapshot.is_verified_hardware is True
            assert snapshot.is_simulated is False
            assert snapshot.status_label == TelemetryStatus.MEASURED.value
            assert snapshot.vram_allocated_bytes == 4 * 1024 * 1024 * 1024

    def test_pytorch_cuda_sampler_with_mocked_cuda_nontarget(self) -> None:
        """Test PyTorchCudaSampler when running on non-target CUDA device."""
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.current_device.return_value = 0
        mock_torch.cuda.get_device_name.return_value = "Tesla T4"
        mock_torch.cuda.memory_allocated.return_value = 1024 * 1024
        mock_torch.cuda.memory_reserved.return_value = 2 * 1024 * 1024
        mock_props = MagicMock()
        mock_props.total_memory = 8 * 1024 * 1024 * 1024
        mock_torch.cuda.get_device_properties.return_value = mock_props

        with patch.dict("sys.modules", {"torch": mock_torch}):
            sampler = PyTorchCudaSampler()
            snapshot = sampler.sample()
            assert snapshot.device_name == "Tesla T4"
            assert snapshot.is_verified_hardware is False
            assert snapshot.is_simulated is True
            assert snapshot.status_label == TelemetryStatus.UNVERIFIED_TARGET.value

    def test_pytorch_cuda_sampler_when_cuda_not_available(self) -> None:
        """Test PyTorchCudaSampler falls back when CUDA is not available."""
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = False

        with patch.dict("sys.modules", {"torch": mock_torch}):
            sampler = PyTorchCudaSampler()
            snapshot = sampler.sample()
            assert snapshot.is_simulated is True
            assert snapshot.status_label == TelemetryStatus.FALLBACK.value

    def test_pytorch_cuda_sampler_exception_handling(self) -> None:
        """Test PyTorchCudaSampler catches runtime errors and safely falls back."""
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.side_effect = RuntimeError("CUDA driver failure")

        with patch.dict("sys.modules", {"torch": mock_torch}):
            sampler = PyTorchCudaSampler()
            snapshot = sampler.sample()
            assert snapshot.is_simulated is True
            assert snapshot.status_label == TelemetryStatus.FALLBACK.value

    def test_telemetry_engine_submillisecond_sampling(self) -> None:
        """Test that HardwareTelemetryEngine samples with sub-millisecond overhead."""
        sampler = MockHardwareTelemetrySampler()
        engine = HardwareTelemetryEngine(sampler=sampler, max_history_size=50)

        snapshot = engine.sample()
        assert snapshot.sampling_latency_ms >= 0.0
        # Sub-millisecond overhead test under normal conditions (< 10.0 ms test ceiling for CI)
        assert snapshot.sampling_latency_ms < 10.0

        latest = engine.get_latest_snapshot()
        assert latest is not None
        assert latest.timestamp_iso == snapshot.timestamp_iso
        assert engine.is_hardware_verified() is False

    def test_telemetry_engine_history_bounded(self) -> None:
        """Test that telemetry history buffer respects max_history_size limit."""
        sampler = MockHardwareTelemetrySampler()
        engine = HardwareTelemetryEngine(sampler=sampler, max_history_size=3)
        assert engine.get_latest_snapshot() is None
        assert engine.is_hardware_verified() is False

        for i in range(5):
            sampler.set_allocated_bytes(i * 1000)
            engine.sample()

        history = engine.get_history()
        assert len(history) == 3
        assert history[-1].vram_allocated_bytes == 4000
        assert history[0].vram_allocated_bytes == 2000

        engine.clear_history()
        assert len(engine.get_history()) == 0

    def test_telemetry_engine_invalid_history_size_raises(self) -> None:
        """Test non-positive history size raises error."""
        with pytest.raises(ModuleContractViolationError, match="max_history_size must be strictly"):
            HardwareTelemetryEngine(max_history_size=0)

    def test_telemetry_engine_throughput_calculation(self) -> None:
        """Test token throughput calculation."""
        engine = HardwareTelemetryEngine(sampler=MockHardwareTelemetrySampler())
        throughput = engine.record_throughput(tokens_processed=5000, duration_seconds=2.5)
        assert throughput == 2000.0

        assert engine.record_throughput(tokens_processed=100, duration_seconds=0.0) == 0.0

        with pytest.raises(
            ModuleContractViolationError, match="tokens_processed cannot be negative"
        ):
            engine.record_throughput(tokens_processed=-1, duration_seconds=1.0)

        with pytest.raises(
            ModuleContractViolationError, match="duration_seconds cannot be negative"
        ):
            engine.record_throughput(tokens_processed=10, duration_seconds=-0.5)


class TestHeadroomBudgetGovernor:
    """Test suite for HeadroomBudgetGovernor and memory safety enforcement."""

    def test_governor_init_validation(self) -> None:
        """Test validation during HeadroomBudgetGovernor initialization."""
        gov = HeadroomBudgetGovernor()
        assert gov.vram_ceiling_bytes == HardwareTarget.VRAM_CEILING_BYTES
        assert gov.vram_safety_margin_bytes == HardwareTarget.SAFETY_RESERVE_BYTES

        with pytest.raises(
            ModuleContractViolationError, match="vram_ceiling_bytes must be strictly positive"
        ):
            HeadroomBudgetGovernor(vram_ceiling_bytes=0)

        with pytest.raises(
            ModuleContractViolationError, match="vram_safety_margin_bytes cannot be negative"
        ):
            HeadroomBudgetGovernor(vram_safety_margin_bytes=-1)

        with pytest.raises(
            ModuleContractViolationError,
            match="vram_safety_margin_bytes must be strictly less than vram_ceiling_bytes",
        ):
            HeadroomBudgetGovernor(vram_ceiling_bytes=1000, vram_safety_margin_bytes=1000)

        with pytest.raises(
            ModuleContractViolationError, match="host_ram_ceiling_bytes must be strictly positive"
        ):
            HeadroomBudgetGovernor(host_ram_ceiling_bytes=0)

    def test_dynamic_memory_reservation_scaling(self) -> None:
        """Test dynamic memory reservation scaling with batch size and context length."""
        gov = HeadroomBudgetGovernor()

        # Batch 1, context 512, 1024 bytes per token
        req1 = SpecialistExecutionRequest(
            specialist_id="SPEC-1",
            batch_size=1,
            context_length=512,
            estimated_base_vram_bytes=1_000_000_000,
            activation_bytes_per_token=1024,
        )
        assert gov.project_required_vram(req1) == 1_000_000_000 + (1 * 512 * 1024)

        # Batch 8, context 2048, 2048 bytes per token
        req2 = SpecialistExecutionRequest(
            specialist_id="SPEC-2",
            batch_size=8,
            context_length=2048,
            estimated_base_vram_bytes=2_000_000_000,
            activation_bytes_per_token=2048,
        )
        expected_activation = 8 * 2048 * 2048
        assert gov.project_required_vram(req2) == 2_000_000_000 + expected_activation

    def test_pre_flight_check_within_budget(self) -> None:
        """Test pre-flight check succeeds when within the 14.5 GB ceiling."""
        sampler = MockHardwareTelemetrySampler(vram_allocated_bytes=4 * 1024 * 1024 * 1024)
        engine = HardwareTelemetryEngine(sampler=sampler)
        gov = HeadroomBudgetGovernor(telemetry_engine=engine)

        req = SpecialistExecutionRequest(
            specialist_id="SPEC-ENCODER",
            batch_size=2,
            context_length=512,
            estimated_base_vram_bytes=2 * 1024 * 1024 * 1024,
        )

        snapshot = gov.pre_flight_check(req)
        assert snapshot.vram_allocated_bytes == 4 * 1024 * 1024 * 1024

    def test_pre_flight_check_exceeding_ceiling_raises(self) -> None:
        """Test pre-flight check raises HardwareBudgetExceededError when ceiling is breached."""
        # 14.0 GB currently allocated
        alloc_bytes = int(14.0 * 1024 * 1024 * 1024)
        sampler = MockHardwareTelemetrySampler(vram_allocated_bytes=alloc_bytes)
        engine = HardwareTelemetryEngine(sampler=sampler)
        gov = HeadroomBudgetGovernor(telemetry_engine=engine)

        # Request requires 1.0 GB -> total 15.0 GB > 14.5 GB ceiling
        req = SpecialistExecutionRequest(
            specialist_id="SPEC-HEAVY-LLM",
            batch_size=4,
            context_length=2048,
            estimated_base_vram_bytes=int(1.0 * 1024 * 1024 * 1024),
        )

        with pytest.raises(
            HardwareBudgetExceededError,
            match="exceeds hard ceiling of 14.50 GB",
        ):
            gov.pre_flight_check(req)

    def test_evaluate_safe_fallback(self) -> None:
        """Test safe fallback evaluation against safety headroom margin (1.5 GB)."""
        sampler = MockHardwareTelemetrySampler()
        engine = HardwareTelemetryEngine(sampler=sampler)
        gov = HeadroomBudgetGovernor(telemetry_engine=engine)

        req = SpecialistExecutionRequest(
            specialist_id="SPEC-1",
            batch_size=1,
            context_length=512,
            estimated_base_vram_bytes=100_000_000,
        )

        # Baseline: 2.0 GB allocated -> plenty of headroom (> 1.5 GB margin)
        sampler.set_allocated_bytes(2 * 1024 * 1024 * 1024)
        assert gov.evaluate_safe_fallback(req) is False

        # Headroom tight: 13.5 GB allocated -> 1.0 GB headroom left (< 1.5 GB margin)
        sampler.set_allocated_bytes(int(13.5 * 1024 * 1024 * 1024))
        assert gov.evaluate_safe_fallback(req) is True

        # Headroom 1.8 GB left, but request demands 500 MB -> leaves 1.3 GB (< 1.5 GB margin)
        sampler.set_allocated_bytes(HardwareTarget.VRAM_CEILING_BYTES - int(1.8 * 1024**3))
        heavy_req = SpecialistExecutionRequest(
            specialist_id="SPEC-HEAVY",
            estimated_base_vram_bytes=int(500 * 1024 * 1024),
        )
        assert gov.evaluate_safe_fallback(heavy_req) is True

    def test_active_allocations_lifecycle(self) -> None:
        """Test registering and releasing active specialist memory allocations."""
        gov = HeadroomBudgetGovernor()
        assert gov.get_total_registered_allocation() == 0
        assert len(gov.get_active_allocations()) == 0

        # Register specialist 1: 4 GB
        alloc1 = 4 * 1024 * 1024 * 1024
        gov.register_allocation("SPEC-1", alloc1)
        assert gov.get_total_registered_allocation() == alloc1
        assert gov.get_active_allocations() == {"SPEC-1": alloc1}

        # Register specialist 2: 6 GB -> total 10 GB
        alloc2 = 6 * 1024 * 1024 * 1024
        gov.register_allocation("SPEC-2", alloc2)
        assert gov.get_total_registered_allocation() == alloc1 + alloc2

        # Re-registering specialist 1 with updated size
        alloc1_updated = 5 * 1024 * 1024 * 1024
        gov.register_allocation("SPEC-1", alloc1_updated)
        assert gov.get_total_registered_allocation() == alloc1_updated + alloc2

        # Exceeding ceiling on registration raises HardwareBudgetExceededError
        with pytest.raises(
            HardwareBudgetExceededError,
            match="Total registered allocation .* exceeds ceiling",
        ):
            gov.register_allocation("SPEC-3", 5 * 1024 * 1024 * 1024)

        # Release specialist 2
        released = gov.release_allocation("SPEC-2")
        assert released == alloc2
        assert gov.get_total_registered_allocation() == alloc1_updated

        # Release non-existent specialist
        assert gov.release_allocation("SPEC-UNKNOWN") == 0

        # Contract violations on inputs
        with pytest.raises(ModuleContractViolationError, match="specialist_id cannot be empty"):
            gov.register_allocation("  ", 100)

        with pytest.raises(
            ModuleContractViolationError, match="allocated_bytes cannot be negative"
        ):
            gov.register_allocation("SPEC-1", -10)
