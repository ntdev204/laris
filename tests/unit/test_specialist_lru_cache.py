"""Unit tests for Layer 9 specialist weight staging and LRU cache.

Tests compliance with DOC-SPEC-MOD-001 (Boundary I), ADR-001, ADR-005, and Issue #69:
- Specialist weight descriptor contracts and invariant validation
- Mock weight loader simulating PCIe Gen4 and NVMe SSD bandwidths
- Cache hit / miss lifecycle and LRU access timestamp updates
- Automatic eviction of inactive specialists before new loads to fit within 14.5 GB ceiling
- Immunity of pinned specialists from automatic LRU eviction
- Failure rollback ensuring cache coherence and zero orphaned memory allocations
- Offloading state transitions and empirical tier occupancy metrics
"""

import pytest

from laris.core.errors import (
    HardwareBudgetExceededError,
    ModuleContractViolationError,
    WeightStagingError,
)
from laris.layers.layer9_adaptive_execution.headroom_governor import (
    HeadroomBudgetGovernor,
)
from laris.layers.layer9_adaptive_execution.weight_staging import (
    MockSpecialistWeightLoader,
    SpecialistLRUCache,
    SpecialistWeightDescriptor,
    StagingState,
    StorageTier,
    WeightTransferMetrics,
)


class TestWeightStagingDataContracts:
    """Tests schema contracts and invariants for weight staging descriptors and metrics."""

    def test_valid_weight_descriptor(self) -> None:
        """Test valid creation of SpecialistWeightDescriptor."""
        desc = SpecialistWeightDescriptor(
            specialist_id="SPEC-NLI",
            parameter_count=350_000_000,
            size_bytes=700 * 1024 * 1024,
            tier=StorageTier.TIER3_COLD_SSD,
            state=StagingState.COLD_STORED,
        )
        assert desc.specialist_id == "SPEC-NLI"
        assert desc.parameter_count == 350_000_000
        assert desc.size_bytes == 700 * 1024 * 1024
        assert desc.tier == StorageTier.TIER3_COLD_SSD
        assert desc.state == StagingState.COLD_STORED
        assert desc.is_pinned is False
        assert desc.access_count == 0

    @pytest.mark.parametrize(
        ("kwargs", "expected_err"),
        [
            (
                {
                    "specialist_id": "",
                    "parameter_count": 100,
                    "size_bytes": 1000,
                },
                "specialist_id cannot be empty",
            ),
            (
                {
                    "specialist_id": "SPEC",
                    "parameter_count": 0,
                    "size_bytes": 1000,
                },
                "parameter_count must be strictly positive",
            ),
            (
                {
                    "specialist_id": "SPEC",
                    "parameter_count": 100,
                    "size_bytes": 0,
                },
                "size_bytes must be strictly positive",
            ),
            (
                {
                    "specialist_id": "SPEC",
                    "parameter_count": 100,
                    "size_bytes": 1000,
                    "access_count": -1,
                },
                "access_count cannot be negative",
            ),
        ],
    )
    def test_invalid_weight_descriptor_raises(self, kwargs: dict, expected_err: str) -> None:
        """Test invalid descriptor configurations raise ModuleContractViolationError."""
        with pytest.raises(ModuleContractViolationError, match=expected_err):
            SpecialistWeightDescriptor(**kwargs)

    def test_weight_transfer_metrics_contract(self) -> None:
        """Test WeightTransferMetrics contract and invariant checks."""
        metric = WeightTransferMetrics(
            specialist_id="SPEC-ENC",
            source_tier=StorageTier.TIER2_HOST_RAM,
            target_tier=StorageTier.TIER1_GPU_VRAM,
            bytes_transferred=1024 * 1024 * 1024,
            transfer_duration_ms=40.0,
            transfer_rate_gb_per_sec=25.0,
        )
        assert metric.specialist_id == "SPEC-ENC"
        assert metric.bytes_transferred == 1024 * 1024 * 1024

        with pytest.raises(ModuleContractViolationError, match="specialist_id cannot be empty"):
            WeightTransferMetrics(
                specialist_id="",
                source_tier=StorageTier.TIER2_HOST_RAM,
                target_tier=StorageTier.TIER1_GPU_VRAM,
                bytes_transferred=100,
                transfer_duration_ms=1.0,
                transfer_rate_gb_per_sec=1.0,
            )

        with pytest.raises(
            ModuleContractViolationError, match="bytes_transferred cannot be negative"
        ):
            WeightTransferMetrics(
                specialist_id="S",
                source_tier=StorageTier.TIER2_HOST_RAM,
                target_tier=StorageTier.TIER1_GPU_VRAM,
                bytes_transferred=-1,
                transfer_duration_ms=1.0,
                transfer_rate_gb_per_sec=1.0,
            )

        with pytest.raises(
            ModuleContractViolationError, match="transfer_duration_ms cannot be negative"
        ):
            WeightTransferMetrics(
                specialist_id="S",
                source_tier=StorageTier.TIER2_HOST_RAM,
                target_tier=StorageTier.TIER1_GPU_VRAM,
                bytes_transferred=100,
                transfer_duration_ms=-0.5,
                transfer_rate_gb_per_sec=1.0,
            )

        with pytest.raises(
            ModuleContractViolationError, match="transfer_rate_gb_per_sec cannot be negative"
        ):
            WeightTransferMetrics(
                specialist_id="S",
                source_tier=StorageTier.TIER2_HOST_RAM,
                target_tier=StorageTier.TIER1_GPU_VRAM,
                bytes_transferred=100,
                transfer_duration_ms=1.0,
                transfer_rate_gb_per_sec=-1.0,
            )


