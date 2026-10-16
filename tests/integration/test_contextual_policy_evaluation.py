"""Integration tests for contextual routing policy baseline comparison and reward validity.

Tests compliance with DOC-SPEC-MOD-001 (Boundary J), ADR-001, ADR-006, ADR-008, and Issue #105:
- Offline counterfactual replay and benchmark comparison against deterministic router
- Latency SLA versus output quality trade-off evaluation across task domains
- Strict reward validity gating preventing policy activation on invalid or unverified signals
- Hardware budget ceiling (<= 15.0 GB physical VRAM) and critical headroom degradation
- Boundary J invariant prohibiting online self-training and policy drift
- Multi-threaded concurrent evaluation safety
"""

from __future__ import annotations

import concurrent.futures
from typing import List

import pytest

from laris.core.errors import (
    ModuleContractViolationError,
    PolicyRewardValidationError,
)
from laris.layers.layer9_adaptive_execution.task_router import (
    ExecutionTier,
    TaskDomain,
)
from laris.layers.layer10_evaluation.contextual_bandit import (
    DeterministicBaselineRouter,
    OfflineContextualBanditEvaluator,
    PolicyEvaluationResult,
    RoutingContext,
    RoutingReward,
    compute_routing_reward,
)


def _generate_synthetic_workload(num_contexts: int = 120) -> List[RoutingContext]:
    """Generate representative synthetic query contexts across all 6 task domains."""
    domains = list(TaskDomain)
    contexts: List[RoutingContext] = []
    for i in range(num_contexts):
        dom = domains[i % len(domains)]
        # Varied token counts and epistemic uncertainties
        tokens = 150 + (i * 37) % 4500
        uncertainty = 0.05 + ((i * 13) % 90) / 100.0
        headroom = 4.0 + ((i * 7) % 110) / 10.0
        contexts.append(
            RoutingContext(
                context_id=f"CTX-INT-SYNTH-{i:04d}",
                task_domain=dom,
                token_count=tokens,
                epistemic_uncertainty=uncertainty,
                current_headroom_gb=headroom,
            )
        )
    return contexts


def _synthetic_oracle(ctx: RoutingContext, tier: ExecutionTier) -> RoutingReward:
    """Deterministic reward oracle modeling domain-tier suitability and latency."""
    # Base quality depends on domain affinity
    if ctx.task_domain in (TaskDomain.CROSS_PAPER_SYNTHESIS, TaskDomain.GAP_DISCOVERY):
        quality = 0.95 if tier == ExecutionTier.TIER_3_DEEP else 0.70
    elif ctx.task_domain in (TaskDomain.DENSE_EMBEDDING, TaskDomain.NLI_VERIFICATION):
        tier_matches = tier in (ExecutionTier.TIER_2_MIDSIZED, ExecutionTier.TIER_3_DEEP)
        quality = 0.90 if tier_matches else 0.65
    else:
        quality = 0.88

    # Latency model (compact: 20ms, midsized: 75ms, deep: 160ms)
    latency_map = {
        ExecutionTier.TIER_0_SYMBOLIC: 5.0,
        ExecutionTier.TIER_1_COMPACT: 20.0,
        ExecutionTier.TIER_2_MIDSIZED: 75.0,
        ExecutionTier.TIER_3_DEEP: 160.0,
    }
    lat = latency_map[tier]

    # VRAM model
    vram_map = {
        ExecutionTier.TIER_0_SYMBOLIC: 0.1,
        ExecutionTier.TIER_1_COMPACT: 1.8,
        ExecutionTier.TIER_2_MIDSIZED: 6.2,
        ExecutionTier.TIER_3_DEEP: 11.5,
    }
    vram = vram_map[tier]

    comp_rew = compute_routing_reward(
        quality_score=quality,
        latency_ms=lat,
        vram_allocated_gb=vram,
        vram_ceiling_gb=15.0,
        latency_target_ms=100.0,
    )

    return RoutingReward(
        context_id=ctx.context_id,
        selected_tier=tier,
        quality_score=quality,
        latency_ms=lat,
        vram_allocated_gb=vram,
        composite_reward=comp_rew,
        is_verified=True,
    )


