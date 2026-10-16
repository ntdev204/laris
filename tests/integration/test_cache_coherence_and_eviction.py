"""Integration and stress tests for Layer 9 specialist cache coherence and eviction.

Tests compliance with DOC-SPEC-MOD-001 (Boundary I), ADR-001, ADR-005, and Issue #101:
- Deterministic LRU ordering and timestamp coherence across repeated accesses
- Cascading multi-model evictions under extreme single-model memory staging requests
- Staging failure recovery ensuring rollback integrity and zero ghost memory leaks
- High-concurrency multithreaded staging and eviction without deadlock or budget overruns
- Complete 3-tier staging lifecycle: Cold SSD (Tier 3) -> Host RAM (Tier 2) -> GPU VRAM (Tier 1)
"""

from __future__ import annotations

import concurrent.futures
import time

import pytest

from laris.core.errors import WeightStagingError
from laris.execution.headroom_governor import (
    HeadroomBudgetGovernor,
)
from laris.execution.weight_staging import (
    MockSpecialistWeightLoader,
    SpecialistLRUCache,
    SpecialistWeightDescriptor,
    StagingState,
    StorageTier,
)


class TestLRUOrderingAndTimestampCoherence:
    """Tests LRU access timestamp updating, ordering, and eviction correctness."""

    def test_strict_lru_eviction_sequence(self) -> None:
        """Test that models are evicted strictly according to oldest access timestamps."""
        # 9.0 GB ceiling with 1.0 GB margin -> 8.0 GB usable for models
        governor = HeadroomBudgetGovernor(
            vram_ceiling_bytes=int(9.0 * 1024**3),
            vram_safety_margin_bytes=int(1.0 * 1024**3),
        )
        cache = SpecialistLRUCache(governor=governor)

        # 4 models of 3.0 GB each (M1, M2, M3, M4)
        m1 = SpecialistWeightDescriptor("MODEL-A", 1_000_000_000, 3 * 1024**3)
        m2 = SpecialistWeightDescriptor("MODEL-B", 1_000_000_000, 3 * 1024**3)
        m3 = SpecialistWeightDescriptor("MODEL-C", 1_000_000_000, 3 * 1024**3)
        m4 = SpecialistWeightDescriptor("MODEL-D", 1_000_000_000, 3 * 1024**3)

        for m in (m1, m2, m3, m4):
            cache.register_specialist(m)

        # Step 1: Load MODEL-A (3 GB)
        cache.request_specialist("MODEL-A")
        time.sleep(0.01)

        # Step 2: Load MODEL-B (3 GB -> 6 GB total in VRAM)
        cache.request_specialist("MODEL-B")
        time.sleep(0.01)

        # Step 3: Access MODEL-A again! Now MODEL-A is newer than MODEL-B
        cache.request_specialist("MODEL-A")
        time.sleep(0.01)

        # Step 4: Load MODEL-C (3 GB). Total needed: 6 + 3 = 9 GB == ceiling.
        # But VRAM has only 6 GB allocated. 6 + 3 = 9 GB <= 9 GB ceiling!
        # Both A, B, C can fit (total 9 GB).
        cache.request_specialist("MODEL-C")
        assert cache.evictions == 0

        # Step 5: Load MODEL-D (3 GB). Total would be 9 + 3 = 12 GB > 9 GB.
        # Who is oldest? MODEL-B was accessed at Step 2; MODEL-A was refreshed at Step 3;
        # MODEL-C was accessed at Step 4.
        # MODEL-B MUST BE EVICTED FIRST!
        cache.request_specialist("MODEL-D")
        assert cache.evictions == 1

        desc_b = cache.get_specialist("MODEL-B")
        desc_a = cache.get_specialist("MODEL-A")
        desc_c = cache.get_specialist("MODEL-C")
        desc_d = cache.get_specialist("MODEL-D")

        assert desc_b is not None and desc_b.state == StagingState.WARM_PARKED
        assert desc_a is not None and desc_a.state == StagingState.ACTIVE_LOADED
        assert desc_c is not None and desc_c.state == StagingState.ACTIVE_LOADED
        assert desc_d is not None and desc_d.state == StagingState.ACTIVE_LOADED


