"""Unit tests for Layer 10 contextual bandit routing policy offline evaluation.

Tests compliance with DOC-SPEC-MOD-001 (Boundary J), ADR-001, ADR-006, ADR-008, and Issue #73:
- Routing context feature extraction, contracts, and serialization
- Routing reward composite function, bounds, and physical VRAM penalty
- Deterministic baseline router behavior and critical memory degradation
- Offline policy fitting on logged traces, online training prohibition, and baseline evaluation
"""

from __future__ import annotations

import pytest

from laris.core.errors import (
    ModuleContractViolationError,
    PolicyRewardValidationError,
)
from laris.evaluation.contextual_bandit import (
    DeterministicBaselineRouter,
    OfflineContextualBanditEvaluator,
    PolicyEvaluationResult,
    RoutingContext,
    RoutingReward,
    compute_routing_reward,
)
from laris.execution.task_router import (
    ExecutionTier,
    TaskDomain,
)


class TestRoutingContextAndRewardContracts:
    """Unit tests for RoutingContext and RoutingReward data schemas and serialization."""

    def test_routing_context_valid_creation_and_feature_vector(self) -> None:
        """Verify valid context creation and normalized feature vector generation."""
        ctx = RoutingContext(
            context_id="CTX-001",
            task_domain=TaskDomain.NLI_VERIFICATION,
            token_count=1024,
            epistemic_uncertainty=0.25,
            current_headroom_gb=8.0,
        )
        assert ctx.context_id == "CTX-001"
        assert ctx.task_domain == TaskDomain.NLI_VERIFICATION

        feat = ctx.feature_vector()
        assert len(feat) == 5
        assert feat[0] == 1.0  # Bias term
        assert 0.0 <= feat[1] <= 1.0  # Domain index
        assert feat[2] == pytest.approx(1024 / 4096.0)  # Token count norm
        assert feat[3] == 0.25  # Uncertainty
        assert feat[4] == pytest.approx(8.0 / 16.0)  # Headroom norm

    @pytest.mark.parametrize(
        ("kwargs", "match_err"),
        [
            (
                {
                    "context_id": "",
                    "task_domain": TaskDomain.LEXICAL_RETRIEVAL,
                    "token_count": 100,
                    "epistemic_uncertainty": 0.1,
                    "current_headroom_gb": 4.0,
                },
                "context_id cannot be empty",
            ),
            (
                {
                    "context_id": "CTX-1",
                    "task_domain": TaskDomain.LEXICAL_RETRIEVAL,
                    "token_count": 0,
                    "epistemic_uncertainty": 0.1,
                    "current_headroom_gb": 4.0,
                },
                "token_count must be at least 1",
            ),
            (
                {
                    "context_id": "CTX-1",
                    "task_domain": TaskDomain.LEXICAL_RETRIEVAL,
                    "token_count": 100,
                    "epistemic_uncertainty": 1.2,
                    "current_headroom_gb": 4.0,
                },
                "epistemic_uncertainty must be in",
            ),
            (
                {
                    "context_id": "CTX-1",
                    "task_domain": TaskDomain.LEXICAL_RETRIEVAL,
                    "token_count": 100,
                    "epistemic_uncertainty": -0.1,
                    "current_headroom_gb": 4.0,
                },
                "epistemic_uncertainty must be in",
            ),
            (
                {
                    "context_id": "CTX-1",
                    "task_domain": TaskDomain.LEXICAL_RETRIEVAL,
                    "token_count": 100,
                    "epistemic_uncertainty": 0.1,
                    "current_headroom_gb": -1.0,
                },
                "current_headroom_gb cannot be negative",
            ),
        ],
    )
    def test_routing_context_contract_violations(
        self, kwargs: dict[str, object], match_err: str
    ) -> None:
        """Verify invalid context attributes raise ModuleContractViolationError."""
        with pytest.raises(ModuleContractViolationError, match=match_err):
            RoutingContext(**kwargs)  # type: ignore[arg-type]

    def test_routing_context_serialization_roundtrip(self) -> None:
        """Verify dictionary serialization round-trip for RoutingContext."""
        ctx = RoutingContext(
            context_id="CTX-ROUNDTRIP",
            task_domain=TaskDomain.GAP_DISCOVERY,
            token_count=2048,
            epistemic_uncertainty=0.42,
            current_headroom_gb=12.5,
        )
        data = ctx.to_dict()
        reconstituted = RoutingContext.from_dict(data)
        assert reconstituted.context_id == ctx.context_id
        assert reconstituted.task_domain == ctx.task_domain
        assert reconstituted.token_count == ctx.token_count
        assert reconstituted.epistemic_uncertainty == ctx.epistemic_uncertainty
        assert reconstituted.current_headroom_gb == ctx.current_headroom_gb

    def test_routing_reward_valid_creation_and_contracts(self) -> None:
        """Verify valid reward creation and schema contract validations."""
        rew = RoutingReward(
            context_id="CTX-001",
            selected_tier=ExecutionTier.TIER_2_MIDSIZED,
            quality_score=0.95,
            latency_ms=45.0,
            vram_allocated_gb=11.5,
            composite_reward=0.72,
            is_verified=True,
        )
        assert rew.context_id == "CTX-001"
        assert rew.is_verified is True

        with pytest.raises(ModuleContractViolationError, match="context_id cannot be empty"):
            RoutingReward(
                context_id="",
                selected_tier=ExecutionTier.TIER_1_COMPACT,
                quality_score=0.9,
                latency_ms=10.0,
                vram_allocated_gb=5.0,
                composite_reward=0.8,
            )

        with pytest.raises(ModuleContractViolationError, match="quality_score must be in"):
            RoutingReward(
                context_id="CTX-1",
                selected_tier=ExecutionTier.TIER_1_COMPACT,
                quality_score=1.5,
                latency_ms=10.0,
                vram_allocated_gb=5.0,
                composite_reward=0.8,
            )

        with pytest.raises(ModuleContractViolationError, match="latency_ms cannot be negative"):
            RoutingReward(
                context_id="CTX-1",
                selected_tier=ExecutionTier.TIER_1_COMPACT,
                quality_score=0.9,
                latency_ms=-5.0,
                vram_allocated_gb=5.0,
                composite_reward=0.8,
            )

        with pytest.raises(
            ModuleContractViolationError, match="vram_allocated_gb cannot be negative"
        ):
            RoutingReward(
                context_id="CTX-1",
                selected_tier=ExecutionTier.TIER_1_COMPACT,
                quality_score=0.9,
                latency_ms=10.0,
                vram_allocated_gb=-1.0,
                composite_reward=0.8,
            )

    def test_routing_reward_serialization_roundtrip(self) -> None:
        """Verify dictionary serialization round-trip for RoutingReward."""
        rew = RoutingReward(
            context_id="CTX-REW-ROUNDTRIP",
            selected_tier=ExecutionTier.TIER_3_DEEP,
            quality_score=0.98,
            latency_ms=120.0,
            vram_allocated_gb=13.8,
            composite_reward=0.81,
            is_verified=True,
        )
        data = rew.to_dict()
        reconstituted = RoutingReward.from_dict(data)
        assert reconstituted.context_id == rew.context_id
        assert reconstituted.selected_tier == rew.selected_tier
        assert reconstituted.composite_reward == rew.composite_reward