class TestMockSpecialistWeightLoader:
    """Tests simulation and failure injection behavior of MockSpecialistWeightLoader."""

    def test_mock_loader_transfer_simulation(self) -> None:
        """Test realistic duration calculation based on simulated bandwidth."""
        loader = MockSpecialistWeightLoader(bandwidth_pcie_gbps=25.0, bandwidth_ssd_gbps=3.5)
        desc = SpecialistWeightDescriptor(
            specialist_id="SPEC-1",
            parameter_count=1_000_000_000,
            size_bytes=2 * 1024 * 1024 * 1024,  # 2 GB
        )

        # 2 GB over PCIe (25 GB/s) -> ~80 ms
        duration_pcie = loader.load_weights(desc, StorageTier.TIER1_GPU_VRAM)
        assert 70.0 < duration_pcie < 90.0

        # Offload 2 GB to RAM
        offload_duration = loader.offload_weights(desc, StorageTier.TIER2_HOST_RAM)
        assert 70.0 < offload_duration < 90.0

        # Load from SSD to RAM
        duration_ssd = loader.load_weights(desc, StorageTier.TIER2_HOST_RAM)
        assert duration_ssd > duration_pcie

    def test_mock_loader_failure_injection(self) -> None:
        """Test mock loader raises RuntimeError when configured to fail on a specialist."""
        loader = MockSpecialistWeightLoader(fail_on_specialist_id="SPEC-FAULTY")
        desc = SpecialistWeightDescriptor(
            specialist_id="SPEC-FAULTY",
            parameter_count=100_000_000,
            size_bytes=200_000_000,
        )
        with pytest.raises(RuntimeError, match="Simulated hardware failure staging"):
            loader.load_weights(desc, StorageTier.TIER1_GPU_VRAM)

        with pytest.raises(RuntimeError, match="Simulated hardware failure offloading"):
            loader.offload_weights(desc, StorageTier.TIER2_HOST_RAM)

    def test_mock_loader_invalid_bandwidth(self) -> None:
        """Test invalid bandwidth values raise ModuleContractViolationError."""
        with pytest.raises(
            ModuleContractViolationError, match="bandwidth_pcie_gbps must be strictly positive"
        ):
            MockSpecialistWeightLoader(bandwidth_pcie_gbps=0.0)

        with pytest.raises(
            ModuleContractViolationError, match="bandwidth_ssd_gbps must be strictly positive"
        ):
            MockSpecialistWeightLoader(bandwidth_ssd_gbps=-1.0)


