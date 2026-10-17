"""Hardware telemetry engine and sampling adapters for Layer 9.

Adheres to DOC-SPEC-MOD-001 (Boundary I), ADR-001, ADR-005, and Issue #68:
- Sub-millisecond hardware telemetry sampling
- Distinct labeling of simulated vs verified target hardware measurements
- Pluggable telemetry sampler protocol with PyTorch CUDA and Mock implementations
- Measurement history tracking and throughput computation
"""

from __future__ import annotations

import datetime
import time
from collections import deque
from dataclasses import replace
from typing import Deque, List, Optional, Protocol

from laris.core.errors import ModuleContractViolationError
from laris.execution.schemas import (
    HardwareTarget,
    TelemetrySnapshot,
    TelemetryStatus,
)


class TelemetrySampler(Protocol):
    """Protocol for hardware telemetry measurement samplers."""

    def sample(self) -> TelemetrySnapshot:
        """Sample and return the current hardware telemetry state."""
        ...


class MockHardwareTelemetrySampler:
    """Mock telemetry sampler providing controllable synthetic metrics for unit tests."""

    def __init__(
        self,
        vram_allocated_bytes: int = 0,
        vram_reserved_bytes: int = 0,
        vram_total_bytes: int = HardwareTarget.TOTAL_VRAM_BYTES,
        vram_ceiling_bytes: int = HardwareTarget.VRAM_CEILING_BYTES,
        host_ram_used_bytes: int = 0,
        host_ram_total_bytes: int = HardwareTarget.DEFAULT_HOST_RAM_CEILING_BYTES,
        device_name: str = f"Mock {HardwareTarget.DEVICE_NAME}",
        is_simulated: bool = True,
        is_verified_hardware: bool = False,
        status_label: str = TelemetryStatus.SIMULATED.value,
        throughput_tokens_per_sec: float = 0.0,
    ) -> None:
        self.vram_allocated_bytes = vram_allocated_bytes
        self.vram_reserved_bytes = vram_reserved_bytes
        self.vram_total_bytes = vram_total_bytes
        self.vram_ceiling_bytes = vram_ceiling_bytes
        self.host_ram_used_bytes = host_ram_used_bytes
        self.host_ram_total_bytes = host_ram_total_bytes
        self.device_name = device_name
        self.is_simulated = is_simulated
        self.is_verified_hardware = is_verified_hardware
        self.status_label = status_label
        self.throughput_tokens_per_sec = throughput_tokens_per_sec

    def set_allocated_bytes(self, allocated_bytes: int) -> None:
        """Dynamically update allocated VRAM bytes."""
        if allocated_bytes < 0:
            raise ModuleContractViolationError("Allocated VRAM bytes cannot be negative.")
        self.vram_allocated_bytes = allocated_bytes

    def set_reserved_bytes(self, reserved_bytes: int) -> None:
        """Dynamically update reserved VRAM bytes."""
        if reserved_bytes < 0:
            raise ModuleContractViolationError("Reserved VRAM bytes cannot be negative.")
        self.vram_reserved_bytes = reserved_bytes

    def set_host_ram_used_bytes(self, host_ram_bytes: int) -> None:
        """Dynamically update host RAM used bytes."""
        if host_ram_bytes < 0:
            raise ModuleContractViolationError("Host RAM bytes cannot be negative.")
        self.host_ram_used_bytes = host_ram_bytes

    def sample(self) -> TelemetrySnapshot:
        """Produce an immutable snapshot from the current mock state."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        return TelemetrySnapshot(
            timestamp_iso=now_iso,
            device_name=self.device_name,
            vram_allocated_bytes=self.vram_allocated_bytes,
            vram_reserved_bytes=self.vram_reserved_bytes,
            vram_total_bytes=self.vram_total_bytes,
            vram_ceiling_bytes=self.vram_ceiling_bytes,
            host_ram_used_bytes=self.host_ram_used_bytes,
            host_ram_total_bytes=self.host_ram_total_bytes,
            sampling_latency_ms=0.0,
            throughput_tokens_per_sec=self.throughput_tokens_per_sec,
            is_simulated=self.is_simulated,
            is_verified_hardware=self.is_verified_hardware,
            status_label=self.status_label,
        )


class PyTorchCudaSampler:
    """Telemetry sampler inspecting PyTorch CUDA device metrics if available."""

    def __init__(self, fallback_sampler: Optional[TelemetrySampler] = None) -> None:
        self._fallback_sampler = fallback_sampler or MockHardwareTelemetrySampler(
            device_name="Fallback CPU / Non-CUDA",
            is_simulated=True,
            is_verified_hardware=False,
            status_label=TelemetryStatus.FALLBACK.value,
        )

    def sample(self) -> TelemetrySnapshot:
        """Sample CUDA memory if initialized; fallback safely otherwise."""
        try:
            import torch  # type: ignore[import-not-found]

            if not torch.cuda.is_available():
                return self._fallback_sampler.sample()

            device_index = torch.cuda.current_device()
            detected_name = torch.cuda.get_device_name(device_index)
            vram_allocated = int(torch.cuda.memory_allocated(device_index))
            vram_reserved = int(torch.cuda.memory_reserved(device_index))
            props = torch.cuda.get_device_properties(device_index)
            total_vram = int(props.total_memory)

            # Target hardware verification check
            is_target = "RTX 5070 Ti" in detected_name or "5070" in detected_name
            is_simulated = getattr(torch.cuda, "_is_simulated", False) is True
            is_verified = is_target and not is_simulated

            now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
            return TelemetrySnapshot(
                timestamp_iso=now_iso,
                device_name=detected_name,
                vram_allocated_bytes=vram_allocated,
                vram_reserved_bytes=vram_reserved,
                vram_total_bytes=total_vram,
                vram_ceiling_bytes=min(total_vram, HardwareTarget.VRAM_CEILING_BYTES),
                host_ram_used_bytes=0,
                host_ram_total_bytes=HardwareTarget.DEFAULT_HOST_RAM_CEILING_BYTES,
                sampling_latency_ms=0.0,
                throughput_tokens_per_sec=0.0,
                is_simulated=not is_verified,
                is_verified_hardware=is_verified,
                status_label=(
                    TelemetryStatus.MEASURED.value
                    if is_verified
                    else TelemetryStatus.UNVERIFIED_TARGET.value
                ),
            )
        except Exception:
            return self._fallback_sampler.sample()


class HardwareTelemetryEngine:
    """Telemetry engine providing sub-millisecond hardware sampling and metric history."""

    def __init__(
        self,
        sampler: Optional[TelemetrySampler] = None,
        max_history_size: int = 100,
    ) -> None:
        if max_history_size <= 0:
            raise ModuleContractViolationError("max_history_size must be strictly positive.")
        self._sampler = sampler or PyTorchCudaSampler()
        self._history: Deque[TelemetrySnapshot] = deque(maxlen=max_history_size)

    def sample(self) -> TelemetrySnapshot:
        """Sample hardware metrics with sub-millisecond latency measurement."""
        t_start = time.perf_counter()
        raw_snapshot = self._sampler.sample()
        t_end = time.perf_counter()
        sampling_latency_ms = (t_end - t_start) * 1000.0

        measured_snapshot = replace(raw_snapshot, sampling_latency_ms=sampling_latency_ms)
        self._history.append(measured_snapshot)
        return measured_snapshot

    def get_latest_snapshot(self) -> Optional[TelemetrySnapshot]:
        """Return the most recently recorded telemetry snapshot, if any."""
        if not self._history:
            return None
        return self._history[-1]

    def get_history(self) -> List[TelemetrySnapshot]:
        """Return a snapshot list of recent telemetry samples."""
        return list(self._history)

    def is_hardware_verified(self) -> bool:
        """Check whether the latest sampled metrics originate from verified target hardware."""
        latest = self.get_latest_snapshot()
        if latest is None:
            return False
        return latest.is_verified_hardware

    def record_throughput(self, tokens_processed: int, duration_seconds: float) -> float:
        """Calculate throughput in tokens per second."""
        if tokens_processed < 0:
            raise ModuleContractViolationError("tokens_processed cannot be negative.")
        if duration_seconds < 0.0:
            raise ModuleContractViolationError("duration_seconds cannot be negative.")
        if duration_seconds == 0.0:
            return 0.0
        return round(tokens_processed / duration_seconds, 2)

    def clear_history(self) -> None:
        """Clear recorded telemetry sample history."""
        self._history.clear()
