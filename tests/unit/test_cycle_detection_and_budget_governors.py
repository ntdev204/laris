"""Unit tests for cycle detection, recursion ceilings, and budget governors.

Covers Issue #67 (Subtask M7-ORCH-003-SUB-01):
- Dynamic cycle detection (duplicate tool dispatches, periodic repeating sequences)
- Hard recursion ceiling enforcement (N <= 10 steps maximum)
- Budget governor token and wall-clock timeout tracking
- Integrated DAGScheduler execution with cycle prevention and preemptive budget aborts
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional, Tuple

import pytest

from laris.core.errors import CycleDetectedError, ModuleContractViolationError
from laris.orchestration import (
    AgentRole,
    BudgetGovernor,
    BudgetLimits,
    CycleDetector,
    DAGScheduler,
    PlanDAG,
    TaskNode,
    TaskNodeStatus,
)

# ---------------------------------------------------------------------------
# 1. CycleDetector Unit Tests
# ---------------------------------------------------------------------------


def test_cycle_detector_duplicate_parameter_call() -> None:
    """Verifies that dispatching an identical (role, params) call twice raises error."""
    detector = CycleDetector(max_duplicate_calls=2)

    # First call is permitted
    detector.record_action(
        role=AgentRole.EVIDENCE_RETRIEVAL,
        parameters={"query": "superconductivity", "k": 10},
    )

    # Second call with identical arguments triggers CycleDetectedError
    with pytest.raises(CycleDetectedError) as exc_info:
        detector.record_action(
            role=AgentRole.EVIDENCE_RETRIEVAL,
            parameters={"query": "superconductivity", "k": 10},
        )
    assert "EVIDENCE_RETRIEVAL" in str(exc_info.value)
    assert "dispatched with identical arguments" in str(exc_info.value)


def test_cycle_detector_duplicate_description_call() -> None:
    """Verifies that dispatching an identical task description twice raises CycleDetectedError."""
    detector = CycleDetector(max_duplicate_calls=2)

    detector.record_action(
        role=AgentRole.CRITICAL_REVIEWER,
        description="Audit experimental methodology",
    )

    with pytest.raises(CycleDetectedError) as exc_info:
        detector.record_action(
            role=AgentRole.CRITICAL_REVIEWER,
            description="Audit experimental methodology",
        )
    assert "CRITICAL_REVIEWER" in str(exc_info.value)
    assert "Audit experimental methodology" in str(exc_info.value)


def test_cycle_detector_periodic_cycle_length_2() -> None:
    """Verifies that an alternating sequence (A -> B -> A -> B) triggers CycleDetectedError."""
    detector = CycleDetector(default_repetition_threshold=2)

    # Sequence: [LANGUAGE_ANALYSIS, DOCUMENT_ANALYSIS, LANGUAGE_ANALYSIS]
    detector.record_action(role=AgentRole.LANGUAGE_ANALYSIS, description="Task A1")
    detector.record_action(role=AgentRole.DOCUMENT_ANALYSIS, description="Task B1")
    detector.record_action(role=AgentRole.LANGUAGE_ANALYSIS, description="Task A2")

    # Completing the second period [LANGUAGE_ANALYSIS, DOCUMENT_ANALYSIS] triggers cycle
    with pytest.raises(CycleDetectedError) as exc_info:
        detector.record_action(role=AgentRole.DOCUMENT_ANALYSIS, description="Task B2")

    assert "Repeating agent cycle detected" in str(exc_info.value)
    assert "LANGUAGE_ANALYSIS -> DOCUMENT_ANALYSIS" in str(exc_info.value)


def test_cycle_detector_periodic_cycle_length_3() -> None:
    """Verifies that a 3-role sequence (A -> B -> C -> A -> B -> C) triggers CycleDetectedError."""
    detector = CycleDetector(default_repetition_threshold=2)

    pattern = [
        AgentRole.QUERY_PLANNER,
        AgentRole.EVIDENCE_RETRIEVAL,
        AgentRole.SCIENTIFIC_CLAIM,
    ]

    # First period
    for idx, role in enumerate(pattern):
        detector.record_action(role=role, description=f"P1-{idx}")

    # Second period: first two
    detector.record_action(role=pattern[0], description="P2-0")
    detector.record_action(role=pattern[1], description="P2-1")

    # Final repetition triggers error
    with pytest.raises(CycleDetectedError) as exc_info:
        detector.record_action(role=pattern[2], description="P2-2")

    assert "Repeating agent cycle detected" in str(exc_info.value)
    assert "QUERY_PLANNER -> EVIDENCE_RETRIEVAL -> SCIENTIFIC_CLAIM" in str(exc_info.value)


def test_cycle_detector_single_role_repetition() -> None:
    """Verifies that 3 consecutive invocations of the same role trigger CycleDetectedError."""
    detector = CycleDetector()

    detector.record_action(role=AgentRole.GAP_DISCOVERY, description="Step 1")
    detector.record_action(role=AgentRole.GAP_DISCOVERY, description="Step 2")

    # Third consecutive invocation triggers cycle detection
    with pytest.raises(CycleDetectedError) as exc_info:
        detector.record_action(role=AgentRole.GAP_DISCOVERY, description="Step 3")

    assert "Repeating agent cycle detected" in str(exc_info.value)
    assert "GAP_DISCOVERY" in str(exc_info.value)


def test_cycle_detector_clear_and_history() -> None:
    """Verifies history retrieval and detector state clearing."""
    detector = CycleDetector()
    detector.record_action(
        role=AgentRole.SUPERVISOR,
        parameters={"goal": "init"},
        task_id="t-init",
        description="Initialize workflow",
    )

    history = detector.get_history()
    assert len(history) == 1
    assert history[0][0] == AgentRole.SUPERVISOR
    assert history[0][2] == "t-init"

    detector.clear()
    assert len(detector.get_history()) == 0


# ---------------------------------------------------------------------------
# 2. BudgetGovernor Unit Tests
# ---------------------------------------------------------------------------


def test_budget_governor_hard_recursion_ceiling_invariant() -> None:
    """Verifies that BudgetGovernor rejects budget configurations exceeding ceiling 10."""
    bad_budget = object.__new__(BudgetLimits)
    object.__setattr__(bad_budget, "max_steps", 15)
    object.__setattr__(bad_budget, "max_tokens", 50000)
    object.__setattr__(bad_budget, "timeout_seconds", 60.0)

    with pytest.raises(ModuleContractViolationError) as exc_info:
        BudgetGovernor(bad_budget)
    assert "exceeds hard recursion ceiling of 10" in str(exc_info.value)


def test_budget_governor_step_limit_enforcement() -> None:
    """Verifies step checking and exhaustion when step limit is reached."""
    governor = BudgetGovernor(BudgetLimits(max_steps=3))
    assert governor.remaining_steps() == 3
    assert governor.is_exhausted() is False

    governor.check_step_allowance()
    governor.record_step(tokens_used=100)
    assert governor.remaining_steps() == 2

    governor.record_step(tokens_used=100)
    governor.record_step(tokens_used=100)
    assert governor.remaining_steps() == 0
    assert governor.is_exhausted() is True
    assert "Budget step limit reached: 3/3" in (governor.exhaustion_rationale() or "")

    with pytest.raises(ModuleContractViolationError) as exc_info:
        governor.check_step_allowance()
    assert "Hard recursion ceiling reached: 3 steps executed" in str(exc_info.value)


def test_budget_governor_token_limit_exhaustion() -> None:
    """Verifies token tracking and exhaustion when max_tokens is exceeded."""
    governor = BudgetGovernor(BudgetLimits(max_tokens=1000, max_steps=10))
    assert governor.remaining_tokens() == 1000
    assert governor.is_exhausted() is False

    governor.record_step(tokens_used=400)
    assert governor.remaining_tokens() == 600
    assert governor.is_exhausted() is False

    governor.record_step(tokens_used=700)
    assert governor.remaining_tokens() == 0
    assert governor.is_exhausted() is True
    assert "Token budget exceeded: 1100/1000" in (governor.exhaustion_rationale() or "")


def test_budget_governor_timeout_exhaustion() -> None:
    """Verifies elapsed time tracking and exhaustion on timeout."""
    governor = BudgetGovernor(BudgetLimits(timeout_seconds=0.01))
    time.sleep(0.02)
    assert governor.is_exhausted() is True
    assert "Execution timeout exceeded" in (governor.exhaustion_rationale() or "")
    assert governor.remaining_time_seconds() == 0.0


def test_budget_governor_invalid_metrics() -> None:
    """Verifies rejection of negative tokens and duration."""
    governor = BudgetGovernor()
    with pytest.raises(ModuleContractViolationError):
        governor.record_step(tokens_used=-5)
    with pytest.raises(ModuleContractViolationError):
        governor.record_step(tokens_used=10, duration_ms=-1.0)


# ---------------------------------------------------------------------------
# 3. Integrated DAGScheduler Execution with Cycle Detection & Budget Governors
# ---------------------------------------------------------------------------


def test_scheduler_detects_repeating_agent_cycle() -> None:
    """Verifies that DAGScheduler halts immediately with CycleDetectedError on repeating cycle."""
    scheduler = DAGScheduler()

    # Create a 4-node sequential DAG with repeating pattern: A -> B -> A -> B
    n1 = TaskNode("n1", AgentRole.LANGUAGE_ANALYSIS, "Task 1", parameters={"q": 1})
    n2 = TaskNode("n2", AgentRole.DOCUMENT_ANALYSIS, "Task 2", dependencies=["n1"])
    n3 = TaskNode(
        "n3", AgentRole.LANGUAGE_ANALYSIS, "Task 3", dependencies=["n2"], parameters={"q": 2}
    )
    n4 = TaskNode("n4", AgentRole.DOCUMENT_ANALYSIS, "Task 4", dependencies=["n3"])

    dag = PlanDAG("plan-cycle", "goal-cycle", {"n1": n1, "n2": n2, "n3": n3, "n4": n4})

    with pytest.raises(CycleDetectedError) as exc_info:
        scheduler.execute_dag(dag)

    assert "Repeating agent cycle detected" in str(exc_info.value)
    assert "LANGUAGE_ANALYSIS -> DOCUMENT_ANALYSIS" in str(exc_info.value)


def test_scheduler_preemptively_aborts_on_token_budget_exhaustion() -> None:
    """Verifies that exceeding token budget cancels remaining pending tasks."""
    scheduler = DAGScheduler()

    # 3-node sequential pipeline
    n1 = TaskNode("n1", AgentRole.EVIDENCE_RETRIEVAL, "Step 1")
    n2 = TaskNode("n2", AgentRole.SCIENTIFIC_CLAIM, "Step 2", dependencies=["n1"])
    n3 = TaskNode("n3", AgentRole.REPORT_COMPOSER, "Step 3", dependencies=["n2"])
    dag = PlanDAG("plan-token-budget", "goal-token", {"n1": n1, "n2": n2, "n3": n3})

    # Custom executor where step 1 consumes 1500 tokens, exceeding budget of 1000
    def heavy_token_executor(
        node: TaskNode,
        artifacts: Dict[str, Any],
    ) -> Tuple[TaskNodeStatus, Optional[Dict[str, Any]], Optional[str], int]:
        return TaskNodeStatus.COMPLETED, {"done": True}, None, 1500

    budget = BudgetLimits(max_tokens=1000, max_steps=10)
    executors = {AgentRole.EVIDENCE_RETRIEVAL: heavy_token_executor}

    result = scheduler.execute_dag(dag, budget=budget, executors=executors)

    assert result.status == TaskNodeStatus.CANCELLED
    assert "n2" in (result.failure_rationale or "")
    assert "n3" in (result.failure_rationale or "")
    # Check trace
    assert result.execution_trace[0].status == TaskNodeStatus.COMPLETED
    assert result.execution_trace[1].status == TaskNodeStatus.CANCELLED
    assert result.execution_trace[2].status == TaskNodeStatus.CANCELLED
    assert "Token budget exceeded" in (result.execution_trace[1].summary or "")


def test_budget_governor_properties() -> None:
    """Verifies that properties return accurate step and token counts."""
    governor = BudgetGovernor()
    assert governor.steps_executed == 0
    assert governor.tokens_consumed == 0
    governor.record_step(tokens_used=50, duration_ms=10.0)
    assert governor.steps_executed == 1
    assert governor.tokens_consumed == 50


def test_cycle_detector_non_json_serializable_parameters() -> None:
    """Verifies fallback string conversion when parameters cannot be serialized to JSON."""
    class CustomObj:
        def __repr__(self) -> str:
            return "custom_object"

    obj = CustomObj()
    detector = CycleDetector(max_duplicate_calls=2)
    detector.record_action(
        role=AgentRole.LANGUAGE_ANALYSIS,
        parameters={"obj": obj},
    )
    with pytest.raises(CycleDetectedError):
        detector.record_action(
            role=AgentRole.LANGUAGE_ANALYSIS,
            parameters={"obj": obj},
        )


def test_scheduler_preemptively_aborts_prior_to_node_when_governor_exhausted() -> None:
    """Verifies that an already exhausted budget governor aborts ready nodes immediately."""
    governor = BudgetGovernor(BudgetLimits(max_steps=1))
    assert governor.exhaustion_rationale() is None
    governor.record_step(tokens_used=10)
    scheduler = DAGScheduler(budget_governor=governor)

    n1 = TaskNode("n1", AgentRole.SUPERVISOR, "Task 1")
    dag = PlanDAG("plan-exhaust", "g1", {"n1": n1})

    result = scheduler.execute_dag(dag)
    assert result.status == TaskNodeStatus.CANCELLED
    assert result.execution_trace[0].status == TaskNodeStatus.CANCELLED
    assert "Budget step limit reached" in (result.execution_trace[0].summary or "")

