"""Selective weight staging and LRU specialist cache for Layer 9.

Adheres to DOC-SPEC-MOD-001 (Boundary I), ADR-001, ADR-005, and Issue #69:
- 3-tier weight staging hierarchy: GPU VRAM (Tier 1) <-> Host RAM (Tier 2) <-> NVMe SSD (Tier 3)
- Least-Recently-Used (LRU) specialist cache policy
- Automatic eviction of inactive specialists before new loads to enforce <= 14.5 GB VRAM ceiling
- Robust state transitions (COLD_STORED, WARM_PARKED, ACTIVE_LOADED, LOADING, OFFLOADING, FAILED)
- Rollback mechanisms on staging/load failures ensuring cache coherence
- Empirical telemetry collection: active parameter count, transfer duration, and transfer rates
"""

from __future__ import annotations

import datetime
import threading
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol

from laris.core.errors import (
    HardwareBudgetExceededError,
    ModuleContractViolationError,
    WeightStagingError,
)
from laris.layers.layer9_adaptive_execution.headroom_governor import (
    HeadroomBudgetGovernor,
)


class StorageTier(str, Enum):
    """The 3-tier physical memory hierarchy defined in ADR-005 and Boundary I."""

    TIER1_GPU_VRAM = "TIER1_GPU_VRAM"
    TIER2_HOST_RAM = "TIER2_HOST_RAM"
    TIER3_COLD_SSD = "TIER3_COLD_SSD"


class StagingState(str, Enum):
    """Lifecycle states of specialist weights across memory tiers."""

    COLD_STORED = "COLD_STORED"
    WARM_PARKED = "WARM_PARKED"
    ACTIVE_LOADED = "ACTIVE_LOADED"
    LOADING = "LOADING"
    OFFLOADING = "OFFLOADING"
    EVICTED = "EVICTED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class SpecialistWeightDescriptor:
    """Metadata describing a specialist model's weights and residency state."""

    specialist_id: str
    parameter_count: int
    size_bytes: int
    tier: StorageTier = StorageTier.TIER3_COLD_SSD
    state: StagingState = StagingState.COLD_STORED
    last_accessed_iso: str = ""
    access_count: int = 0
    is_pinned: bool = False

    def __post_init__(self) -> None:
        """Validate invariant contracts for weight descriptors."""
        if not self.specialist_id or not self.specialist_id.strip():
            raise ModuleContractViolationError("specialist_id cannot be empty.")
        if self.parameter_count <= 0:
            raise ModuleContractViolationError("parameter_count must be strictly positive.")
        if self.size_bytes <= 0:
            raise ModuleContractViolationError("size_bytes must be strictly positive.")
        if self.access_count < 0:
            raise ModuleContractViolationError("access_count cannot be negative.")


@dataclass(frozen=True)
class WeightTransferMetrics:
    """Telemetry recorded during inter-tier weight staging operations."""

    specialist_id: str
    source_tier: StorageTier
    target_tier: StorageTier
    bytes_transferred: int
    transfer_duration_ms: float
    transfer_rate_gb_per_sec: float

    def __post_init__(self) -> None:
        """Validate transfer metric invariants."""
        if not self.specialist_id or not self.specialist_id.strip():
            raise ModuleContractViolationError("specialist_id cannot be empty.")
        if self.bytes_transferred < 0:
            raise ModuleContractViolationError("bytes_transferred cannot be negative.")
        if self.transfer_duration_ms < 0.0:
            raise ModuleContractViolationError("transfer_duration_ms cannot be negative.")
        if self.transfer_rate_gb_per_sec < 0.0:
            raise ModuleContractViolationError("transfer_rate_gb_per_sec cannot be negative.")


class SpecialistWeightLoader(Protocol):
    """Protocol for staging and offloading weight tensors between physical tiers."""

    def load_weights(
        self,
        descriptor: SpecialistWeightDescriptor,
        target_tier: StorageTier,
    ) -> float:
        """Stage weights to target tier and return elapsed duration in milliseconds."""
        ...

    def offload_weights(
        self,
        descriptor: SpecialistWeightDescriptor,
        target_tier: StorageTier,
    ) -> float:
        """Offload weights to target tier and return elapsed duration in milliseconds."""
        ...