class TestCascadingMultiModelEviction:
    """Tests multi-model cascading eviction when a large specialist is staged."""

    def test_cascading_eviction_under_large_request(self) -> None:
        """Test evicting multiple resident models in cascade to fit a single large model."""
        # 14.5 GB ceiling
        governor = HeadroomBudgetGovernor(
            vram_ceiling_bytes=int(14.5 * 1024**3),
            vram_safety_margin_bytes=int(1.5 * 1024**3),
        )
        cache = SpecialistLRUCache(governor=governor)

        # 4 small specialists of 3.0 GB each = 12.0 GB
        for i in range(1, 5):
            cache.register_specialist(
                SpecialistWeightDescriptor(
                    f"SMALL-{i}",
                    1_500_000_000,
                    3 * 1024**3,
                )
            )
            cache.request_specialist(f"SMALL-{i}")
            time.sleep(0.005)

        assert cache.get_tier_occupancy(StorageTier.TIER1_GPU_VRAM)["model_count"] == 4
        assert governor.get_total_registered_allocation() == 12 * 1024**3

        # Register large synthesis LLM (7.0 GB).
        # To stage 7.0 GB, current 12.0 GB + 7.0 GB = 19.0 GB > 14.5 GB ceiling.
        # To clear space:
        # Evict SMALL-1 (releases 3 GB -> 9 GB left). 9 + 7 = 16 GB > 14.5 GB. Still exceeds!
        # Evict SMALL-2 (releases 3 GB -> 6 GB left). 6 + 7 = 13 GB <= 14.5 GB. Fits!
        # Result: 2 models evicted in cascade!
        large_llm = SpecialistWeightDescriptor("SYNTHESIS-7B", 7_000_000_000, 7 * 1024**3)
        cache.register_specialist(large_llm)

        cache.request_specialist("SYNTHESIS-7B")
        assert cache.evictions == 2

        assert cache.get_specialist("SMALL-1").state == StagingState.WARM_PARKED  # type: ignore[union-attr]
        assert cache.get_specialist("SMALL-2").state == StagingState.WARM_PARKED  # type: ignore[union-attr]
        assert cache.get_specialist("SMALL-3").state == StagingState.ACTIVE_LOADED  # type: ignore[union-attr]
        assert cache.get_specialist("SMALL-4").state == StagingState.ACTIVE_LOADED  # type: ignore[union-attr]
        assert cache.get_specialist("SYNTHESIS-7B").state == StagingState.ACTIVE_LOADED  # type: ignore[union-attr]

        # Total VRAM registered in governor: 3 + 3 + 7 = 13 GB <= 14.5 GB
        assert governor.get_total_registered_allocation() == 13 * 1024**3


class TestStagingFailureRollbackAndCoherence:
    """Tests failure recovery, rollback integrity, and prevention of memory leaks."""

    def test_staging_failure_after_cascading_eviction(self) -> None:
        """Test that failed staging preserves evicted states and does not leak allocations."""
        loader = MockSpecialistWeightLoader(fail_on_specialist_id="DEFECTIVE-MODEL")
        governor = HeadroomBudgetGovernor(vram_ceiling_bytes=int(10.0 * 1024**3))
        cache = SpecialistLRUCache(governor=governor, loader=loader)

        # Stage MODEL-1 (4 GB) and MODEL-2 (4 GB) -> total 8 GB
        m1 = SpecialistWeightDescriptor("MODEL-1", 1_000_000_000, 4 * 1024**3)
        m2 = SpecialistWeightDescriptor("MODEL-2", 1_000_000_000, 4 * 1024**3)
        cache.register_specialist(m1)
        cache.register_specialist(m2)
        cache.request_specialist("MODEL-1")
        time.sleep(0.005)
        cache.request_specialist("MODEL-2")

        # DEFECTIVE-MODEL requires 5 GB (would trigger eviction of MODEL-1), but fails to load
        defective = SpecialistWeightDescriptor("DEFECTIVE-MODEL", 2_000_000_000, 5 * 1024**3)
        cache.register_specialist(defective)

        with pytest.raises(
            WeightStagingError, match="Failed to stage specialist 'DEFECTIVE-MODEL'"
        ):
            cache.request_specialist("DEFECTIVE-MODEL")

        # DEFECTIVE-MODEL must remain COLD_STORED
        defective_desc = cache.get_specialist("DEFECTIVE-MODEL")
        assert defective_desc is not None
        assert defective_desc.state == StagingState.COLD_STORED

        # MODEL-1 was evicted to Host RAM safely during headroom clearing
        assert cache.get_specialist("MODEL-1").state == StagingState.WARM_PARKED  # type: ignore[union-attr]
        # MODEL-2 remains active in VRAM
        assert cache.get_specialist("MODEL-2").state == StagingState.ACTIVE_LOADED  # type: ignore[union-attr]

        # Total registered allocation in governor must equal MODEL-2 only (4 GB)
        assert governor.get_total_registered_allocation() == 4 * 1024**3


