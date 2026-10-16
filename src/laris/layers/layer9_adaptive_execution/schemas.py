"""Data contracts and schemas for Layer 9 Adaptive Model Execution.

Adheres to DOC-SPEC-MOD-001 (Boundary I), ADR-001, ADR-005, and Issue #68:
- Real-time hardware telemetry contracts for VRAM, host RAM, latency, and throughput
- Distinction between simulated/mock telemetry and verified target hardware
- RTX 5070 Ti allocation safety threshold (<= 14.5 GB hard ceiling out of 16 GB)
- Specialist execution request and result schemas
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from laris.core.errors import ModuleContractViolationError


class HardwareTarget:
    """Canonical target hardware constants for LARIS execution environments."""

    DEVICE_NAME: str = "NVIDIA GeForce RTX 5070 Ti"
    TOTAL_VRAM_BYTES: int = 16 * 1024 * 1024 * 1024  # 16.0 GB (17,179,869,184 bytes)
    VRAM_CEILING_BYTES: int = int(14.5 * 1024 * 1024 * 1024)  # 14.5 GB (15,569,256,448 bytes)
    SAFETY_RESERVE_BYTES: int = int(1.5 * 1024 * 1024 * 1024)  # 1.5 GB safety buffer
    DEFAULT_HOST_RAM_CEILING_BYTES: int = 32 * 1024 * 1024 * 1024  # 32.0 GB default host RAM


class TelemetryStatus(str, Enum):
    """Status label indicating the source and verification state of hardware telemetry."""

    MEASURED = "MEASURED"
    SIMULATED = "SIMULATED"
    UNVERIFIED_TARGET = "UNVERIFIED_TARGET"
    FALLBACK = "FALLBACK"


@dataclass(frozen=True)
class TelemetrySnapshot:
    """Immutable snapshot of GPU VRAM, host RAM, and latency metrics."""

    timestamp_iso: str
    device_name: str = HardwareTarget.DEVICE_NAME
    vram_allocated_bytes: int = 0
    vram_reserved_bytes: int = 0
    vram_total_bytes: int = HardwareTarget.TOTAL_VRAM_BYTES
    vram_ceiling_bytes: int = HardwareTarget.VRAM_CEILING_BYTES
    host_ram_used_bytes: int = 0
    host_ram_total_bytes: int = HardwareTarget.DEFAULT_HOST_RAM_CEILING_BYTES
    sampling_latency_ms: float = 0.0
    throughput_tokens_per_sec: float = 0.0
    is_simulated: bool = True
    is_verified_hardware: bool = False
    status_label: str = TelemetryStatus.UNVERIFIED_TARGET.value

    def __post_init__(self) -> None:
        """Validate invariant contracts for telemetry metrics."""
        if not self.timestamp_iso:
            raise ModuleContractViolationError("TelemetrySnapshot timestamp_iso cannot be empty.")
        if not self.device_name:
            raise ModuleContractViolationError("TelemetrySnapshot device_name cannot be empty.")
        if self.vram_allocated_bytes < 0:
            raise ModuleContractViolationError("vram_allocated_bytes cannot be negative.")
        if self.vram_reserved_bytes < 0:
            raise ModuleContractViolationError("vram_reserved_bytes cannot be negative.")
        if self.vram_total_bytes <= 0:
            raise ModuleContractViolationError("vram_total_bytes must be strictly positive.")
        if self.vram_ceiling_bytes <= 0:
            raise ModuleContractViolationError("vram_ceiling_bytes must be strictly positive.")
        if self.vram_ceiling_bytes > self.vram_total_bytes:
            raise ModuleContractViolationError(
                f"vram_ceiling_bytes ({self.vram_ceiling_bytes}) cannot exceed "
                f"vram_total_bytes ({self.vram_total_bytes})."
            )
        if self.host_ram_used_bytes < 0:
            raise ModuleContractViolationError("host_ram_used_bytes cannot be negative.")
        if self.host_ram_total_bytes <= 0:
            raise ModuleContractViolationError("host_ram_total_bytes must be strictly positive.")
        if self.sampling_latency_ms < 0.0:
            raise ModuleContractViolationError("sampling_latency_ms cannot be negative.")
        if self.throughput_tokens_per_sec < 0.0:
            raise ModuleContractViolationError("throughput_tokens_per_sec cannot be negative.")

    @property
    def vram_headroom_bytes(self) -> int:
        """Remaining usable VRAM headroom before reaching the 14.5 GB safety ceiling."""
        return max(0, self.vram_ceiling_bytes - self.vram_allocated_bytes)

    @property
    def vram_allocated_gb(self) -> float:
        """Allocated VRAM represented in gigabytes (GiB)."""
        return round(self.vram_allocated_bytes / (1024.0**3), 3)

    @property
    def vram_headroom_gb(self) -> float:
        """Headroom VRAM represented in gigabytes (GiB)."""
        return round(self.vram_headroom_bytes / (1024.0**3), 3)

    @property
    def is_within_ceiling(self) -> bool:
        """Whether current VRAM allocation is within the safety ceiling."""
        return self.vram_allocated_bytes <= self.vram_ceiling_bytes


@dataclass(frozen=True)
class SpecialistExecutionRequest:
    """Execution dispatch request for a specialized model or heuristic component."""

    specialist_id: str
    input_tensor_batch: Any = None
    batch_size: int = 1
    context_length: int = 512
    estimated_base_vram_bytes: int = 0
    activation_bytes_per_token: int = 1024

    def __post_init__(self) -> None:
        """Validate specialist execution request parameters."""
        if not self.specialist_id or not self.specialist_id.strip():
            raise ModuleContractViolationError(
                "SpecialistExecutionRequest specialist_id cannot be empty."
            )
        if self.batch_size <= 0:
            raise ModuleContractViolationError("batch_size must be strictly positive.")
        if self.context_length <= 0:
            raise ModuleContractViolationError("context_length must be strictly positive.")
        if self.estimated_base_vram_bytes < 0:
            raise ModuleContractViolationError("estimated_base_vram_bytes cannot be negative.")
        if self.activation_bytes_per_token < 0:
            raise ModuleContractViolationError("activation_bytes_per_token cannot be negative.")


@dataclass(frozen=True)
class SpecialistExecutionResult:
    """Result of an executed specialist computation along with runtime telemetry."""

    specialist_id: str
    output_tensor_batch: Any = None
    telemetry: TelemetrySnapshot = field(
        default_factory=lambda: TelemetrySnapshot(timestamp_iso="1970-01-01T00:00:00Z")
    )
    fallback_triggered: bool = False
    fallback_reason: Optional[str] = None
    execution_latency_ms: float = 0.0

    def __post_init__(self) -> None:
        """Validate specialist execution result attributes."""
        if not self.specialist_id or not self.specialist_id.strip():
            raise ModuleContractViolationError(
                "SpecialistExecutionResult specialist_id cannot be empty."
            )
        if self.execution_latency_ms < 0.0:
            raise ModuleContractViolationError("execution_latency_ms cannot be negative.")