class MockSpecialistWeightLoader:
    """Simulated weight loader modeling realistic PCIe Gen4 and NVMe bandwidths."""

    def __init__(
        self,
        bandwidth_pcie_gbps: float = 25.0,
        bandwidth_ssd_gbps: float = 3.5,
        fail_on_specialist_id: Optional[str] = None,
    ) -> None:
        if bandwidth_pcie_gbps <= 0.0:
            raise ModuleContractViolationError("bandwidth_pcie_gbps must be strictly positive.")
        if bandwidth_ssd_gbps <= 0.0:
            raise ModuleContractViolationError("bandwidth_ssd_gbps must be strictly positive.")
        self.bandwidth_pcie_bytes_per_sec = bandwidth_pcie_gbps * (1024.0**3)
        self.bandwidth_ssd_bytes_per_sec = bandwidth_ssd_gbps * (1024.0**3)
        self.fail_on_specialist_id = fail_on_specialist_id

    def load_weights(
        self,
        descriptor: SpecialistWeightDescriptor,
        target_tier: StorageTier,
    ) -> float:
        """Simulate loading weights with realistic transfer duration."""
        if self.fail_on_specialist_id == descriptor.specialist_id:
            raise RuntimeError(f"Simulated hardware failure staging {descriptor.specialist_id}")

        if target_tier == StorageTier.TIER1_GPU_VRAM:
            # Transfer over PCIe bus from host RAM (or SSD if cold)
            rate = self.bandwidth_pcie_bytes_per_sec
        else:
            rate = self.bandwidth_ssd_bytes_per_sec

        duration_sec = descriptor.size_bytes / rate
        return max(0.1, duration_sec * 1000.0)

    def offload_weights(
        self,
        descriptor: SpecialistWeightDescriptor,
        target_tier: StorageTier,
    ) -> float:
        """Simulate offloading weights with realistic transfer duration."""
        if self.fail_on_specialist_id == descriptor.specialist_id:
            raise RuntimeError(f"Simulated hardware failure offloading {descriptor.specialist_id}")

        rate = self.bandwidth_pcie_bytes_per_sec
        duration_sec = descriptor.size_bytes / rate
        return max(0.1, duration_sec * 1000.0)


