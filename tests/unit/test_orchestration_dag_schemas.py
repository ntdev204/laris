"""Unit and contract tests for Layer 8 Agent Orchestration DAG schemas and validator.

Adheres to DOC-SPEC-MOD-001 (Boundary H), ADR-006, and Issue #65:
- Verifies all 10 canonical specialist agent roles from ADR-006
- Tests budget limits and hard recursion ceilings (N <= 10)
- Tests ResearchGoal, TaskNode, PlanDAG, and execution trace contracts
- Tests cycle detection, missing dependencies, and topological ordering
"""

from __future__ import annotations

import pytest

from laris.core.errors import CycleDetectedError, ModuleContractViolationError
from laris.layers.layer8_orchestration import (
    AgentRole,
    AgentStep,
    BudgetLimits,
    DAGValidator,
    OrchestrationResult,
    PlanDAG,
    ResearchGoal,
    ResourceUsage,
    TaskNode,
    TaskNodeStatus,
)


def test_agent_roles_enumeration() -> None:
    """Verifies all ten canonical specialist agent roles defined in ADR-006."""
    expected_roles = {
        "SUPERVISOR",
        "QUERY_PLANNER",
        "LANGUAGE_ANALYSIS",
        "DOCUMENT_ANALYSIS",
        "EVIDENCE_RETRIEVAL",
        "SCIENTIFIC_CLAIM",
        "CROSS_PAPER_SYNTHESIS",
        "GAP_DISCOVERY",
        "CRITICAL_REVIEWER",
        "REPORT_COMPOSER",
    }
    actual_roles = {role.value for role in AgentRole}
    assert actual_roles == expected_roles
    assert len(AgentRole) == 10


def test_budget_limits_contracts() -> None:
    """Tests BudgetLimits constraints and hard recursion ceiling enforcement."""
    # Valid defaults
    default_budget = BudgetLimits()
    assert default_budget.max_steps == 10
    assert default_budget.max_tokens == 100_000
    assert default_budget.timeout_seconds == 300.0

    # Custom valid limits
    custom_budget = BudgetLimits(max_steps=5, max_tokens=50_000, timeout_seconds=120.0)
    assert custom_budget.max_steps == 5

    # Violate hard recursion ceiling (N <= 10)
    with pytest.raises(ModuleContractViolationError, match="hard recursion ceiling of 10"):
        BudgetLimits(max_steps=11)

    # Violate positive step limit
    with pytest.raises(ModuleContractViolationError, match="strictly positive"):
        BudgetLimits(max_steps=0)

    # Violate positive token limit
    with pytest.raises(ModuleContractViolationError, match="max_tokens must be strictly positive"):
        BudgetLimits(max_tokens=0)

    # Violate positive timeout
    with pytest.raises(ModuleContractViolationError, match="positive finite float"):
        BudgetLimits(timeout_seconds=-10.0)

    with pytest.raises(ModuleContractViolationError, match="positive finite float"):
        BudgetLimits(timeout_seconds=float("nan"))


def test_research_goal_contracts() -> None:
    """Tests ResearchGoal initialization and validation rules."""
    budget = BudgetLimits(max_steps=8)
    goal = ResearchGoal(
        goal_id="goal-001",
        goal_statement="Synthesize findings on room-temperature superconductivity.",
        resource_budget=budget,
    )
    assert goal.goal_id == "goal-001"
    assert goal.resource_budget.max_steps == 8

    # Empty goal_id
    with pytest.raises(ModuleContractViolationError, match="goal_id must not be empty"):
        ResearchGoal(goal_id="  ", goal_statement="Statement")

    # Empty goal_statement
    with pytest.raises(ModuleContractViolationError, match="goal_statement must not be empty"):
        ResearchGoal(goal_id="goal-001", goal_statement="")


def test_task_node_contracts() -> None:
    """Tests TaskNode schema contracts and self-dependency rejection."""
    node = TaskNode(
        node_id="node-retrieve",
        agent_role=AgentRole.EVIDENCE_RETRIEVAL,
        description="Retrieve evidence coordinates for target query.",
        dependencies=["node-plan"],
        parameters={"query": "superconductivity"},
    )
    assert node.node_id == "node-retrieve"
    assert node.agent_role == AgentRole.EVIDENCE_RETRIEVAL
    assert node.status == TaskNodeStatus.PENDING

    # Empty node_id
    with pytest.raises(ModuleContractViolationError, match="node_id must not be empty"):
        TaskNode(
            node_id="",
            agent_role=AgentRole.QUERY_PLANNER,
            description="Valid description",
        )

    # Empty description
    with pytest.raises(ModuleContractViolationError, match="description must not be empty"):
        TaskNode(
            node_id="valid-id",
            agent_role=AgentRole.QUERY_PLANNER,
            description="   ",
        )

    # Self-dependency
    with pytest.raises(CycleDetectedError, match="cannot specify a self-dependency"):
        TaskNode(
            node_id="node-loop",
            agent_role=AgentRole.SUPERVISOR,
            description="Self loop node",
            dependencies=["node-loop"],
        )


