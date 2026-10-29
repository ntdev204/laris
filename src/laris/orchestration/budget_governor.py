"""Budget governor enforcing recursion ceiling and resource limits in Layer 8.

Adheres to DOC-SPEC-MOD-001 (Boundary H), DOC-SPEC-ORCH-001, ADR-006, and Issue #67:
- Enforces hard recursion ceiling (N <= 10 steps maximum per sub-goal)
- Tracks cumulative token consumption against budget.max_tokens
- Tracks cumulative execution wall-clock time against budget.timeout_seconds
- Preemptively signals budget exhaustion to halt runaway execution
"""

from __future__ import annotations

import time
from typing import Callable, Optional

from laris.core.errors import ModuleContractViolationError
from laris.orchestration.schemas import BudgetLimits


class BudgetGovernor:
    """Enforces execution step ceilings and resource budget limits."""

    def __init__(
        self,
        budget: Optional[BudgetLimits] = None,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        """Initializes BudgetGovernor with specified budget limits."""
        self.budget = budget or BudgetLimits()
        # Verify hard ceiling invariant
        if self.budget.max_steps > 10:
            raise ModuleContractViolationError(
                f"Budget step limit ({self.budget.max_steps}) exceeds hard recursion "
                "ceiling of 10."
            )
        self._start_time = time.perf_counter()
        self._steps_executed = 0
        self._tokens_consumed = 0
        self._total_duration_ms = 0.0

    def check_step_allowance(self) -> None:
        """Checks whether an additional execution step is permitted by the budget.

        Raises:
            ModuleContractViolationError: If steps_executed has reached or exceeded max_steps.
        """
        if self._steps_executed >= self.budget.max_steps:
            raise ModuleContractViolationError(
                f"Hard recursion ceiling reached: {self._steps_executed} steps executed "
                f"(max allowed: {self.budget.max_steps})."
            )

    def record_step(self, tokens_used: int, duration_ms: float = 0.0) -> None:
        """Records the execution of a task step and increments resource counters."""
        if tokens_used < 0:
            raise ModuleContractViolationError(
                f"tokens_used ({tokens_used}) must be non-negative."
            )
        if duration_ms < 0.0:
            raise ModuleContractViolationError(
                f"duration_ms ({duration_ms}) must be non-negative."
            )

        self._steps_executed += 1
        self._tokens_consumed += tokens_used
        self._total_duration_ms += duration_ms

    def is_exhausted(self) -> bool:
        """Returns True if step limit, token limit, or timeout limit is exceeded."""
        if self._steps_executed >= self.budget.max_steps:
            return True
        if self._tokens_consumed >= self.budget.max_tokens:
            return True
        elapsed_sec = time.perf_counter() - self._start_time
        if elapsed_sec >= self.budget.timeout_seconds:
            return True
        return False

    def exhaustion_rationale(self) -> Optional[str]:
        """Provides a detailed diagnostic message if any budget ceiling is exhausted."""
        if self._steps_executed >= self.budget.max_steps:
            return (
                f"Budget step limit reached: {self._steps_executed}/{self.budget.max_steps} "
                "steps executed."
            )
        if self._tokens_consumed >= self.budget.max_tokens:
            return (
                f"Token budget exceeded: {self._tokens_consumed}/{self.budget.max_tokens} "
                "tokens consumed."
            )
        elapsed_sec = time.perf_counter() - self._start_time
        if elapsed_sec >= self.budget.timeout_seconds:
            return (
                f"Execution timeout exceeded: {elapsed_sec:.1f}s/"
                f"{self.budget.timeout_seconds:.1f}s elapsed."
            )
        return None

    @property
    def steps_executed(self) -> int:
        """Number of execution steps completed so far."""
        return self._steps_executed

    @property
    def tokens_consumed(self) -> int:
        """Cumulative tokens consumed so far."""
        return self._tokens_consumed

    def remaining_steps(self) -> int:
        """Returns remaining steps before reaching max_steps."""
        return max(0, self.budget.max_steps - self._steps_executed)

    def remaining_tokens(self) -> int:
        """Returns remaining tokens before reaching max_tokens."""
        return max(0, self.budget.max_tokens - self._tokens_consumed)

    def remaining_time_seconds(self) -> float:
        """Returns remaining wall-clock seconds before reaching timeout_seconds."""
        elapsed = time.perf_counter() - self._start_time
        return max(0.0, self.budget.timeout_seconds - elapsed)