class SpecialistLRUCache:
    """Least-Recently-Used specialist weight staging cache and resource governor."""

    def __init__(
        self,
        governor: Optional[HeadroomBudgetGovernor] = None,
        loader: Optional[SpecialistWeightLoader] = None,
        bandwidth_pcie_gbps: float = 25.0,
    ) -> None:
        self._governor = governor or HeadroomBudgetGovernor()
        self._loader = loader or MockSpecialistWeightLoader(bandwidth_pcie_gbps=bandwidth_pcie_gbps)
        self._registry: Dict[str, SpecialistWeightDescriptor] = {}
        self._transfer_history: List[WeightTransferMetrics] = []
        self._lock = threading.Lock()
        self._hits: int = 0
        self._misses: int = 0
        self._evictions: int = 0

    @property
    def hits(self) -> int:
        """Number of cache hits where requested specialist was already in VRAM."""
        return self._hits

    @property
    def misses(self) -> int:
        """Number of cache misses requiring staging from RAM or SSD."""
        return self._misses

    @property
    def evictions(self) -> int:
        """Number of evictions performed to make VRAM headroom."""
        return self._evictions

    @property
    def hit_rate(self) -> float:
        """Ratio of cache hits over total access requests."""
        total = self._hits + self._misses
        if total == 0:
            return 0.0
        return round(self._hits / total, 4)

    @property
    def active_params_count(self) -> int:
        """Sum of model parameters actively loaded in GPU VRAM (Tier 1)."""
        with self._lock:
            return sum(
                d.parameter_count
                for d in self._registry.values()
                if d.state == StagingState.ACTIVE_LOADED
            )

    @property
    def total_system_params(self) -> int:
        """Sum of all specialist parameters registered across all storage tiers."""
        with self._lock:
            return sum(d.parameter_count for d in self._registry.values())

    def register_specialist(self, descriptor: SpecialistWeightDescriptor) -> None:
        """Register a specialist model in the staging cache directory."""
        with self._lock:
            if descriptor.specialist_id in self._registry:
                raise ModuleContractViolationError(
                    f"Specialist '{descriptor.specialist_id}' is already registered."
                )
            self._registry[descriptor.specialist_id] = descriptor

    def get_specialist(self, specialist_id: str) -> Optional[SpecialistWeightDescriptor]:
        """Retrieve specialist descriptor without modifying LRU state."""
        with self._lock:
            return self._registry.get(specialist_id)

    def pin_specialist(self, specialist_id: str) -> SpecialistWeightDescriptor:
        """Pin a specialist in VRAM so it cannot be automatically evicted."""
        with self._lock:
            if specialist_id not in self._registry:
                raise ModuleContractViolationError(f"Specialist '{specialist_id}' not found.")
            desc = self._registry[specialist_id]
            updated = replace(desc, is_pinned=True)
            self._registry[specialist_id] = updated
            return updated

    def unpin_specialist(self, specialist_id: str) -> SpecialistWeightDescriptor:
        """Unpin a specialist, allowing LRU eviction when memory pressure occurs."""
        with self._lock:
            if specialist_id not in self._registry:
                raise ModuleContractViolationError(f"Specialist '{specialist_id}' not found.")
            desc = self._registry[specialist_id]
            updated = replace(desc, is_pinned=False)
            self._registry[specialist_id] = updated
            return updated

    def request_specialist(self, specialist_id: str) -> SpecialistWeightDescriptor:
        """Request specialist model weights, dynamically loading to VRAM via LRU policy."""
        with self._lock:
            if specialist_id not in self._registry:
                raise ModuleContractViolationError(
                    f"Specialist '{specialist_id}' is not registered in the cache."
                )

            descriptor = self._registry[specialist_id]
            now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

            # Cache HIT: Already resident in GPU VRAM
            if descriptor.state == StagingState.ACTIVE_LOADED:
                self._hits += 1
                updated = replace(
                    descriptor,
                    last_accessed_iso=now_iso,
                    access_count=descriptor.access_count + 1,
                )
                self._registry[specialist_id] = updated
                return updated

            # Cache MISS: Needs staging from RAM or SSD
            self._misses += 1
            required_vram = descriptor.size_bytes
            effective_ceiling = self._governor.vram_ceiling_bytes

            # Evict LRU models until sufficient VRAM headroom is available
            current_vram = self._governor.get_total_registered_allocation()
            while (current_vram + required_vram) > effective_ceiling:
                evicted_desc = self._find_and_evict_lru_candidate(exclude_id=specialist_id)
                if evicted_desc is None:
                    allocated_gb = (current_vram + required_vram) / (1024.0**3)
                    ceiling_gb = effective_ceiling / (1024.0**3)
                    raise HardwareBudgetExceededError(
                        f"Cannot stage specialist '{specialist_id}' ({required_vram / 1024**3:.2f}"
                        f" GB): required allocation {allocated_gb:.2f} GB exceeds ceiling "
                        f"{ceiling_gb:.2f} GB and no evictable models remain in VRAM."
                    )
                current_vram = self._governor.get_total_registered_allocation()

            # Execute weight staging with failure rollback guard
            previous_state = descriptor.state
            previous_tier = descriptor.tier

            # Staging state transition
            self._registry[specialist_id] = replace(descriptor, state=StagingState.LOADING)

            try:
                duration_ms = self._loader.load_weights(
                    descriptor, StorageTier.TIER1_GPU_VRAM
                )
                self._governor.register_allocation(specialist_id, descriptor.size_bytes)

                rate_gbps = (
                    (descriptor.size_bytes / (1024.0**3)) / (duration_ms / 1000.0)
                    if duration_ms > 0
                    else 0.0
                )
                metric = WeightTransferMetrics(
                    specialist_id=specialist_id,
                    source_tier=previous_tier,
                    target_tier=StorageTier.TIER1_GPU_VRAM,
                    bytes_transferred=descriptor.size_bytes,
                    transfer_duration_ms=round(duration_ms, 2),
                    transfer_rate_gb_per_sec=round(rate_gbps, 2),
                )
                self._transfer_history.append(metric)

                staged = replace(
                    descriptor,
                    tier=StorageTier.TIER1_GPU_VRAM,
                    state=StagingState.ACTIVE_LOADED,
                    last_accessed_iso=now_iso,
                    access_count=descriptor.access_count + 1,
                )
                self._registry[specialist_id] = staged
                return staged

            except Exception as exc:
                # Rollback on failure
                self._registry[specialist_id] = replace(
                    descriptor,
                    tier=previous_tier,
                    state=previous_state,
                )
                self._governor.release_allocation(specialist_id)
                raise WeightStagingError(
                    f"Failed to stage specialist '{specialist_id}': {exc}"
                ) from exc

    def offload_specialist(
        self,
        specialist_id: str,
        target_tier: StorageTier = StorageTier.TIER2_HOST_RAM,
    ) -> SpecialistWeightDescriptor:
        """Offload an active specialist from VRAM to Host RAM or Cold SSD."""
        with self._lock:
            if specialist_id not in self._registry:
                raise ModuleContractViolationError(f"Specialist '{specialist_id}' not found.")

            descriptor = self._registry[specialist_id]
            if descriptor.tier == target_tier:
                return descriptor

            # Offloading only moves down the hierarchy: VRAM -> RAM/SSD, or RAM -> SSD
            if descriptor.tier == StorageTier.TIER3_COLD_SSD:
                return descriptor

            previous_tier = descriptor.tier
            self._registry[specialist_id] = replace(descriptor, state=StagingState.OFFLOADING)

            duration_ms = self._loader.offload_weights(descriptor, target_tier)
            if previous_tier == StorageTier.TIER1_GPU_VRAM:
                self._governor.release_allocation(specialist_id)

            new_state = (
                StagingState.WARM_PARKED
                if target_tier == StorageTier.TIER2_HOST_RAM
                else StagingState.COLD_STORED
            )
            rate_gbps = (
                (descriptor.size_bytes / (1024.0**3)) / (duration_ms / 1000.0)
                if duration_ms > 0
                else 0.0
            )
            self._transfer_history.append(
                WeightTransferMetrics(
                    specialist_id=specialist_id,
                    source_tier=previous_tier,
                    target_tier=target_tier,
                    bytes_transferred=descriptor.size_bytes,
                    transfer_duration_ms=round(duration_ms, 2),
                    transfer_rate_gb_per_sec=round(rate_gbps, 2),
                )
            )

            offloaded = replace(
                descriptor,
                tier=target_tier,
                state=new_state,
            )
            self._registry[specialist_id] = offloaded
            return offloaded

    def evict_lru(self) -> Optional[SpecialistWeightDescriptor]:
        """Manually trigger LRU eviction of the oldest unpinned VRAM-resident specialist."""
        with self._lock:
            return self._find_and_evict_lru_candidate()

    def _find_and_evict_lru_candidate(
        self,
        exclude_id: Optional[str] = None,
    ) -> Optional[SpecialistWeightDescriptor]:
        """Internal helper to find and evict the oldest unpinned VRAM specialist."""
        candidates = [
            d
            for d in self._registry.values()
            if d.state == StagingState.ACTIVE_LOADED
            and not d.is_pinned
            and d.specialist_id != exclude_id
        ]
        if not candidates:
            return None

        # Sort by last_accessed_iso ascending (oldest access first)
        candidates.sort(key=lambda d: d.last_accessed_iso)
        candidate = candidates[0]

        # Offload candidate to Host RAM (Warm Parked)
        self._evictions += 1
        previous_tier = candidate.tier
        duration_ms = self._loader.offload_weights(candidate, StorageTier.TIER2_HOST_RAM)
        self._governor.release_allocation(candidate.specialist_id)

        rate_gbps = (
            (candidate.size_bytes / (1024.0**3)) / (duration_ms / 1000.0)
            if duration_ms > 0
            else 0.0
        )
        self._transfer_history.append(
            WeightTransferMetrics(
                specialist_id=candidate.specialist_id,
                source_tier=previous_tier,
                target_tier=StorageTier.TIER2_HOST_RAM,
                bytes_transferred=candidate.size_bytes,
                transfer_duration_ms=round(duration_ms, 2),
                transfer_rate_gb_per_sec=round(rate_gbps, 2),
            )
        )

        evicted = replace(
            candidate,
            tier=StorageTier.TIER2_HOST_RAM,
            state=StagingState.WARM_PARKED,
        )
        self._registry[candidate.specialist_id] = evicted
        return evicted

    def get_transfer_history(self) -> List[WeightTransferMetrics]:
        """Return history log of weight staging and offloading operations."""
        with self._lock:
            return list(self._transfer_history)

    def get_tier_occupancy(self, tier: StorageTier) -> Dict[str, Any]:
        """Return summary of models and total memory footprint in a specific tier."""
        with self._lock:
            models = [d for d in self._registry.values() if d.tier == tier]
            total_bytes = sum(d.size_bytes for d in models)
            total_params = sum(d.parameter_count for d in models)
            return {
                "tier": tier.value,
                "model_count": len(models),
                "total_bytes": total_bytes,
                "total_gb": round(total_bytes / (1024.0**3), 3),
                "total_params": total_params,
                "models": [d.specialist_id for d in models],
            }