def test_plan_dag_linear_execution() -> None:
    """Verifies PlanDAG validation, topological sorting, and readiness on a linear pipeline."""
    node1 = TaskNode("n1", AgentRole.QUERY_PLANNER, "Plan research")
    node2 = TaskNode("n2", AgentRole.EVIDENCE_RETRIEVAL, "Retrieve papers", dependencies=["n1"])
    node3 = TaskNode("n3", AgentRole.SCIENTIFIC_CLAIM, "Extract claims", dependencies=["n2"])

    nodes = {"n1": node1, "n2": node2, "n3": node3}
    dag = PlanDAG(plan_id="plan-linear", goal_id="goal-01", nodes=nodes)

    order = dag.topological_sort()
    assert order == ["n1", "n2", "n3"]

    # Initial ready nodes
    ready0 = dag.get_ready_nodes(completed_node_ids=set())
    assert [n.node_id for n in ready0] == ["n1"]

    # After n1 completed
    ready1 = dag.get_ready_nodes(completed_node_ids={"n1"})
    assert [n.node_id for n in ready1] == ["n2"]

    # Downstream / Upstream traversal
    assert dag.get_downstream_nodes("n1") == ["n2", "n3"]
    assert dag.get_downstream_nodes("n2") == ["n3"]
    assert dag.get_downstream_nodes("n3") == []

    assert dag.get_upstream_nodes("n3") == ["n1", "n2"]
    assert dag.get_upstream_nodes("n2") == ["n1"]
    assert dag.get_upstream_nodes("n1") == []


def test_plan_dag_diamond_topology() -> None:
    """Verifies PlanDAG handling of diamond/fork-join dependency structures."""
    # Fork: n1 -> n2, n1 -> n3; Join: n2 -> n4, n3 -> n4
    n1 = TaskNode("n1", AgentRole.QUERY_PLANNER, "Plan")
    n2 = TaskNode("n2", AgentRole.LANGUAGE_ANALYSIS, "Lang", dependencies=["n1"])
    n3 = TaskNode("n3", AgentRole.DOCUMENT_ANALYSIS, "Doc", dependencies=["n1"])
    n4 = TaskNode("n4", AgentRole.CROSS_PAPER_SYNTHESIS, "Synthesize", dependencies=["n2", "n3"])
    diamond_nodes = {"n1": n1, "n2": n2, "n3": n3, "n4": n4}
    dag = PlanDAG(plan_id="plan-diamond", goal_id="goal-01", nodes=diamond_nodes)
    order = dag.topological_sort()

    assert order[0] == "n1"
    assert set(order[1:3]) == {"n2", "n3"}
    assert order[3] == "n4"

    # When n1 is done, both n2 and n3 are ready
    ready = dag.get_ready_nodes(completed_node_ids={"n1"})
    assert {n.node_id for n in ready} == {"n2", "n3"}

    # n4 is ready only when both n2 and n3 are completed
    assert dag.get_ready_nodes(completed_node_ids={"n1", "n2"}) == [n3]
    assert {n.node_id for n in dag.get_ready_nodes(completed_node_ids={"n1", "n2", "n3"})} == {"n4"}


def test_plan_dag_validation_failures() -> None:
    """Tests PlanDAG rejection of empty, mismatched, or malformed node collections."""
    # Empty nodes
    with pytest.raises(ModuleContractViolationError, match="at least one TaskNode"):
        PlanDAG(plan_id="p1", goal_id="g1", nodes={})

    # Empty plan_id
    n1 = TaskNode("n1", AgentRole.SUPERVISOR, "Task")
    with pytest.raises(ModuleContractViolationError, match="plan_id must not be empty"):
        PlanDAG(plan_id="", goal_id="g1", nodes={"n1": n1})

    # Empty goal_id
    with pytest.raises(ModuleContractViolationError, match="goal_id must not be empty"):
        PlanDAG(plan_id="p1", goal_id="  ", nodes={"n1": n1})

    # Dictionary key mismatch
    with pytest.raises(ModuleContractViolationError, match="does not match TaskNode.node_id"):
        PlanDAG(plan_id="p1", goal_id="g1", nodes={"mismatched_key": n1})

    # Unknown dependency
    n_orphan = TaskNode("n_orphan", AgentRole.SUPERVISOR, "Task", dependencies=["missing_node"])
    with pytest.raises(ModuleContractViolationError, match="unknown dependency 'missing_node'"):
        PlanDAG(plan_id="p1", goal_id="g1", nodes={"n_orphan": n_orphan})

    # Unknown node for downstream/upstream query
    valid_dag = PlanDAG(plan_id="p1", goal_id="g1", nodes={"n1": n1})
    with pytest.raises(ModuleContractViolationError, match="Unknown node_id"):
        valid_dag.get_downstream_nodes("non_existent")

    with pytest.raises(ModuleContractViolationError, match="Unknown node_id"):
        valid_dag.get_upstream_nodes("non_existent")