class TestCompositeRewardComputation:
    """Unit tests for compute_routing_reward function."""

    def test_compute_routing_reward_nominal(self) -> None:
        """Verify standard reward calculation balancing accuracy, latency, and VRAM."""
        rew = compute_routing_reward(
            quality_score=0.90,
            latency_ms=100.0,
            vram_allocated_gb=10.0,
            vram_ceiling_gb=15.0,
            latency_target_ms=100.0,
        )
        # alpha=0.7*0.90 = 0.63
        # beta=0.2 * (100/(300)) = 0.2 * 0.3333 = 0.0667
        # gamma=0.1 * (10/15) = 0.1 * 0.6667 = 0.0667
        # 0.63 - 0.0667 - 0.0667 ~ 0.4966
        assert 0.45 <= rew <= 0.55

    def test_compute_routing_reward_ceiling_breach(self) -> None:
        """Verify exceeding physical VRAM ceiling (15.0 GB) immediately yields -1.0 penalty."""
        rew = compute_routing_reward(
            quality_score=0.99,
            latency_ms=20.0,
            vram_allocated_gb=15.8,  # > 15.0 GB ceiling
            vram_ceiling_gb=15.0,
        )
        assert rew == -1.0


class TestDeterministicBaselineRouter:
    """Unit tests for the DeterministicBaselineRouter."""

    def test_canonical_domain_routing(self) -> None:
        """Verify each task domain routes to its canonical execution tier."""
        router = DeterministicBaselineRouter()

        cases = [
            (TaskDomain.SYMBOLIC_VALIDATION, ExecutionTier.TIER_0_SYMBOLIC),
            (TaskDomain.LEXICAL_RETRIEVAL, ExecutionTier.TIER_1_COMPACT),
            (TaskDomain.DENSE_EMBEDDING, ExecutionTier.TIER_2_MIDSIZED),
            (TaskDomain.NLI_VERIFICATION, ExecutionTier.TIER_2_MIDSIZED),
            (TaskDomain.CROSS_PAPER_SYNTHESIS, ExecutionTier.TIER_3_DEEP),
            (TaskDomain.GAP_DISCOVERY, ExecutionTier.TIER_3_DEEP),
        ]
        for domain, expected_tier in cases:
            ctx = RoutingContext(
                context_id=f"CTX-{domain.value}",
                task_domain=domain,
                token_count=500,
                epistemic_uncertainty=0.1,
                current_headroom_gb=10.0,
            )
            assert router.select_tier(ctx) == expected_tier

    def test_headroom_degradation_fallback(self) -> None:
        """Verify deep or mid-sized tiers degrade to compact tier under low headroom (< 1.5 GB)."""
        router = DeterministicBaselineRouter()

        ctx_degrade = RoutingContext(
            context_id="CTX-LOW-HEADROOM",
            task_domain=TaskDomain.GAP_DISCOVERY,  # Normally Tier 3 Deep
            token_count=500,
            epistemic_uncertainty=0.1,
            current_headroom_gb=1.2,  # < 1.5 GB critical threshold
        )
        assert router.select_tier(ctx_degrade) == ExecutionTier.TIER_1_COMPACT