class TestSpecialistLRUCache:
    """Test suite for SpecialistLRUCache and staging state transitions."""

    @pytest.fixture
    def cache_fixture(self) -> SpecialistLRUCache:
        """Create a cache instance with a configured 14.5 GB ceiling governor."""
        governor = HeadroomBudgetGovernor(
            vram_ceiling_bytes=int(14.5 * 1024**3),
            vram_safety_margin_bytes=int(1.5 * 1024**3),
        )
        return SpecialistLRUCache(governor=governor)

    def test_specialist_registration_and_retrieval(
        self, cache_fixture: SpecialistLRUCache
    ) -> None:
        """Test registering specialists and duplicate rejection."""
        desc = SpecialistWeightDescriptor(
            specialist_id="SPEC-ENCODER",
            parameter_count=200_000_000,
            size_bytes=400 * 1024 * 1024,
        )
        cache_fixture.register_specialist(desc)
        retrieved = cache_fixture.get_specialist("SPEC-ENCODER")
        assert retrieved is not None
        assert retrieved.specialist_id == "SPEC-ENCODER"
        assert cache_fixture.get_specialist("NON_EXISTENT") is None

        with pytest.raises(ModuleContractViolationError, match="is already registered"):
            cache_fixture.register_specialist(desc)

        assert cache_fixture.hit_rate == 0.0

        with pytest.raises(ModuleContractViolationError, match="not registered in the cache"):
            cache_fixture.request_specialist("UNREGISTERED_MODEL")

        with pytest.raises(
            ModuleContractViolationError, match="Specialist 'UNREGISTERED_MODEL' not found"
        ):
            cache_fixture.offload_specialist("UNREGISTERED_MODEL")

    def test_cache_miss_and_hit_lifecycle(self, cache_fixture: SpecialistLRUCache) -> None:
        """Test cache miss on initial staging followed by cache hit on subsequent access."""
        desc = SpecialistWeightDescriptor(
            specialist_id="SPEC-NLI",
            parameter_count=1_000_000_000,
            size_bytes=2 * 1024 * 1024 * 1024,  # 2 GB
        )
        cache_fixture.register_specialist(desc)

        # Request 1: Cache MISS -> staged to Tier 1 GPU VRAM
        res1 = cache_fixture.request_specialist("SPEC-NLI")
        assert res1.state == StagingState.ACTIVE_LOADED
        assert res1.tier == StorageTier.TIER1_GPU_VRAM
        assert res1.access_count == 1
        assert res1.last_accessed_iso != ""
        assert cache_fixture.hits == 0
        assert cache_fixture.misses == 1
        assert cache_fixture.hit_rate == 0.0

        # Request 2: Cache HIT -> already resident in VRAM
        res2 = cache_fixture.request_specialist("SPEC-NLI")
        assert res2.state == StagingState.ACTIVE_LOADED
        assert res2.access_count == 2
        assert cache_fixture.hits == 1
        assert cache_fixture.misses == 1
        assert cache_fixture.hit_rate == 0.5

    def test_lru_automatic_eviction_under_memory_pressure(self) -> None:
        """Test that inactive models are evicted in LRU order when ceiling is reached."""
        # Governor configured with 10.0 GB ceiling for deterministic testing
        governor = HeadroomBudgetGovernor(
            vram_ceiling_bytes=int(10.0 * 1024**3),
            vram_safety_margin_bytes=int(1.0 * 1024**3),
        )
        cache = SpecialistLRUCache(governor=governor)

        # Register 3 models of 4.0 GB each (total 12.0 GB > 10.0 GB ceiling)
        m1 = SpecialistWeightDescriptor("MODEL-1", 2_000_000_000, 4 * 1024**3)
        m2 = SpecialistWeightDescriptor("MODEL-2", 2_000_000_000, 4 * 1024**3)
        m3 = SpecialistWeightDescriptor("MODEL-3", 2_000_000_000, 4 * 1024**3)

        cache.register_specialist(m1)
        cache.register_specialist(m2)
        cache.register_specialist(m3)

        # Stage MODEL-1 (4 GB in VRAM, 4 GB total)
        cache.request_specialist("MODEL-1")
        # Stage MODEL-2 (4 GB in VRAM, 8 GB total <= 10 GB ceiling)
        cache.request_specialist("MODEL-2")
        assert cache.evictions == 0

        # Access MODEL-1 again so MODEL-2 becomes the least recently used
        cache.request_specialist("MODEL-1")

        # Now stage MODEL-3 (4 GB). Total would be 8 + 4 = 12 GB > 10 GB.
        # MODEL-2 must be automatically evicted to Tier 2 Host RAM!
        cache.request_specialist("MODEL-3")
        assert cache.evictions == 1

        # Check model states
        mod1 = cache.get_specialist("MODEL-1")
        mod2 = cache.get_specialist("MODEL-2")
        mod3 = cache.get_specialist("MODEL-3")

        assert mod1 is not None and mod1.state == StagingState.ACTIVE_LOADED
        assert mod2 is not None and mod2.state == StagingState.WARM_PARKED
        assert mod2.tier == StorageTier.TIER2_HOST_RAM
        assert mod3 is not None and mod3.state == StagingState.ACTIVE_LOADED

    def test_pinned_specialist_immunity_from_eviction(self) -> None:
        """Test that pinned specialists are never evicted during memory pressure."""
        governor = HeadroomBudgetGovernor(
            vram_ceiling_bytes=int(7.0 * 1024**3),
            vram_safety_margin_bytes=int(1.0 * 1024**3),
        )
        cache = SpecialistLRUCache(governor=governor)

        m1 = SpecialistWeightDescriptor("MODEL-PINNED", 1_500_000_000, 3 * 1024**3)
        m2 = SpecialistWeightDescriptor("MODEL-UNPINNED", 1_500_000_000, 3 * 1024**3)
        m3 = SpecialistWeightDescriptor("MODEL-NEW", 1_500_000_000, 3 * 1024**3)

        cache.register_specialist(m1)
        cache.register_specialist(m2)
        cache.register_specialist(m3)

        # Stage and pin MODEL-PINNED
        cache.request_specialist("MODEL-PINNED")
        cache.pin_specialist("MODEL-PINNED")

        # Stage MODEL-UNPINNED
        cache.request_specialist("MODEL-UNPINNED")

        # Pinning validation
        pinned_desc = cache.get_specialist("MODEL-PINNED")
        assert pinned_desc is not None and pinned_desc.is_pinned is True

        # Staging MODEL-NEW requires evicting 3 GB. Even though MODEL-PINNED was accessed first,
        # MODEL-UNPINNED must be evicted because MODEL-PINNED is protected!
        cache.request_specialist("MODEL-NEW")

        assert cache.get_specialist("MODEL-PINNED").state == StagingState.ACTIVE_LOADED  # type: ignore[union-attr]
        assert cache.get_specialist("MODEL-UNPINNED").state == StagingState.WARM_PARKED  # type: ignore[union-attr]
        assert cache.get_specialist("MODEL-NEW").state == StagingState.ACTIVE_LOADED  # type: ignore[union-attr]

    def test_insufficient_headroom_all_pinned_raises(self) -> None:
        """Test HardwareBudgetExceededError raised if required headroom cannot be evicted."""
        governor = HeadroomBudgetGovernor(vram_ceiling_bytes=int(5.0 * 1024**3))
        cache = SpecialistLRUCache(governor=governor)

        m1 = SpecialistWeightDescriptor("M1", 1_000_000_000, 3 * 1024**3)
        m2 = SpecialistWeightDescriptor("M2", 1_000_000_000, 3 * 1024**3)

        cache.register_specialist(m1)
        cache.register_specialist(m2)

        cache.request_specialist("M1")
        cache.pin_specialist("M1")

        # Staging M2 requires 3 GB -> total 6 GB > 5 GB ceiling, but M1 is pinned
        with pytest.raises(
            HardwareBudgetExceededError, match="no evictable models remain in VRAM"
        ):
            cache.request_specialist("M2")

    def test_staging_failure_rollback(self) -> None:
        """Test that staging failure cleanly rolls back state and releases allocations."""
        loader = MockSpecialistWeightLoader(fail_on_specialist_id="SPEC-CORRUPT")
        governor = HeadroomBudgetGovernor()
        cache = SpecialistLRUCache(governor=governor, loader=loader)

        desc = SpecialistWeightDescriptor(
            specialist_id="SPEC-CORRUPT",
            parameter_count=500_000_000,
            size_bytes=1024 * 1024 * 1024,
            tier=StorageTier.TIER3_COLD_SSD,
            state=StagingState.COLD_STORED,
        )
        cache.register_specialist(desc)

        with pytest.raises(WeightStagingError, match="Failed to stage specialist 'SPEC-CORRUPT'"):
            cache.request_specialist("SPEC-CORRUPT")

        # State must be rolled back to COLD_STORED / TIER3_COLD_SSD
        post_failure = cache.get_specialist("SPEC-CORRUPT")
        assert post_failure is not None
        assert post_failure.state == StagingState.COLD_STORED
        assert post_failure.tier == StorageTier.TIER3_COLD_SSD

        # Governor registered allocation must remain 0 (no leak)
        assert governor.get_total_registered_allocation() == 0

    def test_explicit_offload_and_manual_evict(self, cache_fixture: SpecialistLRUCache) -> None:
        """Test explicit offloading and manual evict_lru operation."""
        desc = SpecialistWeightDescriptor("MODEL-A", 500_000_000, 1024**3)
        cache_fixture.register_specialist(desc)
        cache_fixture.request_specialist("MODEL-A")

        # Explicit offload to host RAM
        offloaded = cache_fixture.offload_specialist("MODEL-A", StorageTier.TIER2_HOST_RAM)
        assert offloaded.state == StagingState.WARM_PARKED
        assert offloaded.tier == StorageTier.TIER2_HOST_RAM

        # Offloading already offloaded model is a safe no-op
        assert cache_fixture.offload_specialist("MODEL-A").state == StagingState.WARM_PARKED

        # Offloading a cold SSD model is a safe no-op
        cold_desc = SpecialistWeightDescriptor("COLD-MODEL", 100_000, 100_000)
        cache_fixture.register_specialist(cold_desc)
        assert cache_fixture.offload_specialist("COLD-MODEL").tier == StorageTier.TIER3_COLD_SSD

        # Stage again then manual evict
        cache_fixture.request_specialist("MODEL-A")
        evicted = cache_fixture.evict_lru()
        assert evicted is not None
        assert evicted.specialist_id == "MODEL-A"
        assert evicted.state == StagingState.WARM_PARKED

        # evict_lru with no models in VRAM returns None
        assert cache_fixture.evict_lru() is None

    def test_unpin_and_pin_contract_checks(self, cache_fixture: SpecialistLRUCache) -> None:
        """Test pinning and unpinning non-existent specialist raises error."""
        with pytest.raises(ModuleContractViolationError, match="not found"):
            cache_fixture.pin_specialist("NON_EXISTENT")

        with pytest.raises(ModuleContractViolationError, match="not found"):
            cache_fixture.unpin_specialist("NON_EXISTENT")

        desc = SpecialistWeightDescriptor("M1", 100, 1000)
        cache_fixture.register_specialist(desc)
        cache_fixture.pin_specialist("M1")
        assert cache_fixture.get_specialist("M1").is_pinned is True  # type: ignore[union-attr]
        cache_fixture.unpin_specialist("M1")
        assert cache_fixture.get_specialist("M1").is_pinned is False  # type: ignore[union-attr]

    def test_tier_occupancy_and_telemetry_metrics(
        self, cache_fixture: SpecialistLRUCache
    ) -> None:
        """Test tier occupancy inspection and active vs total parameter counts."""
        m1 = SpecialistWeightDescriptor("M1", 500_000_000, 1 * 1024**3)
        m2 = SpecialistWeightDescriptor("M2", 1_500_000_000, 3 * 1024**3)
        cache_fixture.register_specialist(m1)
        cache_fixture.register_specialist(m2)

        assert cache_fixture.total_system_params == 2_000_000_000
        assert cache_fixture.active_params_count == 0

        # Stage M1
        cache_fixture.request_specialist("M1")
        assert cache_fixture.active_params_count == 500_000_000

        tier1 = cache_fixture.get_tier_occupancy(StorageTier.TIER1_GPU_VRAM)
        assert tier1["model_count"] == 1
        assert tier1["models"] == ["M1"]
        assert tier1["total_gb"] == 1.0

        tier3 = cache_fixture.get_tier_occupancy(StorageTier.TIER3_COLD_SSD)
        assert tier3["model_count"] == 1
        assert tier3["models"] == ["M2"]

        history = cache_fixture.get_transfer_history()
        assert len(history) >= 1
        assert history[0].specialist_id == "M1"