class TestHighConcurrencyStagingSafety:
    """Stress tests concurrent multithreaded staging requests."""

    def test_concurrent_specialist_staging_and_eviction(self) -> None:
        """Test multi-threaded concurrent requests do not oversubscribe VRAM or deadlock."""
        governor = HeadroomBudgetGovernor(
            vram_ceiling_bytes=int(14.5 * 1024**3),
            vram_safety_margin_bytes=int(1.5 * 1024**3),
        )
        cache = SpecialistLRUCache(governor=governor)

        # 10 models of 2.0 GB each
        for i in range(10):
            cache.register_specialist(
                SpecialistWeightDescriptor(
                    f"CONCURRENT-MODEL-{i}",
                    1_000_000_000,
                    2 * 1024**3,
                )
            )

        def worker(thread_idx: int) -> None:
            # Each thread requests a specialist
            model_id = f"CONCURRENT-MODEL-{thread_idx % 10}"
            desc = cache.request_specialist(model_id)
            assert desc.state == StagingState.ACTIVE_LOADED

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(worker, i) for i in range(40)]
            for future in concurrent.futures.as_completed(futures):
                future.result()

        # Invariant check: VRAM total allocation MUST NEVER exceed 14.5 GB ceiling!
        total_vram = governor.get_total_registered_allocation()
        assert total_vram <= int(14.5 * 1024**3)
        assert cache.hits + cache.misses == 40


class TestThreeTierStagingLifecycle:
    """Tests complete migration cycle across Tier 3 (SSD), Tier 2 (RAM), and Tier 1 (VRAM)."""

    def test_complete_3tier_migration_and_metrics(self) -> None:
        """Test moving a specialist from Cold SSD -> VRAM -> Warm RAM -> Cold SSD."""
        cache = SpecialistLRUCache()
        model_size = 2 * 1024**3  # 2 GB
        desc = SpecialistWeightDescriptor(
            specialist_id="SPEC-LIFECYCLE",
            parameter_count=1_000_000_000,
            size_bytes=model_size,
            tier=StorageTier.TIER3_COLD_SSD,
            state=StagingState.COLD_STORED,
        )
        cache.register_specialist(desc)

        # Step 1: Cold SSD -> GPU VRAM
        s1 = cache.request_specialist("SPEC-LIFECYCLE")
        assert s1.tier == StorageTier.TIER1_GPU_VRAM
        assert s1.state == StagingState.ACTIVE_LOADED

        # Step 2: GPU VRAM -> Host RAM
        s2 = cache.offload_specialist("SPEC-LIFECYCLE", StorageTier.TIER2_HOST_RAM)
        assert s2.tier == StorageTier.TIER2_HOST_RAM
        assert s2.state == StagingState.WARM_PARKED

        # Step 3: Host RAM -> Cold SSD
        s3 = cache.offload_specialist("SPEC-LIFECYCLE", StorageTier.TIER3_COLD_SSD)
        assert s3.tier == StorageTier.TIER3_COLD_SSD
        assert s3.state == StagingState.COLD_STORED

        # Verify transfer history contains all 3 operations with realistic metrics
        history = cache.get_transfer_history()
        assert len(history) == 3
        for transfer in history:
            assert transfer.specialist_id == "SPEC-LIFECYCLE"
            assert transfer.bytes_transferred == model_size
            assert transfer.transfer_duration_ms > 0.0
            assert transfer.transfer_rate_gb_per_sec > 0.0
