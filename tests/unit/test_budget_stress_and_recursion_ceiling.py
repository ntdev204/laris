"""Stress tests for hard recursion ceilings, resource governors, and cycle prevention.

Covers Issue #99 (Subtask M7-ORCH-003-SUB-02):
- Hard recursion ceiling (N <= 10) stress on large sequential and branching DAGs
- Preemptive cancellation under burst and incremental token budget exhaustion
- Wall-clock execution timeout enforcement under simulated delays
- Higher-order periodic cycle detection stress (k=4, k=5 repeating sequences)
- Complex non-cyclic workflow verification ensuring zero false-positive cycle triggers
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

import pytest

from laris.core.errors import CycleDetectedError, ModuleContractViolationError
from laris.layers.layer8_orchestration import (
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
# 1. Hard Recursion Ceiling Stress Tests (N <= 10)
# ---------------------------------------------------------------------------


def test_hard_recursion_ceiling_exact_10_steps() -> None:
    """Verifies that a 10-step DAG executes to full completion at the hard ceiling."""
    scheduler = DAGScheduler()
    roles = [
        AgentRole.SUPERVISOR,
        AgentRole.QUERY_PLANNER,
        AgentRole.LANGUAGE_ANALYSIS,
        AgentRole.DOCUMENT_ANALYSIS,
        AgentRole.EVIDENCE_RETRIEVAL,
        AgentRole.SCIENTIFIC_CLAIM,
        AgentRole.CROSS_PAPER_SYNTHESIS,
        AgentRole.GAP_DISCOVERY,
        AgentRole.CRITICAL_REVIEWER,
        AgentRole.REPORT_COMPOSER,
    ]
    nodes: Dict[str, TaskNode] = {}
    prev: Optional[str] = None
    for i, role in enumerate(roles):
        nid = f"step_{i}"
        deps = [prev] if prev else []
        nodes[nid] = TaskNode(
            node_id=nid,
            agent_role=role,
            description=f"Execution step {i}",
            dependencies=deps,
        )
        prev = nid

    dag = PlanDAG("plan-10-steps", "goal-10", nodes)
    budget = BudgetLimits(max_steps=10)
    result = scheduler.execute_dag(dag, budget=budget)

    assert result.status == TaskNodeStatus.COMPLETED
    assert result.resource_usage.total_steps == 10
    assert len(result.final_artifacts) == 10
    assert len(result.execution_trace) == 10
    assert all(step.status == TaskNodeStatus.COMPLETED for step in result.execution_trace)


def test_hard_recursion_ceiling_exceeding_10_steps_truncation() -> None:
    """Verifies that an oversized pipeline (15 tasks) is truncated at 10 steps."""
    scheduler = DAGScheduler()
    roles = [
        AgentRole.SUPERVISOR,
        AgentRole.QUERY_PLANNER,
        AgentRole.LANGUAGE_ANALYSIS,
        AgentRole.DOCUMENT_ANALYSIS,
        AgentRole.EVIDENCE_RETRIEVAL,
        AgentRole.SCIENTIFIC_CLAIM,
        AgentRole.CROSS_PAPER_SYNTHESIS,
        AgentRole.GAP_DISCOVERY,
        AgentRole.CRITICAL_REVIEWER,
        AgentRole.REPORT_COMPOSER,
        AgentRole.SUPERVISOR,
        AgentRole.QUERY_PLANNER,
        AgentRole.LANGUAGE_ANALYSIS,
        AgentRole.DOCUMENT_ANALYSIS,
        AgentRole.EVIDENCE_RETRIEVAL,
    ]
    nodes: Dict[str, TaskNode] = {}
    prev: Optional[str] = None
    for i, role in enumerate(roles):
        nid = f"step_{i}"
        deps = [prev] if prev else []
        nodes[nid] = TaskNode(
            node_id=nid,
            agent_role=role,
            description=f"Oversized step {i}",
            dependencies=deps,
        )
        prev = nid

    dag = PlanDAG("plan-15-steps", "goal-15", nodes)
    budget = BudgetLimits(max_steps=10)
    result = scheduler.execute_dag(dag, budget=budget)

    assert result.status == TaskNodeStatus.CANCELLED
    # First 10 completed
    completed_steps = [s for s in result.execution_trace if s.status == TaskNodeStatus.COMPLETED]
    assert len(completed_steps) == 10
    # Remaining 5 cancelled
    cancelled_steps = [s for s in result.execution_trace if s.status == TaskNodeStatus.CANCELLED]
    assert len(cancelled_steps) == 5
    for s in cancelled_steps:
        assert "hard step limit reached" in (s.summary or "")


def test_branching_dag_step_ceiling_stress() -> None:
    """Verifies step ceiling enforcement across a fan-out / fan-in branching DAG."""
    scheduler = DAGScheduler()
    nodes: Dict[str, TaskNode] = {}

    # Root task
    nodes["root"] = TaskNode("root", AgentRole.SUPERVISOR, "Root coordination")

    # 6 parallel worker tasks
    worker_roles = [
        AgentRole.QUERY_PLANNER,
        AgentRole.LANGUAGE_ANALYSIS,
        AgentRole.DOCUMENT_ANALYSIS,
        AgentRole.EVIDENCE_RETRIEVAL,
        AgentRole.SCIENTIFIC_CLAIM,
        AgentRole.CROSS_PAPER_SYNTHESIS,
    ]
    worker_ids: List[str] = []
    for idx, role in enumerate(worker_roles):
        wid = f"w_{idx}"
        worker_ids.append(wid)
        nodes[wid] = TaskNode(wid, role, f"Worker {idx}", dependencies=["root"])

    # Convergence task
    nodes["join"] = TaskNode(
        "join", AgentRole.REPORT_COMPOSER, "Synthesize report", dependencies=worker_ids
    )

    dag = PlanDAG("plan-branching", "goal-branching", nodes)
    # Total nodes = 8. Set budget limit to 4 steps.
    budget = BudgetLimits(max_steps=4)
    result = scheduler.execute_dag(dag, budget=budget)

    assert result.status == TaskNodeStatus.CANCELLED
    completed = [s for s in result.execution_trace if s.status == TaskNodeStatus.COMPLETED]
    cancelled = [s for s in result.execution_trace if s.status == TaskNodeStatus.CANCELLED]
    assert len(completed) == 4
    assert len(cancelled) == 4


# ---------------------------------------------------------------------------
# 2. Resource Budget Stress Tests (Tokens and Timeout)
# ---------------------------------------------------------------------------


def test_burst_token_budget_exhaustion_stress() -> None:
    """Verifies preemptive cancellation when an execution step consumes excess tokens."""
    scheduler = DAGScheduler()

    # 4-node linear pipeline
    n1 = TaskNode("n1", AgentRole.QUERY_PLANNER, "Step 1")
    n2 = TaskNode("n2", AgentRole.EVIDENCE_RETRIEVAL, "Step 2", dependencies=["n1"])
    n3 = TaskNode("n3", AgentRole.SCIENTIFIC_CLAIM, "Step 3", dependencies=["n2"])
    n4 = TaskNode("n4", AgentRole.REPORT_COMPOSER, "Step 4", dependencies=["n3"])
    dag = PlanDAG("plan-burst", "goal-burst", {"n1": n1, "n2": n2, "n3": n3, "n4": n4})

    # Step 1 consumes 1,000 tokens, Step 2 consumes 5,000 tokens. Total = 6,000 > 5,000 max.
    def variable_token_executor(
        node: TaskNode,
        artifacts: Dict[str, Any],
    ) -> Tuple[TaskNodeStatus, Optional[Dict[str, Any]], Optional[str], int]:
        tokens = 1000 if node.node_id == "n1" else 5000
        return TaskNodeStatus.COMPLETED, {"done": node.node_id}, None, tokens

    budget = BudgetLimits(max_tokens=5000, max_steps=10)
    executors = {
        AgentRole.QUERY_PLANNER: variable_token_executor,
        AgentRole.EVIDENCE_RETRIEVAL: variable_token_executor,
    }

    result = scheduler.execute_dag(dag, budget=budget, executors=executors)

    assert result.status == TaskNodeStatus.CANCELLED
    assert result.resource_usage.total_tokens_used == 6000
    # Steps 1 and 2 completed; steps 3 and 4 cancelled
    statuses = [s.status for s in result.execution_trace]
    assert statuses == [
        TaskNodeStatus.COMPLETED,
        TaskNodeStatus.COMPLETED,
        TaskNodeStatus.CANCELLED,
        TaskNodeStatus.CANCELLED,
    ]
    assert "Token budget exceeded" in (result.execution_trace[2].summary or "")


def test_wall_clock_timeout_budget_stress() -> None:
    """Verifies that exceeding wall-clock timeout cancels unstarted nodes."""
    scheduler = DAGScheduler()

    n1 = TaskNode("n1", AgentRole.LANGUAGE_ANALYSIS, "Fast task")
    n2 = TaskNode("n2", AgentRole.DOCUMENT_ANALYSIS, "Slow task", dependencies=["n1"])
    n3 = TaskNode("n3", AgentRole.REPORT_COMPOSER, "Pending task", dependencies=["n2"])
    dag = PlanDAG("plan-timeout", "goal-timeout", {"n1": n1, "n2": n2, "n3": n3})

    def slow_executor(
        node: TaskNode,
        artifacts: Dict[str, Any],
    ) -> Tuple[TaskNodeStatus, Optional[Dict[str, Any]], Optional[str], int]:
        if node.node_id == "n2":
            time.sleep(0.04)
        return TaskNodeStatus.COMPLETED, {"done": True}, None, 100

    budget = BudgetLimits(timeout_seconds=0.03, max_steps=10)
    executors = {
        AgentRole.LANGUAGE_ANALYSIS: slow_executor,
        AgentRole.DOCUMENT_ANALYSIS: slow_executor,
    }

    result = scheduler.execute_dag(dag, budget=budget, executors=executors)

    assert result.status == TaskNodeStatus.CANCELLED
    # Step 3 must be cancelled due to timeout
    assert result.execution_trace[2].status == TaskNodeStatus.CANCELLED
    assert "timeout" in (result.execution_trace[2].summary or "").lower()


# ---------------------------------------------------------------------------
# 3. Higher-Order Cycle Detection Stress Tests (k=4, k=5)
# ---------------------------------------------------------------------------


def test_higher_order_cycle_length_4_stress() -> None:
    """Verifies detection of 4-agent repeating sequence (A -> B -> C -> D -> A -> B -> C -> D)."""
    detector = CycleDetector(default_repetition_threshold=2)
    cycle_roles = [
        AgentRole.QUERY_PLANNER,
        AgentRole.LANGUAGE_ANALYSIS,
        AgentRole.DOCUMENT_ANALYSIS,
        AgentRole.EVIDENCE_RETRIEVAL,
    ]

    # First period of 4
    for idx, r in enumerate(cycle_roles):
        detector.record_action(r, description=f"P1-{idx}")

    # Second period: first 3
    for idx in range(3):
        detector.record_action(cycle_roles[idx], description=f"P2-{idx}")

    # Fourth action of second period completes the cycle
    with pytest.raises(CycleDetectedError) as exc_info:
        detector.record_action(cycle_roles[3], description="P2-3")

    assert "Repeating agent cycle detected" in str(exc_info.value)
    assert "QUERY_PLANNER -> LANGUAGE_ANALYSIS -> DOCUMENT_ANALYSIS -> EVIDENCE_RETRIEVAL" in str(
        exc_info.value
    )


def test_higher_order_cycle_length_5_stress() -> None:
    """Verifies detection of 5-agent repeating sequence."""
    detector = CycleDetector(default_repetition_threshold=2)
    cycle_roles = [
        AgentRole.SUPERVISOR,
        AgentRole.QUERY_PLANNER,
        AgentRole.EVIDENCE_RETRIEVAL,
        AgentRole.SCIENTIFIC_CLAIM,
        AgentRole.CRITICAL_REVIEWER,
    ]

    # First period of 5
    for idx, r in enumerate(cycle_roles):
        detector.record_action(r, description=f"P1-{idx}")

    # Second period: first 4
    for idx in range(4):
        detector.record_action(cycle_roles[idx], description=f"P2-{idx}")

    # Fifth action triggers cycle error
    with pytest.raises(CycleDetectedError) as exc_info:
        detector.record_action(cycle_roles[4], description="P2-4")

    assert "Repeating agent cycle detected" in str(exc_info.value)


def test_complex_non_cyclic_workflow_zero_false_positives() -> None:
    """Verifies that diverse non-repeating agent execution triggers zero false positives."""
    detector = CycleDetector(default_repetition_threshold=2)
    diverse_roles = [
        AgentRole.SUPERVISOR,
        AgentRole.QUERY_PLANNER,
        AgentRole.LANGUAGE_ANALYSIS,
        AgentRole.DOCUMENT_ANALYSIS,
        AgentRole.EVIDENCE_RETRIEVAL,
        AgentRole.SCIENTIFIC_CLAIM,
        AgentRole.CROSS_PAPER_SYNTHESIS,
        AgentRole.GAP_DISCOVERY,
        AgentRole.CRITICAL_REVIEWER,
        AgentRole.REPORT_COMPOSER,
    ]

    for idx, r in enumerate(diverse_roles):
        detector.record_action(r, description=f"Distinct task {idx}")

    assert len(detector.get_history()) == 10


def test_budget_governor_high_iteration_tracking_stress() -> None:
    """Verifies budget governor resource accounting across multi-step iterations."""
    governor = BudgetGovernor(BudgetLimits(max_steps=10, max_tokens=20000))

    for step_num in range(10):
        governor.check_step_allowance()
        governor.record_step(tokens_used=1500, duration_ms=25.0)

    assert governor.steps_executed == 10
    assert governor.tokens_consumed == 15000
    assert governor.remaining_steps() == 0
    assert governor.remaining_tokens() == 5000
    assert governor.is_exhausted() is True

    # Attempting 11th step raises error
    with pytest.raises(ModuleContractViolationError):
        governor.check_step_allowance()