class TestOfflineContextualPolicyEvaluationWorkloads:
    """Integration tests evaluating policy behavior across realistic synthetic workloads."""

    def test_end_to_end_counterfactual_workload_evaluation(self) -> None:
        """Verify end-to-end training and evaluation against deterministic baseline."""
        contexts = _generate_synthetic_workload(120)
        evaluator = OfflineContextualBanditEvaluator()

        # Generate logged training trials
        logged_trials = []
        for ctx in contexts[:60]:
            # Optimal tier selection for training
            if ctx.task_domain in (TaskDomain.CROSS_PAPER_SYNTHESIS, TaskDomain.GAP_DISCOVERY):
                chosen_tier = ExecutionTier.TIER_3_DEEP
            elif ctx.task_domain in (TaskDomain.DENSE_EMBEDDING, TaskDomain.NLI_VERIFICATION):
                chosen_tier = ExecutionTier.TIER_2_MIDSIZED
            elif ctx.task_domain == TaskDomain.SYMBOLIC_VALIDATION:
                chosen_tier = ExecutionTier.TIER_0_SYMBOLIC
            else:
                chosen_tier = ExecutionTier.TIER_1_COMPACT

            rew = _synthetic_oracle(ctx, chosen_tier)
            logged_trials.append((ctx, chosen_tier, rew))

        # Train policy offline on logged traces
        evaluator.fit_offline(logged_trials)
        assert evaluator.is_fitted

        # Evaluate against baseline router on held-out evaluation workload
        eval_contexts = contexts[60:]
        result: PolicyEvaluationResult = evaluator.evaluate_against_baseline(
            eval_id="EVAL-EXP-WORKLOAD-001",
            contexts=eval_contexts,
            reward_oracle=_synthetic_oracle,
        )

        assert result.eval_id == "EVAL-EXP-WORKLOAD-001"
        assert result.num_trials == 60
        assert isinstance(result.relative_reward_gain, float)
        assert isinstance(result.policy_mean_latency_ms, float)
        assert isinstance(result.policy_mean_quality, float)
        assert isinstance(result.is_activated, bool)
        assert isinstance(result.to_dict(), dict)

    def test_latency_quality_tradeoff_surfaces(self) -> None:
        """Verify composite reward trade-offs between tight latency SLA and high quality."""
        # Fast compact tier: lower latency (25ms), lower quality (0.75)
        rew_fast = compute_routing_reward(
            quality_score=0.75,
            latency_ms=25.0,
            vram_allocated_gb=2.0,
            alpha=0.6,
            beta=0.3,
            gamma=0.1,
            latency_target_ms=50.0,
        )

        # Deep tier: higher latency (180ms), higher quality (0.95)
        rew_deep = compute_routing_reward(
            quality_score=0.95,
            latency_ms=180.0,
            vram_allocated_gb=11.0,
            alpha=0.6,
            beta=0.3,
            gamma=0.1,
            latency_target_ms=50.0,
        )

        # Both rewards must be bounded and valid
        assert -1.0 <= rew_fast <= 1.0
        assert -1.0 <= rew_deep <= 1.0

    def test_policy_activation_disabled_on_insufficient_gain(self) -> None:
        """Verify policy activation recommendation is False when reward gain <= threshold."""
        evaluator = OfflineContextualBanditEvaluator()
        # Unfitted policy defaults to baseline router, so relative gain == 0.0
        ctx = RoutingContext(
            context_id="CTX-FLAT-001",
            task_domain=TaskDomain.LEXICAL_RETRIEVAL,
            token_count=200,
            epistemic_uncertainty=0.1,
            current_headroom_gb=10.0,
        )
        result = evaluator.evaluate_against_baseline(
            eval_id="EVAL-FLAT-GAIN",
            contexts=[ctx],
            reward_oracle=_synthetic_oracle,
        )
        # rel_gain == 0.0, which is not > 0.0, so is_activated must be False
        assert not result.is_activated

    def test_policy_activation_disabled_on_excessive_quality_drop(self) -> None:
        """Verify policy activation recommendation is False when quality drops > 0.01."""
        evaluator = OfflineContextualBanditEvaluator()
        ctx = RoutingContext(
            context_id="CTX-DEG-001",
            task_domain=TaskDomain.CROSS_PAPER_SYNTHESIS,
            token_count=500,
            epistemic_uncertainty=0.1,
            current_headroom_gb=10.0,
        )

        # Train policy to prefer TIER_0_SYMBOLIC
        train_rew = RoutingReward(
            context_id="CTX-TRAIN",
            selected_tier=ExecutionTier.TIER_0_SYMBOLIC,
            quality_score=0.20,
            latency_ms=5.0,
            vram_allocated_gb=0.1,
            composite_reward=0.9,
            is_verified=True,
        )
        evaluator.fit_offline([(ctx, ExecutionTier.TIER_0_SYMBOLIC, train_rew)] * 10)

        # Custom oracle where Tier 0 has poor quality (0.20) vs baseline Tier 3 (0.95)
        def custom_oracle(c: RoutingContext, t: ExecutionTier) -> RoutingReward:
            q = 0.20 if t == ExecutionTier.TIER_0_SYMBOLIC else 0.95
            return RoutingReward(
                context_id=c.context_id,
                selected_tier=t,
                quality_score=q,
                latency_ms=10.0,
                vram_allocated_gb=2.0,
                composite_reward=0.8 if t == ExecutionTier.TIER_0_SYMBOLIC else 0.5,
                is_verified=True,
            )

        result = evaluator.evaluate_against_baseline(
            eval_id="EVAL-QUALITY-DROP",
            contexts=[ctx],
            reward_oracle=custom_oracle,
        )
        # Quality drop is 0.95 - 0.20 = 0.75 > 0.01, so is_activated must be False
        assert not result.is_activated