class TestOfflineContextualBanditEvaluator:
    """Unit tests for offline contextual bandit policy evaluation and safety gates."""

    def test_unfitted_policy_fallback_to_baseline(self) -> None:
        """Verify un-fitted evaluator seamlessly uses deterministic baseline router."""
        evaluator = OfflineContextualBanditEvaluator()
        ctx = RoutingContext(
            context_id="CTX-UNFIT",
            task_domain=TaskDomain.SYMBOLIC_VALIDATION,
            token_count=100,
            epistemic_uncertainty=0.05,
            current_headroom_gb=8.0,
        )
        assert evaluator.select_tier(ctx) == ExecutionTier.TIER_0_SYMBOLIC

    def test_fit_offline_empty_trials_fails(self) -> None:
        """Verify fitting on empty logged trials raises ModuleContractViolationError."""
        evaluator = OfflineContextualBanditEvaluator()
        with pytest.raises(ModuleContractViolationError, match="empty logged trials"):
            evaluator.fit_offline([])

    def test_fit_offline_unverified_reward_fails(self) -> None:
        """Verify fitting on unverified reward raises PolicyRewardValidationError."""
        evaluator = OfflineContextualBanditEvaluator()
        ctx = RoutingContext(
            context_id="CTX-UNVERIFIED",
            task_domain=TaskDomain.NLI_VERIFICATION,
            token_count=200,
            epistemic_uncertainty=0.1,
            current_headroom_gb=8.0,
        )
        rew = RoutingReward(
            context_id="CTX-UNVERIFIED",
            selected_tier=ExecutionTier.TIER_2_MIDSIZED,
            quality_score=0.9,
            latency_ms=50.0,
            vram_allocated_gb=10.0,
            composite_reward=0.6,
            is_verified=False,  # Unverified reward!
        )
        with pytest.raises(PolicyRewardValidationError, match="unverified"):
            evaluator.fit_offline([(ctx, ExecutionTier.TIER_2_MIDSIZED, rew)])

    def test_online_training_attempt_strictly_prohibited(self) -> None:
        """Verify online self-training is explicitly forbidden."""
        evaluator = OfflineContextualBanditEvaluator()
        with pytest.raises(ModuleContractViolationError, match="Online self-training is strictly"):
            evaluator.trigger_online_training_attempt()

    def test_evaluate_against_baseline_empty_contexts_fails(self) -> None:
        """Verify evaluation on empty contexts list raises error."""
        evaluator = OfflineContextualBanditEvaluator()
        with pytest.raises(ModuleContractViolationError, match="cannot be empty"):
            evaluator.evaluate_against_baseline(
                eval_id="EVAL-EMPTY",
                contexts=[],
                reward_oracle=lambda c, t: None,  # type: ignore[return-value]
            )

    def test_evaluate_against_baseline_unverified_reward_fails(self) -> None:
        """Verify encounter of unverified reward during evaluation raises exception."""
        evaluator = OfflineContextualBanditEvaluator()
        ctx = RoutingContext(
            context_id="CTX-EVAL-BAD-REW",
            task_domain=TaskDomain.LEXICAL_RETRIEVAL,
            token_count=100,
            epistemic_uncertainty=0.1,
            current_headroom_gb=8.0,
        )

        def mock_oracle(c: RoutingContext, t: ExecutionTier) -> RoutingReward:
            return RoutingReward(
                context_id=c.context_id,
                selected_tier=t,
                quality_score=0.9,
                latency_ms=10.0,
                vram_allocated_gb=4.0,
                composite_reward=0.7,
                is_verified=False,
            )

        with pytest.raises(PolicyRewardValidationError, match="Invalid reward signal"):
            evaluator.evaluate_against_baseline("EVAL-FAIL", [ctx], mock_oracle)

    def test_evaluate_against_baseline_successful_comparison(self) -> None:
        """Verify offline evaluation computes valid comparative metrics and activation flag."""
        evaluator = OfflineContextualBanditEvaluator()

        # Generate training traces to fit evaluator
        training_traces = []
        for i in range(20):
            domain = list(TaskDomain)[i % len(TaskDomain)]
            ctx = RoutingContext(
                context_id=f"CTX-TRAIN-{i:03d}",
                task_domain=domain,
                token_count=500 + i * 50,
                epistemic_uncertainty=0.1 + (i * 0.03) % 0.8,
                current_headroom_gb=10.0,
            )
            tier = ExecutionTier.TIER_1_COMPACT
            rew = RoutingReward(
                context_id=ctx.context_id,
                selected_tier=tier,
                quality_score=0.92,
                latency_ms=30.0,
                vram_allocated_gb=6.0,
                composite_reward=0.75,
                is_verified=True,
            )
            training_traces.append((ctx, tier, rew))

        evaluator.fit_offline(training_traces)

        # Test evaluation contexts
        eval_contexts = [
            RoutingContext(
                context_id=f"CTX-EVAL-{i:03d}",
                task_domain=list(TaskDomain)[i % len(TaskDomain)],
                token_count=400 + i * 100,
                epistemic_uncertainty=0.15,
                current_headroom_gb=9.0,
            )
            for i in range(10)
        ]

        def test_oracle(c: RoutingContext, t: ExecutionTier) -> RoutingReward:
            # Policy chooses Tier 1 which has low latency; Baseline chooses default tier
            lat = 25.0 if t == ExecutionTier.TIER_1_COMPACT else 90.0
            qual = 0.94 if t == ExecutionTier.TIER_1_COMPACT else 0.90
            comp = compute_routing_reward(qual, lat, 6.0)
            return RoutingReward(
                context_id=c.context_id,
                selected_tier=t,
                quality_score=qual,
                latency_ms=lat,
                vram_allocated_gb=6.0,
                composite_reward=comp,
                is_verified=True,
            )

        res = evaluator.evaluate_against_baseline("EVAL-RUN-01", eval_contexts, test_oracle)

        assert res.eval_id == "EVAL-RUN-01"
        assert res.num_trials == 10
        assert res.policy_name == "OfflineContextualBandit-v1"
        assert res.baseline_name == "DeterministicBaselineRouter"
        assert isinstance(res.is_activated, bool)
        assert len(res.decisions_summary) > 0

        # Test serialization round-trip of PolicyEvaluationResult
        res_dict = res.to_dict()
        reconstituted = PolicyEvaluationResult.from_dict(res_dict)
        assert reconstituted.eval_id == res.eval_id
        assert reconstituted.policy_mean_reward == res.policy_mean_reward
        assert reconstituted.relative_reward_gain == res.relative_reward_gain
        assert reconstituted.is_activated == res.is_activated

    def test_fitted_policy_low_headroom_penalty(self) -> None:
        """Verify fitted evaluator penalizes deep and midsized tiers under critical headroom."""
        evaluator = OfflineContextualBanditEvaluator()
        ctx = RoutingContext(
            context_id="CTX-TRAIN",
            task_domain=TaskDomain.GAP_DISCOVERY,
            token_count=1000,
            epistemic_uncertainty=0.5,
            current_headroom_gb=10.0,
        )
        # Train to prefer Tier 3 Deep
        rew = RoutingReward(
            context_id="CTX-TRAIN",
            selected_tier=ExecutionTier.TIER_3_DEEP,
            quality_score=0.99,
            latency_ms=80.0,
            vram_allocated_gb=12.0,
            composite_reward=1.0,
        )
        evaluator.fit_offline([(ctx, ExecutionTier.TIER_3_DEEP, rew)] * 10)

        # Evaluate with critical headroom (< 1.5 GB)
        critical_ctx = RoutingContext(
            context_id="CTX-CRITICAL",
            task_domain=TaskDomain.GAP_DISCOVERY,
            token_count=1000,
            epistemic_uncertainty=0.5,
            current_headroom_gb=1.0,  # Critical headroom
        )
        # Due to score -= 2.0 penalty on Tier 3 & Tier 2, Tier 1 is selected
        selected = evaluator.select_tier(critical_ctx)
        assert selected not in (ExecutionTier.TIER_2_MIDSIZED, ExecutionTier.TIER_3_DEEP)

    def test_evaluate_against_baseline_unverified_baseline_reward(self) -> None:
        """Verify unverified baseline reward raises PolicyRewardValidationError."""
        evaluator = OfflineContextualBanditEvaluator()
        ctx = RoutingContext(
            context_id="CTX-BASE-BAD",
            task_domain=TaskDomain.LEXICAL_RETRIEVAL,
            token_count=100,
            epistemic_uncertainty=0.1,
            current_headroom_gb=8.0,
        )
        train_rew = RoutingReward(
            context_id="CTX-TRAIN",
            selected_tier=ExecutionTier.TIER_3_DEEP,
            quality_score=0.9,
            latency_ms=10.0,
            vram_allocated_gb=4.0,
            composite_reward=1.0,
            is_verified=True,
        )
        evaluator.fit_offline([(ctx, ExecutionTier.TIER_3_DEEP, train_rew)] * 10)

        def mock_oracle(c: RoutingContext, t: ExecutionTier) -> RoutingReward:
            # Policy (Tier 3) is verified, but baseline (Tier 1) is unverified
            is_ver = False if t == ExecutionTier.TIER_1_COMPACT else True
            return RoutingReward(
                context_id=c.context_id,
                selected_tier=t,
                quality_score=0.9,
                latency_ms=10.0,
                vram_allocated_gb=4.0,
                composite_reward=0.7,
                is_verified=is_ver,
            )

        with pytest.raises(PolicyRewardValidationError, match="Invalid reward signal"):
            evaluator.evaluate_against_baseline("EVAL-BASE-FAIL", [ctx], mock_oracle)