def test_plan_dag_cycle_rejection() -> None:
    """Tests detection and rejection of cyclic dependencies in PlanDAG."""
    # 2-node cycle: A -> B -> A
    # To create nodes with mutual dependencies without TaskNode post_init self-dependency violation:
    na = TaskNode("na", AgentRole.SUPERVISOR, "A", dependencies=["nb"])
    nb = TaskNode("nb", AgentRole.QUERY_PLANNER, "B", dependencies=["na"])

    with pytest.raises(CycleDetectedError, match="contains a directed cycle"):
        PlanDAG(plan_id="plan-cycle-2", goal_id="g1", nodes={"na": na, "nb": nb})

    # 3-node cycle: X -> Y -> Z -> X
    nx = TaskNode("nx", AgentRole.SUPERVISOR, "X", dependencies=["nz"])
    ny = TaskNode("ny", AgentRole.QUERY_PLANNER, "Y", dependencies=["nx"])
    nz = TaskNode("nz", AgentRole.EVIDENCE_RETRIEVAL, "Z", dependencies=["ny"])

    with pytest.raises(CycleDetectedError, match="contains a directed cycle"):
        PlanDAG(plan_id="plan-cycle-3", goal_id="g1", nodes={"nx": nx, "ny": ny, "nz": nz})


def test_dag_validator_engine() -> None:
    """Verifies DAGValidator utility methods for cycle and dependency checking."""
    validator = DAGValidator()

    # Valid DAG
    n1 = TaskNode("n1", AgentRole.QUERY_PLANNER, "Plan")
    n2 = TaskNode("n2", AgentRole.EVIDENCE_RETRIEVAL, "Retrieve", dependencies=["n1"])
    nodes_valid = {"n1": n1, "n2": n2}

    assert validator.detect_cycles(nodes_valid) is None
    assert validator.find_missing_dependencies(nodes_valid) == {}
    validator.validate_nodes(nodes_valid)

    # Missing dependency
    n_broken = TaskNode("n3", AgentRole.SCIENTIFIC_CLAIM, "Claim", dependencies=["missing_id"])
    nodes_missing = {"n3": n_broken}
    assert validator.detect_cycles(nodes_missing) is None
    assert validator.find_missing_dependencies(nodes_missing) == {"n3": ["missing_id"]}
    with pytest.raises(ModuleContractViolationError, match="Referential integrity failure"):
        validator.validate_nodes(nodes_missing)

    # Empty node collection
    with pytest.raises(ModuleContractViolationError, match="must not be empty"):
        validator.validate_nodes({})

    # Key mismatch
    with pytest.raises(ModuleContractViolationError, match="does not match TaskNode.node_id"):
        validator.validate_nodes({"wrong_key": n1})

    # Cyclic nodes
    na = TaskNode("na", AgentRole.SUPERVISOR, "A", dependencies=["nb"])
    nb = TaskNode("nb", AgentRole.QUERY_PLANNER, "B", dependencies=["na"])
    cycle_path = validator.detect_cycles({"na": na, "nb": nb})
    assert cycle_path is not None
    assert len(cycle_path) >= 2
    assert cycle_path[0] == cycle_path[-1]

    with pytest.raises(CycleDetectedError, match="contains a directed cycle"):
        validator.validate_nodes({"na": na, "nb": nb})

    # Direct self-loop in nodes (simulated bypass or dictionary lookup)
    # Using object.__new__ to test validator's direct check
    n_self = object.__new__(TaskNode)
    object.__setattr__(n_self, "node_id", "self_node")
    object.__setattr__(n_self, "agent_role", AgentRole.SUPERVISOR)
    object.__setattr__(n_self, "description", "Self")
    object.__setattr__(n_self, "dependencies", ["self_node"])
    object.__setattr__(n_self, "parameters", {})
    object.__setattr__(n_self, "status", TaskNodeStatus.PENDING)
    object.__setattr__(n_self, "output_artifact", None)
    object.__setattr__(n_self, "error_message", None)

    cycle_self = validator.detect_cycles({"self_node": n_self})
    assert cycle_self == ["self_node", "self_node"]

    # Budget limits validation
    validator.validate_budget_limits(BudgetLimits(max_steps=5))
    # Simulated invalid budget via object.__new__
    b_bad = object.__new__(BudgetLimits)
    object.__setattr__(b_bad, "max_steps", 15)
    object.__setattr__(b_bad, "max_tokens", 1000)
    object.__setattr__(b_bad, "timeout_seconds", 100.0)
    with pytest.raises(ModuleContractViolationError, match="exceeds hard recursion ceiling"):
        validator.validate_budget_limits(b_bad)

    object.__setattr__(b_bad, "max_steps", 0)
    with pytest.raises(ModuleContractViolationError, match="must be positive"):
        validator.validate_budget_limits(b_bad)

    # Validate PlanDAG instance
    dag_valid = PlanDAG("p1", "g1", nodes_valid)
    validator.validate_dag(dag_valid)