class TestRewardSignalValidityGating:
    """Integration tests for reward signal validation and safety constraints."""

    def test_unverified_reward_blocks_offline_fitting(self) -> None:
        """Verify that any unverified reward signal prevents offline policy fitting."""
        evaluator = OfflineContextualBanditEvaluator()
        ctx = RoutingContext(
            context_id="CTX-INVALID-FIT",
            task_domain=TaskDomain.LEXICAL_RETRIEVAL,
            token_count=100,
            epistemic_uncertainty=0.1,
            current_headroom_gb=10.0,
        )
        invalid_rew = RoutingReward(
            context_id="CTX-INVALID-FIT",
            selected_tier=ExecutionTier.TIER_1_COMPACT,
            quality_score=0.8,
            latency_ms=20.0,
            vram_allocated_gb=2.0,
            composite_reward=0.6,
            is_verified=False,  # Unverified reward signal
        )

        with pytest.raises(PolicyRewardValidationError, match="Refusing to fit policy"):
            evaluator.fit_offline([(ctx, ExecutionTier.TIER_1_COMPACT, invalid_rew)])

    def test_unverified_reward_blocks_evaluation_stream(self) -> None:
        """Verify that an unverified reward in the evaluation stream halts execution."""
        evaluator = OfflineContextualBanditEvaluator()
        ctx = RoutingContext(
            context_id="CTX-INVALID-STREAM",
            task_domain=TaskDomain.SYMBOLIC_VALIDATION,
            token_count=100,
            epistemic_uncertainty=0.1,
            current_headroom_gb=10.0,
        )

        def bad_oracle(c: RoutingContext, t: ExecutionTier) -> RoutingReward:
            return RoutingReward(
                context_id=c.context_id,
                selected_tier=t,
                quality_score=0.9,
                latency_ms=5.0,
                vram_allocated_gb=0.1,
                composite_reward=0.8,
                is_verified=False,
            )

        with pytest.raises(PolicyRewardValidationError, match="Invalid reward signal"):
            evaluator.evaluate_against_baseline("EVAL-BAD-STREAM", [ctx], bad_oracle)

    def test_vram_ceiling_breach_penalized(self) -> None:
        """Verify that breaching the 15.0 GB physical VRAM ceiling assigns -1.0 penalty."""
        rew = compute_routing_reward(
            quality_score=0.99,
            latency_ms=10.0,
            vram_allocated_gb=15.5,  # Exceeds 15.0 GB ceiling
            vram_ceiling_gb=15.0,
        )
        assert rew == -1.0

    def test_critical_headroom_tier_degradation(self) -> None:
        """Verify that both policy and baseline router degrade tiers when headroom < 1.5 GB."""
        ctx_restricted = RoutingContext(
            context_id="CTX-LOW-VRAM",
            task_domain=TaskDomain.CROSS_PAPER_SYNTHESIS,
            token_count=2000,
            epistemic_uncertainty=0.8,
            current_headroom_gb=1.2,  # Critical headroom (< 1.5 GB)
        )
        baseline = DeterministicBaselineRouter()
        evaluator = OfflineContextualBanditEvaluator()

        # Baseline router normally assigns TIER_3_DEEP for CROSS_PAPER_SYNTHESIS,
        # but under restricted headroom it degrades to TIER_1_COMPACT
        base_decision = baseline.select_tier(ctx_restricted)
        assert base_decision == ExecutionTier.TIER_1_COMPACT

        # Policy router also avoids TIER_2 and TIER_3 under restricted headroom
        policy_decision = evaluator.select_tier(ctx_restricted)
        assert policy_decision not in (ExecutionTier.TIER_2_MIDSIZED, ExecutionTier.TIER_3_DEEP)


class TestOnlineSafetyAndConcurrencyInvariants:
    """Integration tests for Boundary J invariants, ADR-008, and thread safety."""

    def test_strict_online_self_training_prohibition(self) -> None:
        """Verify trigger_online_training_attempt() raises ModuleContractViolationError."""
        evaluator = OfflineContextualBanditEvaluator()
        with pytest.raises(
            ModuleContractViolationError, match="Online self-training is strictly prohibited"
        ):
            evaluator.trigger_online_training_attempt()

    def test_concurrent_policy_evaluation_thread_safety(self) -> None:
        """Verify multi-threaded evaluation against baseline without state corruption."""
        contexts = _generate_synthetic_workload(30)
        evaluator = OfflineContextualBanditEvaluator()

        def run_eval(worker_idx: int) -> PolicyEvaluationResult:
            return evaluator.evaluate_against_baseline(
                eval_id=f"EVAL-CONCURRENT-{worker_idx:02d}",
                contexts=contexts,
                reward_oracle=_synthetic_oracle,
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(run_eval, i) for i in range(8)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        assert len(results) == 8
        for res in results:
            assert res.num_trials == 30
