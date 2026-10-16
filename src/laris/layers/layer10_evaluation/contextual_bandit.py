"""Contextual bandit routing policy offline evaluation and reward validation.

Adheres to DOC-SPEC-MOD-001 (Boundary J), ADR-001, ADR-006, ADR-008, and Issue #73:
- Offline contextual policy evaluation comparing specialist routing against deterministic baseline
- Composite reward validation combining accuracy/quality, latency SLA, and physical VRAM constraints
- Strict prohibition of online self-training to prevent uncontrolled policy drift or
  catastrophic forgetting
- Safety gating ensuring policy activation occurs only with verified positive empirical reward gains
"""

from __future__ import annotations

import datetime
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Tuple

from laris.core.errors import (
    ModuleContractViolationError,
    PolicyRewardValidationError,
)
from laris.layers.layer9_adaptive_execution.task_router import (
    ExecutionTier,
    TaskDomain,
)


@dataclass(frozen=True)
class RoutingContext:
    """Multi-dimensional contextual features for specialist routing decisions."""

    context_id: str
    task_domain: TaskDomain
    token_count: int
    epistemic_uncertainty: float
    current_headroom_gb: float

    def __post_init__(self) -> None:
        """Validate invariant contracts for routing context."""
        if not self.context_id or not self.context_id.strip():
            raise ModuleContractViolationError("context_id cannot be empty.")
        if self.token_count < 1:
            raise ModuleContractViolationError("token_count must be at least 1.")
        if not (0.0 <= self.epistemic_uncertainty <= 1.0):
            raise ModuleContractViolationError("epistemic_uncertainty must be in [0.0, 1.0].")
        if self.current_headroom_gb < 0.0:
            raise ModuleContractViolationError("current_headroom_gb cannot be negative.")

    def feature_vector(self) -> List[float]:
        """Convert contextual features into normalized numerical feature vector."""
        domain_idx = list(TaskDomain).index(self.task_domain) / max(1, len(TaskDomain) - 1)
        normalized_tokens = min(1.0, self.token_count / 4096.0)
        normalized_headroom = min(1.0, self.current_headroom_gb / 16.0)
        # Bias term, domain index, token length, epistemic uncertainty, headroom
        return [1.0, domain_idx, normalized_tokens, self.epistemic_uncertainty, normalized_headroom]

    def to_dict(self) -> Dict[str, Any]:
        """Convert routing context to a dictionary."""
        return {
            "context_id": self.context_id,
            "task_domain": self.task_domain.value,
            "token_count": self.token_count,
            "epistemic_uncertainty": self.epistemic_uncertainty,
            "current_headroom_gb": self.current_headroom_gb,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> RoutingContext:
        """Construct routing context from dictionary."""
        return cls(
            context_id=data["context_id"],
            task_domain=TaskDomain(data["task_domain"]),
            token_count=int(data["token_count"]),
            epistemic_uncertainty=float(data["epistemic_uncertainty"]),
            current_headroom_gb=float(data["current_headroom_gb"]),
        )


@dataclass(frozen=True)
class RoutingReward:
    """Empirical reward observation resulting from execution tier dispatch."""

    context_id: str
    selected_tier: ExecutionTier
    quality_score: float
    latency_ms: float
    vram_allocated_gb: float
    composite_reward: float
    is_verified: bool = True

    def __post_init__(self) -> None:
        """Validate invariant contracts for routing reward signal."""
        if not self.context_id or not self.context_id.strip():
            raise ModuleContractViolationError("context_id cannot be empty.")
        if not (0.0 <= self.quality_score <= 1.0):
            raise ModuleContractViolationError("quality_score must be in [0.0, 1.0].")
        if self.latency_ms < 0.0:
            raise ModuleContractViolationError("latency_ms cannot be negative.")
        if self.vram_allocated_gb < 0.0:
            raise ModuleContractViolationError("vram_allocated_gb cannot be negative.")

    def to_dict(self) -> Dict[str, Any]:
        """Convert reward record to a dictionary."""
        return {
            "context_id": self.context_id,
            "selected_tier": self.selected_tier.value,
            "quality_score": self.quality_score,
            "latency_ms": self.latency_ms,
            "vram_allocated_gb": self.vram_allocated_gb,
            "composite_reward": self.composite_reward,
            "is_verified": self.is_verified,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> RoutingReward:
        """Construct routing reward from dictionary."""
        return cls(
            context_id=data["context_id"],
            selected_tier=ExecutionTier(data["selected_tier"]),
            quality_score=float(data["quality_score"]),
            latency_ms=float(data["latency_ms"]),
            vram_allocated_gb=float(data["vram_allocated_gb"]),
            composite_reward=float(data["composite_reward"]),
            is_verified=bool(data.get("is_verified", True)),
        )


def compute_routing_reward(
    quality_score: float,
    latency_ms: float,
    vram_allocated_gb: float,
    vram_ceiling_gb: float = 15.0,
    latency_target_ms: float = 100.0,
    alpha: float = 0.70,
    beta: float = 0.20,
    gamma: float = 0.10,
) -> float:
    """Calculate deterministic composite reward balancing accuracy, latency, and VRAM budget.

    Formula:
        R = alpha * quality - beta * min(1.0, latency / (3 * target)) - gamma * (vram / ceiling)
        Penalized heavily (-1.0) if hard VRAM ceiling (15.0 GB) is violated.
    """
    if vram_allocated_gb > vram_ceiling_gb:
        return -1.0

    norm_latency = min(1.0, latency_ms / (latency_target_ms * 3.0))
    norm_vram = min(1.0, vram_allocated_gb / vram_ceiling_gb)

    raw_reward = (alpha * quality_score) - (beta * norm_latency) - (gamma * norm_vram)
    return round(raw_reward, 4)


@dataclass(frozen=True)
class PolicyEvaluationResult:
    """Comparative evaluation summary between contextual bandit policy and baseline router."""

    eval_id: str
    policy_name: str
    baseline_name: str
    num_trials: int
    policy_mean_reward: float
    baseline_mean_reward: float
    relative_reward_gain: float
    policy_mean_latency_ms: float
    baseline_mean_latency_ms: float
    policy_mean_quality: float
    baseline_mean_quality: float
    is_activated: bool
    timestamp_iso: str
    decisions_summary: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert evaluation result to dictionary."""
        return {
            "eval_id": self.eval_id,
            "policy_name": self.policy_name,
            "baseline_name": self.baseline_name,
            "num_trials": self.num_trials,
            "policy_mean_reward": self.policy_mean_reward,
            "baseline_mean_reward": self.baseline_mean_reward,
            "relative_reward_gain": self.relative_reward_gain,
            "policy_mean_latency_ms": self.policy_mean_latency_ms,
            "baseline_mean_latency_ms": self.baseline_mean_latency_ms,
            "policy_mean_quality": self.policy_mean_quality,
            "baseline_mean_quality": self.baseline_mean_quality,
            "is_activated": self.is_activated,
            "timestamp_iso": self.timestamp_iso,
            "decisions_summary": dict(self.decisions_summary),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> PolicyEvaluationResult:
        """Construct evaluation result from dictionary."""
        return cls(
            eval_id=data["eval_id"],
            policy_name=data["policy_name"],
            baseline_name=data["baseline_name"],
            num_trials=int(data["num_trials"]),
            policy_mean_reward=float(data["policy_mean_reward"]),
            baseline_mean_reward=float(data["baseline_mean_reward"]),
            relative_reward_gain=float(data["relative_reward_gain"]),
            policy_mean_latency_ms=float(data["policy_mean_latency_ms"]),
            baseline_mean_latency_ms=float(data["baseline_mean_latency_ms"]),
            policy_mean_quality=float(data["policy_mean_quality"]),
            baseline_mean_quality=float(data["baseline_mean_quality"]),
            is_activated=bool(data["is_activated"]),
            timestamp_iso=data["timestamp_iso"],
            decisions_summary=dict(data.get("decisions_summary", {})),
        )


class DeterministicBaselineRouter:
    """Fixed rule-based specialist router serving as the empirical baseline."""

    _DEFAULT_MAPPING = {
        TaskDomain.SYMBOLIC_VALIDATION: ExecutionTier.TIER_0_SYMBOLIC,
        TaskDomain.LEXICAL_RETRIEVAL: ExecutionTier.TIER_1_COMPACT,
        TaskDomain.DENSE_EMBEDDING: ExecutionTier.TIER_2_MIDSIZED,
        TaskDomain.NLI_VERIFICATION: ExecutionTier.TIER_2_MIDSIZED,
        TaskDomain.CROSS_PAPER_SYNTHESIS: ExecutionTier.TIER_3_DEEP,
        TaskDomain.GAP_DISCOVERY: ExecutionTier.TIER_3_DEEP,
    }

    def select_tier(self, context: RoutingContext) -> ExecutionTier:
        """Select execution tier based on deterministic domain mapping with headroom fallback."""
        tier = self._DEFAULT_MAPPING.get(context.task_domain, ExecutionTier.TIER_1_COMPACT)
        # Degradation check: if headroom is severely restricted (< 1.5 GB), degrade tier
        if context.current_headroom_gb < 1.5 and tier in (
            ExecutionTier.TIER_2_MIDSIZED,
            ExecutionTier.TIER_3_DEEP,
        ):
            return ExecutionTier.TIER_1_COMPACT
        return tier


class OfflineContextualBanditEvaluator:
    """Offline contextual bandit policy evaluator and safety verification gate."""

    def __init__(self, feature_dim: int = 5) -> None:
        self._feature_dim = feature_dim
        self._tiers = list(ExecutionTier)
        self._weights: Dict[ExecutionTier, List[float]] = {
            tier: [0.0] * feature_dim for tier in self._tiers
        }
        self._is_fitted = False
        self._lock = threading.Lock()

    def fit_offline(
        self,
        logged_trials: List[Tuple[RoutingContext, ExecutionTier, RoutingReward]],
    ) -> None:
        """Fit policy weights using ridge regression on offline logged execution traces."""
        if not logged_trials:
            raise ModuleContractViolationError("Cannot fit policy on empty logged trials.")

        # Invariant: Verify all training rewards are valid and verified
        for ctx, tier, rew in logged_trials:
            if not rew.is_verified:
                raise PolicyRewardValidationError(
                    f"Refusing to fit policy: reward for context '{ctx.context_id}' is unverified."
                )

        with self._lock:
            # Simple offline regularized gradient update per tier
            reg = 0.1
            for ctx, tier, rew in logged_trials:
                phi = ctx.feature_vector()
                pred = sum(w * f for w, f in zip(self._weights[tier], phi))
                err = rew.composite_reward - pred
                for i in range(self._feature_dim):
                    self._weights[tier][i] += 0.05 * (err * phi[i] - reg * self._weights[tier][i])

            self._is_fitted = True

    def select_tier(self, context: RoutingContext) -> ExecutionTier:
        """Select highest scoring execution tier for the given context."""
        with self._lock:
            if not self._is_fitted:
                # Fallback to deterministic baseline if un-fitted
                return DeterministicBaselineRouter().select_tier(context)

            phi = context.feature_vector()
            best_tier = ExecutionTier.TIER_1_COMPACT
            best_score = -float("inf")

            for tier in self._tiers:
                score = sum(w * f for w, f in zip(self._weights[tier], phi))
                # Hardware safety constraint: penalize deep tiers if headroom is critical
                if context.current_headroom_gb < 1.5 and tier in (
                    ExecutionTier.TIER_2_MIDSIZED,
                    ExecutionTier.TIER_3_DEEP,
                ):
                    score -= 2.0

                if score > best_score:
                    best_score = score
                    best_tier = tier

            return best_tier

    def trigger_online_training_attempt(self) -> None:
        """Explicitly enforce invariant: online self-training is strictly prohibited."""
        raise ModuleContractViolationError(
            "Online self-training is strictly prohibited adhering to ADR-008 and Boundary J safety."
        )

    def evaluate_against_baseline(
        self,
        eval_id: str,
        contexts: List[RoutingContext],
        reward_oracle: Callable[[RoutingContext, ExecutionTier], RoutingReward],
    ) -> PolicyEvaluationResult:
        """Run offline counterfactual evaluation comparing policy against deterministic baseline."""
        if not contexts:
            raise ModuleContractViolationError("Contexts list cannot be empty.")

        baseline_router = DeterministicBaselineRouter()
        policy_rewards: List[float] = []
        baseline_rewards: List[float] = []
        policy_latencies: List[float] = []
        baseline_latencies: List[float] = []
        policy_qualities: List[float] = []
        baseline_qualities: List[float] = []
        decision_counts: Dict[str, int] = {}

        for ctx in contexts:
            # Policy decision
            pol_tier = self.select_tier(ctx)
            pol_rew = reward_oracle(ctx, pol_tier)
            if not pol_rew.is_verified:
                raise PolicyRewardValidationError(
                    f"Invalid reward signal encountered for context '{ctx.context_id}'."
                )

            decision_counts[pol_tier.value] = decision_counts.get(pol_tier.value, 0) + 1
            policy_rewards.append(pol_rew.composite_reward)
            policy_latencies.append(pol_rew.latency_ms)
            policy_qualities.append(pol_rew.quality_score)

            # Baseline decision
            base_tier = baseline_router.select_tier(ctx)
            base_rew = reward_oracle(ctx, base_tier)
            if not base_rew.is_verified:
                raise PolicyRewardValidationError(
                    f"Invalid reward signal encountered for baseline context '{ctx.context_id}'."
                )

            baseline_rewards.append(base_rew.composite_reward)
            baseline_latencies.append(base_rew.latency_ms)
            baseline_qualities.append(base_rew.quality_score)

        n = len(contexts)
        pol_mean_rew = sum(policy_rewards) / n
        base_mean_rew = sum(baseline_rewards) / n
        rel_gain = pol_mean_rew - base_mean_rew

        pol_mean_lat = sum(policy_latencies) / n
        base_mean_lat = sum(baseline_latencies) / n

        pol_mean_qual = sum(policy_qualities) / n
        base_mean_qual = sum(baseline_qualities) / n

        # Activation Gate:
        # 1. Must improve on baseline composite reward (rel_gain > 0)
        # 2. Must not degrade quality score below baseline margin (-0.01)
        can_activate = (rel_gain > 0.0) and (pol_mean_qual >= (base_mean_qual - 0.01))

        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        return PolicyEvaluationResult(
            eval_id=eval_id,
            policy_name="OfflineContextualBandit-v1",
            baseline_name="DeterministicBaselineRouter",
            num_trials=n,
            policy_mean_reward=round(pol_mean_rew, 4),
            baseline_mean_reward=round(base_mean_rew, 4),
            relative_reward_gain=round(rel_gain, 4),
            policy_mean_latency_ms=round(pol_mean_lat, 2),
            baseline_mean_latency_ms=round(base_mean_lat, 2),
            policy_mean_quality=round(pol_mean_qual, 4),
            baseline_mean_quality=round(base_mean_qual, 4),
            is_activated=can_activate,
            timestamp_iso=now_iso,
            decisions_summary=decision_counts,
        )
