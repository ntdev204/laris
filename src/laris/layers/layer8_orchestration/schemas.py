"""Schemas and data models for Layer 8 Agent Orchestration.

Adheres to DOC-SPEC-MOD-001 (Boundary H), ADR-006, and Issue #65:
- Research goal definitions and resource budget limits enforcing recursion ceiling (N <= 10)
- Task node schemas and ten canonical specialist agent roles
- Directed Acyclic Graph (PlanDAG) contract with dependency and acyclicity validation
- Deterministic execution trace contracts (AgentStep, ResourceUsage, OrchestrationResult)
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from laris.core.errors import CycleDetectedError, ModuleContractViolationError


class AgentRole(str, Enum):
    """The ten canonical specialist agent roles defined in ADR-006 and Boundary H."""

    SUPERVISOR = "SUPERVISOR"
    QUERY_PLANNER = "QUERY_PLANNER"
    LANGUAGE_ANALYSIS = "LANGUAGE_ANALYSIS"
    DOCUMENT_ANALYSIS = "DOCUMENT_ANALYSIS"
    EVIDENCE_RETRIEVAL = "EVIDENCE_RETRIEVAL"
    SCIENTIFIC_CLAIM = "SCIENTIFIC_CLAIM"
    CROSS_PAPER_SYNTHESIS = "CROSS_PAPER_SYNTHESIS"
    GAP_DISCOVERY = "GAP_DISCOVERY"
    CRITICAL_REVIEWER = "CRITICAL_REVIEWER"
    REPORT_COMPOSER = "REPORT_COMPOSER"


class TaskNodeStatus(str, Enum):
    """Lifecycle status of an individual task node in an execution DAG."""

    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    SKIPPED = "SKIPPED"


@dataclass(frozen=True)
class BudgetLimits:
    """Resource bounds and execution limits for research goal orchestration."""

    max_steps: int = 10
    max_tokens: int = 100_000
    timeout_seconds: float = 300.0

    def __post_init__(self) -> None:
        if self.max_steps <= 0:
            raise ModuleContractViolationError("BudgetLimits max_steps must be strictly positive.")
        if self.max_steps > 10:
            raise ModuleContractViolationError(
                "BudgetLimits max_steps must not exceed hard recursion ceiling of 10."
            )
        if self.max_tokens <= 0:
            raise ModuleContractViolationError(
                "BudgetLimits max_tokens must be strictly positive."
            )
        if math.isnan(self.timeout_seconds) or self.timeout_seconds <= 0.0:
            raise ModuleContractViolationError(
                "BudgetLimits timeout_seconds must be a positive finite float."
            )


@dataclass(frozen=True)
class ResearchGoal:
    """High-level research objective statement and associated resource budget."""

    goal_id: str
    goal_statement: str
    resource_budget: BudgetLimits = field(default_factory=BudgetLimits)

    def __post_init__(self) -> None:
        if not self.goal_id or not self.goal_id.strip():
            raise ModuleContractViolationError("ResearchGoal goal_id must not be empty.")
        if not self.goal_statement or not self.goal_statement.strip():
            raise ModuleContractViolationError("ResearchGoal goal_statement must not be empty.")


@dataclass(frozen=True)
class TaskNode:
    """Individual unit of work in a research plan DAG dispatched to a specialist agent."""

    node_id: str
    agent_role: AgentRole
    description: str
    dependencies: List[str] = field(default_factory=list)
    parameters: Dict[str, Any] = field(default_factory=dict)
    status: TaskNodeStatus = TaskNodeStatus.PENDING
    output_artifact: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.node_id or not self.node_id.strip():
            raise ModuleContractViolationError("TaskNode node_id must not be empty.")
        if not self.description or not self.description.strip():
            raise ModuleContractViolationError("TaskNode description must not be empty.")
        if self.node_id in self.dependencies:
            raise CycleDetectedError(
                f"TaskNode '{self.node_id}' cannot specify a self-dependency."
            )


@dataclass(frozen=True)
class AgentStep:
    """Deterministic record of a single specialist agent execution step in a trace."""

    step_index: int
    node_id: str
    agent_role: AgentRole
    started_at_iso: str
    completed_at_iso: str
    duration_ms: float
    status: TaskNodeStatus
    tokens_used: int = 0
    summary: str = ""

    def __post_init__(self) -> None:
        if self.step_index < 0:
            raise ModuleContractViolationError("AgentStep step_index must be non-negative.")
        if not self.node_id or not self.node_id.strip():
            raise ModuleContractViolationError("AgentStep node_id must not be empty.")
        if math.isnan(self.duration_ms) or self.duration_ms < 0.0:
            raise ModuleContractViolationError(
                "AgentStep duration_ms must be a non-negative finite float."
            )
        if self.tokens_used < 0:
            raise ModuleContractViolationError("AgentStep tokens_used must be non-negative.")


@dataclass(frozen=True)
class ResourceUsage:
    """Aggregated resource telemetry consumed across an orchestration run."""

    total_steps: int
    total_duration_ms: float
    total_tokens_used: int
    peak_vram_mb: Optional[float] = None

    def __post_init__(self) -> None:
        if self.total_steps < 0:
            raise ModuleContractViolationError("ResourceUsage total_steps must be non-negative.")
        if math.isnan(self.total_duration_ms) or self.total_duration_ms < 0.0:
            raise ModuleContractViolationError(
                "ResourceUsage total_duration_ms must be a non-negative finite float."
            )
        if self.total_tokens_used < 0:
            raise ModuleContractViolationError(
                "ResourceUsage total_tokens_used must be non-negative."
            )
        if self.peak_vram_mb is not None:
            if math.isnan(self.peak_vram_mb) or self.peak_vram_mb < 0.0:
                raise ModuleContractViolationError(
                    "ResourceUsage peak_vram_mb must be a non-negative finite float."
                )


@dataclass(frozen=True)
class OrchestrationResult:
    """Final validated result artifact and execution trace of research orchestration."""

    plan_id: str
    goal_id: str
    final_artifacts: Dict[str, Any]
    execution_trace: List[AgentStep]
    resource_usage: ResourceUsage
    status: TaskNodeStatus
    failure_rationale: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.plan_id or not self.plan_id.strip():
            raise ModuleContractViolationError("OrchestrationResult plan_id must not be empty.")
        if not self.goal_id or not self.goal_id.strip():
            raise ModuleContractViolationError("OrchestrationResult goal_id must not be empty.")


@dataclass(frozen=True)
class PlanDAG:
    """Directed Acyclic Graph defining task node dependencies for a research goal."""

    plan_id: str
    goal_id: str
    nodes: Dict[str, TaskNode]

    def __post_init__(self) -> None:
        if not self.plan_id or not self.plan_id.strip():
            raise ModuleContractViolationError("PlanDAG plan_id must not be empty.")
        if not self.goal_id or not self.goal_id.strip():
            raise ModuleContractViolationError("PlanDAG goal_id must not be empty.")
        if not self.nodes:
            raise ModuleContractViolationError("PlanDAG nodes must contain at least one TaskNode.")

        # Validate that all node keys match their internal node_id
        for key, node in self.nodes.items():
            if key != node.node_id:
                raise ModuleContractViolationError(
                    f"PlanDAG dictionary key '{key}' does not match TaskNode.node_id "
                    f"'{node.node_id}'."
                )

        # Validate referential integrity of dependencies
        for node in self.nodes.values():
            for dep_id in node.dependencies:
                if dep_id not in self.nodes:
                    raise ModuleContractViolationError(
                        f"TaskNode '{node.node_id}' specifies unknown dependency '{dep_id}'."
                    )

        # Validate acyclicity using Kahn's algorithm
        in_degree: Dict[str, int] = {node_id: 0 for node_id in self.nodes}
        for node in self.nodes.values():
            for dep_id in node.dependencies:
                # dep_id is prerequisite for node.node_id
                pass
            in_degree[node.node_id] = len(node.dependencies)

        queue: deque[str] = deque([nid for nid, deg in in_degree.items() if deg == 0])
        visited_count = 0

        # Adjacency map: prerequisite -> downstream dependents
        downstream: Dict[str, List[str]] = {nid: [] for nid in self.nodes}
        for node in self.nodes.values():
            for dep_id in node.dependencies:
                downstream[dep_id].append(node.node_id)

        while queue:
            curr = queue.popleft()
            visited_count += 1
            for nxt in downstream[curr]:
                in_degree[nxt] -= 1
                if in_degree[nxt] == 0:
                    queue.append(nxt)

        if visited_count < len(self.nodes):
            cyclic_nodes = [nid for nid, deg in in_degree.items() if deg > 0]
            raise CycleDetectedError(
                f"PlanDAG '{self.plan_id}' contains a directed cycle involving nodes: "
                f"{cyclic_nodes}."
            )

    def topological_sort(self) -> List[str]:
        """Returns node IDs in topologically sorted execution order."""
        in_degree: Dict[str, int] = {
            node.node_id: len(node.dependencies) for node in self.nodes.values()
        }
        queue: deque[str] = deque([nid for nid, deg in in_degree.items() if deg == 0])
        order: List[str] = []

        downstream: Dict[str, List[str]] = {nid: [] for nid in self.nodes}
        for node in self.nodes.values():
            for dep_id in node.dependencies:
                downstream[dep_id].append(node.node_id)

        while queue:
            curr = queue.popleft()
            order.append(curr)
            for nxt in downstream[curr]:
                in_degree[nxt] -= 1
                if in_degree[nxt] == 0:
                    queue.append(nxt)

        return order

    def get_ready_nodes(self, completed_node_ids: Set[str]) -> List[TaskNode]:
        """Returns pending nodes whose prerequisites are all completed."""
        ready: List[TaskNode] = []
        for node in self.nodes.values():
            if node.status in (TaskNodeStatus.PENDING, TaskNodeStatus.READY):
                if node.node_id not in completed_node_ids:
                    if all(dep in completed_node_ids for dep in node.dependencies):
                        ready.append(node)
        return ready

    def get_downstream_nodes(self, node_id: str) -> List[str]:
        """Returns all transitively downstream dependent node IDs for a given node."""
        if node_id not in self.nodes:
            raise ModuleContractViolationError(
                f"Unknown node_id '{node_id}' in get_downstream_nodes."
            )
        downstream_map: Dict[str, List[str]] = {nid: [] for nid in self.nodes}
        for node in self.nodes.values():
            for dep_id in node.dependencies:
                downstream_map[dep_id].append(node.node_id)

        visited: Set[str] = set()
        queue: deque[str] = deque([node_id])
        while queue:
            curr = queue.popleft()
            for nxt in downstream_map[curr]:
                if nxt not in visited:
                    visited.add(nxt)
                    queue.append(nxt)
        return sorted(visited)

    def get_upstream_nodes(self, node_id: str) -> List[str]:
        """Returns all transitively upstream prerequisite node IDs for a given node."""
        if node_id not in self.nodes:
            raise ModuleContractViolationError(
                f"Unknown node_id '{node_id}' in get_upstream_nodes."
            )
        visited: Set[str] = set()
        queue: deque[str] = deque(self.nodes[node_id].dependencies)
        while queue:
            curr = queue.popleft()
            if curr not in visited:
                visited.add(curr)
                queue.extend(self.nodes[curr].dependencies)
        return sorted(visited)
