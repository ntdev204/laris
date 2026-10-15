"""Unit and integration tests for DAG scheduling, failure propagation, and cancellation.

Adheres to DOC-SPEC-MOD-001 (Boundary H), ADR-006, and Issue #97:
- Tests valid topological scheduling across linear and branched pipeline topologies
- Tests automatic failure propagation skipping downstream dependents of failed tasks
- Tests cooperative cancellation and execution trace integrity
- Tests budget step limit enforcement and pre-execution validation
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import pytest

from laris.core.errors import CycleDetectedError, ModuleContractViolationError
from laris.layers.layer8_orchestration import (
    AgentRole,
    BudgetLimits,
    DAGScheduler,
    PlanDAG,
    TaskNode,
    TaskNodeStatus,
)


@pytest.fixture
def scheduler() -> DAGScheduler:
    """Provides a fresh DAGScheduler instance."""
    return DAGScheduler()


def test_scheduler_linear_pipeline_success(scheduler: DAGScheduler) -> None:
    """Tests full execution of a 4-step linear pipeline with trace integrity."""
    n1 = TaskNode("n1", AgentRole.QUERY_PLANNER, "Decompose research question")
    n2 = TaskNode(
        "n2",
        AgentRole.EVIDENCE_RETRIEVAL,
        "Retrieve evidence coordinates",
        dependencies=["n1"],
    )
    n3 = TaskNode("n3", AgentRole.SCIENTIFIC_CLAIM, "Extract factual claims", dependencies=["n2"])
    n4 = TaskNode("n4", AgentRole.REPORT_COMPOSER, "Compose research report", dependencies=["n3"])

    dag = PlanDAG("plan-linear", "goal-01", {"n1": n1, "n2": n2, "n3": n3, "n4": n4})
    result = scheduler.execute_dag(dag)

    assert result.status == TaskNodeStatus.COMPLETED
    assert result.failure_rationale is None
    assert len(result.final_artifacts) == 4
    assert len(result.execution_trace) == 4

    # Verify sequential monotonic step indices
    for i, step in enumerate(result.execution_trace):
        assert step.step_index == i
        assert step.status == TaskNodeStatus.COMPLETED
        assert step.duration_ms >= 0.0
        assert step.tokens_used > 0
        assert "2026" in step.started_at_iso
        assert "2026" in step.completed_at_iso

    # Verify resource usage
    assert result.resource_usage.total_steps == 4
    assert result.resource_usage.total_tokens_used == 4 * 150
    assert result.resource_usage.total_duration_ms >= 0.0


def test_scheduler_diamond_pipeline_artifacts(scheduler: DAGScheduler) -> None:
    """Verifies that join nodes receive artifacts produced by multiple upstream branches."""
    n1 = TaskNode("n1", AgentRole.QUERY_PLANNER, "Plan")
    n2 = TaskNode("n2", AgentRole.LANGUAGE_ANALYSIS, "Lang analysis", dependencies=["n1"])
    n3 = TaskNode("n3", AgentRole.DOCUMENT_ANALYSIS, "Doc analysis", dependencies=["n1"])
    n4 = TaskNode("n4", AgentRole.CROSS_PAPER_SYNTHESIS, "Synthesize", dependencies=["n2", "n3"])

    dag = PlanDAG("plan-diamond", "goal-02", {"n1": n1, "n2": n2, "n3": n3, "n4": n4})
    result = scheduler.execute_dag(dag)

    assert result.status == TaskNodeStatus.COMPLETED
    assert len(result.final_artifacts) == 4

    synth_artifact = result.final_artifacts["n4"]
    assert "n2" in synth_artifact["upstream_artifacts"]
    assert "n3" in synth_artifact["upstream_artifacts"]


def test_scheduler_task_failure_propagation(scheduler: DAGScheduler) -> None:
    """Verifies that a failed task skips downstream dependents while allowing parallel tasks."""
    # Topology:
    #   n1 -> n2 -> n3 (n2 fails, so n3 must be SKIPPED)
    #   n1 -> n4 (independent branch, must SUCCEED)
    n1 = TaskNode("n1", AgentRole.QUERY_PLANNER, "Plan research")
    n2 = TaskNode("n2", AgentRole.EVIDENCE_RETRIEVAL, "Failing retrieval", dependencies=["n1"])
    n3 = TaskNode("n3", AgentRole.SCIENTIFIC_CLAIM, "Extract claims", dependencies=["n2"])
    n4 = TaskNode(
        "n4",
        AgentRole.LANGUAGE_ANALYSIS,
        "Independent token analysis",
        dependencies=["n1"],
    )

    dag = PlanDAG("plan-fail-prop", "goal-03", {"n1": n1, "n2": n2, "n3": n3, "n4": n4})

    # Custom executor causing n2 to fail
    def failing_retrieval_executor(
        node: TaskNode,
        artifacts: Dict[str, Any],
    ) -> Tuple[TaskNodeStatus, Optional[Dict[str, Any]], Optional[str], int]:
        if node.node_id == "n2":
            return TaskNodeStatus.FAILED, None, "Database connection timeout.", 50
        return TaskNodeStatus.COMPLETED, {"node": node.node_id}, None, 100

    result = scheduler.execute_dag(
        dag,
        executors={AgentRole.EVIDENCE_RETRIEVAL: failing_retrieval_executor},
    )

    assert result.status == TaskNodeStatus.FAILED
    assert result.failure_rationale is not None
    assert "Execution failed on nodes: ['n2']" in result.failure_rationale
    assert "skipped dependent nodes: ['n3']" in result.failure_rationale

    # n1 and n4 completed, n2 failed, n3 skipped
    trace_map = {step.node_id: step.status for step in result.execution_trace}
    assert trace_map["n1"] == TaskNodeStatus.COMPLETED
    assert trace_map["n2"] == TaskNodeStatus.FAILED
    assert trace_map["n3"] == TaskNodeStatus.SKIPPED
    assert trace_map["n4"] == TaskNodeStatus.COMPLETED

    # Artifacts exist only for completed nodes
    assert "n1" in result.final_artifacts
    assert "n4" in result.final_artifacts
    assert "n2" not in result.final_artifacts
    assert "n3" not in result.final_artifacts


def test_scheduler_unhandled_exception_handling(scheduler: DAGScheduler) -> None:
    """Verifies that unhandled exceptions in agent executors are caught and marked FAILED."""
    n1 = TaskNode("n1", AgentRole.CRITICAL_REVIEWER, "Run review")
    dag = PlanDAG("plan-crash", "goal-04", {"n1": n1})

    def crashing_executor(
        node: TaskNode,
        artifacts: Dict[str, Any],
    ) -> Tuple[TaskNodeStatus, Optional[Dict[str, Any]], Optional[str], int]:
        raise RuntimeError("Simulated internal agent crash.")

    result = scheduler.execute_dag(
        dag,
        executors={AgentRole.CRITICAL_REVIEWER: crashing_executor},
    )

    assert result.status == TaskNodeStatus.FAILED
    assert "Simulated internal agent crash" in (result.failure_rationale or "")
    assert result.execution_trace[0].status == TaskNodeStatus.FAILED


def test_scheduler_cooperative_cancellation(scheduler: DAGScheduler) -> None:
    """Verifies that cancel_before_node terminates unstarted tasks cleanly."""
    n1 = TaskNode("n1", AgentRole.QUERY_PLANNER, "Step 1")
    n2 = TaskNode("n2", AgentRole.EVIDENCE_RETRIEVAL, "Step 2", dependencies=["n1"])
    n3 = TaskNode("n3", AgentRole.SCIENTIFIC_CLAIM, "Step 3", dependencies=["n2"])

    dag = PlanDAG("plan-cancel", "goal-05", {"n1": n1, "n2": n2, "n3": n3})
    result = scheduler.execute_dag(dag, cancel_before_node="n2")

    assert result.status == TaskNodeStatus.CANCELLED
    assert result.failure_rationale is not None
    assert "Execution cancelled on nodes" in result.failure_rationale

    # Step 1 completed, Steps 2 and 3 cancelled
    trace_statuses = [step.status for step in result.execution_trace]
    assert trace_statuses[0] == TaskNodeStatus.COMPLETED
    assert trace_statuses[1] == TaskNodeStatus.CANCELLED
    assert trace_statuses[2] == TaskNodeStatus.CANCELLED


def test_scheduler_hard_recursion_budget_limit(scheduler: DAGScheduler) -> None:
    """Verifies that exceeding the configured max_steps aborts unstarted nodes."""
    # Pipeline of 5 tasks with budget of max 2 steps
    nodes = {}
    prev: Optional[str] = None
    for i in range(5):
        nid = f"n{i}"
        deps: list[str] = [prev] if prev else []
        nodes[nid] = TaskNode(nid, AgentRole.SUPERVISOR, f"Task {i}", dependencies=deps)
        prev = nid

    dag = PlanDAG("plan-budget", "goal-06", nodes)
    budget = BudgetLimits(max_steps=2)

    result = scheduler.execute_dag(dag, budget=budget)

    assert result.status == TaskNodeStatus.CANCELLED
    # First 2 completed, remaining 3 cancelled
    completed = [s for s in result.execution_trace if s.status == TaskNodeStatus.COMPLETED]
    cancelled = [s for s in result.execution_trace if s.status == TaskNodeStatus.CANCELLED]
    assert len(completed) == 2
    assert len(cancelled) == 3


def test_scheduler_pre_execution_validation_failures(scheduler: DAGScheduler) -> None:
    """Verifies that invalid DAGs or budgets are caught prior to executing any steps."""
    # Cyclic DAG (simulated)
    na = TaskNode("na", AgentRole.SUPERVISOR, "A", dependencies=["nb"])
    nb = TaskNode("nb", AgentRole.QUERY_PLANNER, "B", dependencies=["na"])

    # PlanDAG post_init already catches cycles, but if bypassed:
    with pytest.raises(CycleDetectedError):
        PlanDAG("plan-bad", "g1", {"na": na, "nb": nb})

    # Invalid budget limit
    valid_node = TaskNode("n1", AgentRole.SUPERVISOR, "Task")
    valid_dag = PlanDAG("plan-valid", "g1", {"n1": valid_node})

    bad_budget = object.__new__(BudgetLimits)
    object.__setattr__(bad_budget, "max_steps", 15)
    object.__setattr__(bad_budget, "max_tokens", 1000)
    object.__setattr__(bad_budget, "timeout_seconds", 100.0)

    with pytest.raises(ModuleContractViolationError, match="exceeds hard recursion ceiling"):
        scheduler.execute_dag(valid_dag, budget=bad_budget)
