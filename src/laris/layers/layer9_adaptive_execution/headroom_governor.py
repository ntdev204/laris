"""Headroom budgeting governor and safety enforcement for Layer 9.

Adheres to DOC-SPEC-MOD-001 (Boundary I), ADR-001, ADR-005, and Issue #68:
- RTX 5070 Ti allocation safety threshold (<= 14.5 GB hard ceiling)
- Dynamic memory reservation scaling based on batch size and context window length
- HardwareBudgetExceededError pre-flight enforcement preventing OOM conditions
- Safe fallback evaluation when headroom drops below safety margin
"""

from __future__ import annotations

import threading
from typing import Dict, Optional

from laris.core.errors import HardwareBudgetExceededError, ModuleContractViolationError
from laris.layers.layer9_adaptive_execution.schemas import (
    HardwareTarget,
    SpecialistExecutionRequest,
    TelemetrySnapshot,
)
from laris.layers.layer9_adaptive_execution.telemetry import HardwareTelemetryEngine


class HeadroomBudgetGovernor:
    """Governor enforcing memory headroom safety thresholds on local hardware."""

    def __init__(
        self,
        telemetry_engine: Optional[HardwareTelemetryEngine] = None,
        vram_ceiling_bytes: int = HardwareTarget.VRAM_CEILING_BYTES,
        vram_safety_margin_bytes: int = HardwareTarget.SAFETY_RESERVE_BYTES,
        host_ram_ceiling_bytes: int = HardwareTarget.DEFAULT_HOST_RAM_CEILING_BYTES,
    ) -> None:
        if vram_ceiling_bytes <= 0:
            raise ModuleContractViolationError("vram_ceiling_bytes must be strictly positive.")
        if vram_safety_margin_bytes < 0:
            raise ModuleContractViolationError("vram_safety_margin_bytes cannot be negative.")
        if vram_safety_margin_bytes >= vram_ceiling_bytes:
            raise ModuleContractViolationError(
                "vram_safety_margin_bytes must be strictly less than vram_ceiling_bytes."
            )
        if host_ram_ceiling_bytes <= 0:
            raise ModuleContractViolationError("host_ram_ceiling_bytes must be strictly positive.")

        self._telemetry_engine = telemetry_engine or HardwareTelemetryEngine()
        self._vram_ceiling_bytes = vram_ceiling_bytes
        self._vram_safety_margin_bytes = vram_safety_margin_bytes
        self._host_ram_ceiling_bytes = host_ram_ceiling_bytes
        self._active_allocations: Dict[str, int] = {}
        self._lock = threading.Lock()

    @property
    def vram_ceiling_bytes(self) -> int:
        """Configured hard VRAM allocation ceiling in bytes."""
        return self._vram_ceiling_bytes

    @property
    def vram_safety_margin_bytes(self) -> int:
        """Configured safety headroom buffer margin in bytes."""
        return self._vram_safety_margin_bytes

    def project_required_vram(self, request: SpecialistExecutionRequest) -> int:
        """Dynamically compute projected VRAM reservation for execution request."""
        base_vram = request.estimated_base_vram_bytes
        dynamic_activation_vram = (
            request.batch_size * request.context_length * request.activation_bytes_per_token
        )
        return base_vram + dynamic_activation_vram

    def pre_flight_check(
        self,
        request: SpecialistExecutionRequest,
        current_snapshot: Optional[TelemetrySnapshot] = None,
    ) -> TelemetrySnapshot:
        """Verify request fits within the 14.5 GB safety ceiling before dispatch."""
        snapshot = current_snapshot or self._telemetry_engine.sample()
        projected_additional = self.project_required_vram(request)
        total_projected = snapshot.vram_allocated_bytes + projected_additional

        if total_projected > self._vram_ceiling_bytes:
            allocated_gb = total_projected / (1024.0**3)
            ceiling_gb = self._vram_ceiling_bytes / (1024.0**3)
            raise HardwareBudgetExceededError(
                f"Projected VRAM allocation {allocated_gb:.2f} GB exceeds hard ceiling "
                f"of {ceiling_gb:.2f} GB on {snapshot.device_name}."
            )

        return snapshot

    def evaluate_safe_fallback(
        self,
        request: SpecialistExecutionRequest,
        current_snapshot: Optional[TelemetrySnapshot] = None,
    ) -> bool:
        """Determine whether available headroom requires engaging safe fallback mode."""
        snapshot = current_snapshot or self._telemetry_engine.sample()
        current_headroom = max(0, self._vram_ceiling_bytes - snapshot.vram_allocated_bytes)

        if current_headroom < self._vram_safety_margin_bytes:
            return True

        projected_additional = self.project_required_vram(request)
        projected_headroom = current_headroom - projected_additional
        return projected_headroom < self._vram_safety_margin_bytes

    def register_allocation(self, specialist_id: str, allocated_bytes: int) -> None:
        """Register active VRAM allocation for a loaded specialist model."""
        if not specialist_id or not specialist_id.strip():
            raise ModuleContractViolationError("specialist_id cannot be empty.")
        if allocated_bytes < 0:
            raise ModuleContractViolationError("allocated_bytes cannot be negative.")

        with self._lock:
            current_sum = sum(self._active_allocations.values())
            previous_alloc = self._active_allocations.get(specialist_id, 0)
            new_sum = current_sum - previous_alloc + allocated_bytes

            if new_sum > self._vram_ceiling_bytes:
                new_sum_gb = new_sum / (1024.0**3)
                ceiling_gb = self._vram_ceiling_bytes / (1024.0**3)
                raise HardwareBudgetExceededError(
                    f"Total registered allocation {new_sum_gb:.2f} GB exceeds ceiling "
                    f"of {ceiling_gb:.2f} GB."
                )

            self._active_allocations[specialist_id] = allocated_bytes

    def release_allocation(self, specialist_id: str) -> int:
        """Release registered VRAM allocation for an offloaded specialist model."""
        with self._lock:
            return self._active_allocations.pop(specialist_id, 0)

    def get_total_registered_allocation(self) -> int:
        """Return total active allocated bytes across all registered specialists."""
        with self._lock:
            return sum(self._active_allocations.values())

    def get_active_allocations(self) -> Dict[str, int]:
        """Return a copy of current specialist allocation records."""
        with self._lock:
            return dict(self._active_allocations)
