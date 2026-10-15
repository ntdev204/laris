"""Deterministic DAG scheduler and supervisor runtime for Layer 8 Agent Orchestration.

Adheres to DOC-SPEC-MOD-001 (Boundary H), ADR-006, and Issue #97:
- Scheduled execution of PlanDAG task nodes in topological dependency order
- Automatic failure propagation skipping downstream dependents of failed tasks
- Cooperative cancellation terminating unstarted tasks gracefully
- Deterministic execution trace logging with step indices and resource usage
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from laris.layers.layer8_orchestration.budget_governor import BudgetGovernor
from laris.layers.layer8_orchestration.cycle_detector import CycleDetector
from laris.layers.layer8_orchestration.dag_validator import DAGValidator
from laris.layers.layer8_orchestration.schemas import (
    AgentRole,
    AgentStep,
    BudgetLimits,
    OrchestrationResult,
    PlanDAG,
    ResourceUsage,
    TaskNode,
    TaskNodeStatus,
)

# Signature: (node, artifacts_so_far) -> (status, output_artifact, error_message, tokens_used)
NodeExecutor = Callable[
    [TaskNode, Dict[str, Any]],
    Tuple[TaskNodeStatus, Optional[Dict[str, Any]], Optional[str], int],
]


def default_node_executor(
    node: TaskNode,
    artifacts: Dict[str, Any],
) -> Tuple[TaskNodeStatus, Optional[Dict[str, Any]], Optional[str], int]:
    """Default synthetic executor simulating specialist agent task completion."""
    output = {
        "node_id": node.node_id,
        "role": node.agent_role.value,
        "summary": f"Executed {node.description}",
        "upstream_artifacts": list(artifacts.keys()),
    }
    return TaskNodeStatus.COMPLETED, output, None, 150


def _cancel_remaining_pending_nodes(
    node_states: Dict[str, TaskNode],
    cancelled_nodes: Set[str],
    trace: List[AgentStep],
    step_counter: int,
    error_message: str,
    summary: str,
) -> int:
    """Cancels all currently pending nodes in node_states and records cancellation trace steps."""
    for remaining_id, remaining_node in node_states.items():
        if remaining_node.status == TaskNodeStatus.PENDING:
            cancelled_node = TaskNode(
                node_id=remaining_node.node_id,
                agent_role=remaining_node.agent_role,
                description=remaining_node.description,
                dependencies=remaining_node.dependencies,
                parameters=remaining_node.parameters,
                status=TaskNodeStatus.CANCELLED,
                error_message=error_message,
            )
            node_states[remaining_id] = cancelled_node
            cancelled_nodes.add(remaining_id)
            trace.append(
                AgentStep(
                    step_index=step_counter,
                    node_id=remaining_id,
                    agent_role=remaining_node.agent_role,
                    started_at_iso=datetime.now(timezone.utc).isoformat(),
                    completed_at_iso=datetime.now(timezone.utc).isoformat(),
                    duration_ms=0.0,
                    status=TaskNodeStatus.CANCELLED,
                    tokens_used=0,
                    summary=summary,
                )
            )
            step_counter += 1
    return step_counter


class DAGScheduler:
    """Schedules and executes PlanDAG workflows with failure propagation and tracing."""

    def __init__(
        self,
        validator: Optional[DAGValidator] = None,
        default_executor: Optional[NodeExecutor] = None,
        cycle_detector: Optional[CycleDetector] = None,
        budget_governor: Optional[BudgetGovernor] = None,
    ) -> None:
        self.validator = validator or DAGValidator()
        self.default_executor = default_executor or default_node_executor
        self.cycle_detector = cycle_detector
        self.budget_governor = budget_governor

    def execute_dag(
        self,
        dag: PlanDAG,
        budget: Optional[BudgetLimits] = None,
        executors: Optional[Dict[AgentRole, NodeExecutor]] = None,
        cancel_before_node: Optional[str] = None,
    ) -> OrchestrationResult:
        """Executes the task nodes of a PlanDAG adhering to dependencies and budget."""
        effective_budget = budget or BudgetLimits()
        self.validator.validate_budget_limits(effective_budget)
        self.validator.validate_dag(dag)

        detector = self.cycle_detector or CycleDetector()
        governor = self.budget_governor or BudgetGovernor(effective_budget)

        custom_executors = executors or {}
        node_states: Dict[str, TaskNode] = dict(dag.nodes)
        artifacts: Dict[str, Any] = {}
        completed_nodes: Set[str] = set()
        failed_nodes: Set[str] = set()
        skipped_nodes: Set[str] = set()
        cancelled_nodes: Set[str] = set()
        trace: List[AgentStep] = []

        step_counter = 0
        total_tokens = 0
        t_start = time.perf_counter()

        while True:
            # Identify pending nodes whose dependencies are completely satisfied
            ready_nodes: List[TaskNode] = []
            for node_id, node in node_states.items():
                if node.status == TaskNodeStatus.PENDING:
                    if all(dep in completed_nodes for dep in node.dependencies):
                        ready_nodes.append(node)

            if not ready_nodes:
                break

            for curr_node in ready_nodes:
                # Check cooperative cancellation target
                if cancel_before_node is not None and curr_node.node_id == cancel_before_node:
                    step_counter = _cancel_remaining_pending_nodes(
                        node_states=node_states,
                        cancelled_nodes=cancelled_nodes,
                        trace=trace,
                        step_counter=step_counter,
                        error_message="Execution cancelled by caller.",
                        summary="Task cancelled before execution.",
                    )
                    break

                # Enforce budget step ceiling and governor exhaustion
                if step_counter >= effective_budget.max_steps or governor.is_exhausted():
                    rationale = governor.exhaustion_rationale() or "Budget step limit reached."
                    cancel_msg = (
                        "Budget step limit reached."
                        if step_counter >= effective_budget.max_steps
                        else rationale
                    )
                    summary = (
                        "Aborted: hard step limit reached."
                        if step_counter >= effective_budget.max_steps
                        else f"Aborted: {rationale}"
                    )
                    step_counter = _cancel_remaining_pending_nodes(
                        node_states=node_states,
                        cancelled_nodes=cancelled_nodes,
                        trace=trace,
                        step_counter=step_counter,
                        error_message=cancel_msg,
                        summary=summary,
                    )
                    break

                # Cycle detection on node execution
                detector.record_action(
                    role=curr_node.agent_role,
                    parameters=curr_node.parameters,
                    task_id=curr_node.node_id,
                    description=curr_node.description,
                )

                # Select executor for node's agent role
                executor = custom_executors.get(curr_node.agent_role, self.default_executor)
                t_node_start = time.perf_counter()
                iso_start = datetime.now(timezone.utc).isoformat()

                try:
                    status, output, err_msg, tokens = executor(curr_node, artifacts)
                except Exception as exc:
                    status = TaskNodeStatus.FAILED
                    output = None
                    err_msg = f"Unhandled exception during execution: {exc}"
                    tokens = 0

                t_node_end = time.perf_counter()
                iso_end = datetime.now(timezone.utc).isoformat()
                dur_ms = round((t_node_end - t_node_start) * 1000.0, 2)
                total_tokens += tokens

                updated_node = TaskNode(
                    node_id=curr_node.node_id,
                    agent_role=curr_node.agent_role,
                    description=curr_node.description,
                    dependencies=curr_node.dependencies,
                    parameters=curr_node.parameters,
                    status=status,
                    output_artifact=output,
                    error_message=err_msg,
                )
                node_states[curr_node.node_id] = updated_node

                trace.append(
                    AgentStep(
                        step_index=step_counter,
                        node_id=curr_node.node_id,
                        agent_role=curr_node.agent_role,
                        started_at_iso=iso_start,
                        completed_at_iso=iso_end,
                        duration_ms=dur_ms,
                        status=status,
                        tokens_used=tokens,
                        summary=f"{status.value}: {curr_node.description}",
                    )
                )
                step_counter += 1

                # Record step in budget governor
                governor.record_step(tokens_used=tokens, duration_ms=dur_ms)

                if status == TaskNodeStatus.COMPLETED:
                    completed_nodes.add(curr_node.node_id)
                    if output is not None:
                        artifacts[curr_node.node_id] = output

                elif status == TaskNodeStatus.FAILED:
                    failed_nodes.add(curr_node.node_id)
                    # Propagate failure: mark all downstream dependents as SKIPPED
                    downstream_ids = dag.get_downstream_nodes(curr_node.node_id)
                    for ds_id in downstream_ids:
                        ds_node = node_states[ds_id]
                        if ds_node.status == TaskNodeStatus.PENDING:
                            skipped_node = TaskNode(
                                node_id=ds_node.node_id,
                                agent_role=ds_node.agent_role,
                                description=ds_node.description,
                                dependencies=ds_node.dependencies,
                                parameters=ds_node.parameters,
                                status=TaskNodeStatus.SKIPPED,
                                error_message=f"Prerequisite node '{curr_node.node_id}' failed.",
                            )
                            node_states[ds_id] = skipped_node
                            skipped_nodes.add(ds_id)
                            trace.append(
                                AgentStep(
                                    step_index=step_counter,
                                    node_id=ds_id,
                                    agent_role=ds_node.agent_role,
                                    started_at_iso=datetime.now(timezone.utc).isoformat(),
                                    completed_at_iso=datetime.now(timezone.utc).isoformat(),
                                    duration_ms=0.0,
                                    status=TaskNodeStatus.SKIPPED,
                                    tokens_used=0,
                                    summary=(
                                        f"Skipped because prerequisite '{curr_node.node_id}' "
                                        f"failed."
                                    ),
                                )
                            )
                            step_counter += 1

                # If budget exhausted after this step, cancel remaining pending nodes
                if governor.is_exhausted():
                    rationale = governor.exhaustion_rationale() or "Budget limit reached."
                    cancel_msg = (
                        "Budget step limit reached."
                        if governor.steps_executed >= effective_budget.max_steps
                        else rationale
                    )
                    summary = (
                        "Aborted: hard step limit reached."
                        if governor.steps_executed >= effective_budget.max_steps
                        else f"Aborted: {rationale}"
                    )
                    step_counter = _cancel_remaining_pending_nodes(
                        node_states=node_states,
                        cancelled_nodes=cancelled_nodes,
                        trace=trace,
                        step_counter=step_counter,
                        error_message=cancel_msg,
                        summary=summary,
                    )
                    break

            if cancel_before_node is not None and cancel_before_node in node_states:
                if node_states[cancel_before_node].status == TaskNodeStatus.CANCELLED:
                    break

        t_end = time.perf_counter()
        total_dur_ms = round((t_end - t_start) * 1000.0, 2)

        # Determine overall status
        if failed_nodes:
            overall_status = TaskNodeStatus.FAILED
            node_errs = [
                f"{nid}: {node_states[nid].error_message}"
                for nid in sorted(failed_nodes)
                if node_states[nid].error_message
            ]
            err_details = f" ({'; '.join(node_errs)})" if node_errs else ""
            failure_rationale = (
                f"Execution failed on nodes: {sorted(failed_nodes)}{err_details}; "
                f"skipped dependent nodes: {sorted(skipped_nodes)}."
            )
        elif cancelled_nodes:
            overall_status = TaskNodeStatus.CANCELLED
            failure_rationale = f"Execution cancelled on nodes: {sorted(cancelled_nodes)}."
        else:
            overall_status = TaskNodeStatus.COMPLETED
            failure_rationale = None

        usage = ResourceUsage(
            total_steps=step_counter,
            total_duration_ms=total_dur_ms,
            total_tokens_used=total_tokens,
        )

        return OrchestrationResult(
            plan_id=dag.plan_id,
            goal_id=dag.goal_id,
            final_artifacts=artifacts,
            execution_trace=trace,
            resource_usage=usage,
            status=overall_status,
            failure_rationale=failure_rationale,
        )