def test_agent_step_and_orchestration_result_contracts() -> None:
    """Verifies schema contracts for execution traces and final orchestration results."""
    step = AgentStep(
        step_index=0,
        node_id="n1",
        agent_role=AgentRole.QUERY_PLANNER,
        started_at_iso="2026-10-16T05:00:00Z",
        completed_at_iso="2026-10-16T05:00:01Z",
        duration_ms=1050.5,
        status=TaskNodeStatus.COMPLETED,
        tokens_used=1200,
        summary="Query planned into 4 task nodes.",
    )
    assert step.step_index == 0
    assert step.duration_ms == 1050.5

    # AgentStep validations
    with pytest.raises(ModuleContractViolationError, match="step_index must be non-negative"):
        AgentStep(-1, "n1", AgentRole.SUPERVISOR, "2026", "2026", 100.0, TaskNodeStatus.COMPLETED)

    with pytest.raises(ModuleContractViolationError, match="node_id must not be empty"):
        AgentStep(0, "  ", AgentRole.SUPERVISOR, "2026", "2026", 100.0, TaskNodeStatus.COMPLETED)

    with pytest.raises(ModuleContractViolationError, match="duration_ms must be a non-negative"):
        AgentStep(0, "n1", AgentRole.SUPERVISOR, "2026", "2026", -5.0, TaskNodeStatus.COMPLETED)

    with pytest.raises(ModuleContractViolationError, match="duration_ms must be a non-negative"):
        AgentStep(
            0, "n1", AgentRole.SUPERVISOR, "2026", "2026", float("nan"), TaskNodeStatus.COMPLETED
        )

    with pytest.raises(ModuleContractViolationError, match="tokens_used must be non-negative"):
        AgentStep(
            0,
            "n1",
            AgentRole.SUPERVISOR,
            "2026",
            "2026",
            100.0,
            TaskNodeStatus.COMPLETED,
            tokens_used=-1,
        )

    # ResourceUsage
    usage = ResourceUsage(
        total_steps=3,
        total_duration_ms=2500.0,
        total_tokens_used=4500,
        peak_vram_mb=4096.0,
    )
    assert usage.total_steps == 3
    assert usage.peak_vram_mb == 4096.0

    with pytest.raises(ModuleContractViolationError, match="total_steps must be non-negative"):
        ResourceUsage(-1, 100.0, 100)

    with pytest.raises(
        ModuleContractViolationError, match="total_duration_ms must be a non-negative"
    ):
        ResourceUsage(1, -10.0, 100)

    with pytest.raises(
        ModuleContractViolationError, match="total_tokens_used must be non-negative"
    ):
        ResourceUsage(1, 10.0, -100)

    with pytest.raises(ModuleContractViolationError, match="peak_vram_mb must be a non-negative"):
        ResourceUsage(1, 10.0, 100, peak_vram_mb=-50.0)

    # OrchestrationResult
    result = OrchestrationResult(
        plan_id="p1",
        goal_id="g1",
        final_artifacts={"report": "Comprehensive synthesis"},
        execution_trace=[step],
        resource_usage=usage,
        status=TaskNodeStatus.COMPLETED,
    )
    assert result.status == TaskNodeStatus.COMPLETED
    assert len(result.execution_trace) == 1

    with pytest.raises(ModuleContractViolationError, match="plan_id must not be empty"):
        OrchestrationResult("", "g1", {}, [step], usage, TaskNodeStatus.COMPLETED)

    with pytest.raises(ModuleContractViolationError, match="goal_id must not be empty"):
        OrchestrationResult("p1", "", {}, [step], usage, TaskNodeStatus.COMPLETED)
