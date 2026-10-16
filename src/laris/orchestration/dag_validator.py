"""DAG validator and cycle detection engine for Layer 8 Agent Orchestration.

Adheres to DOC-SPEC-MOD-001 (Boundary H), ADR-006, and Issue #65:
- Independent validation of task node dependency topologies
- Exhaustive cycle detection returning concrete cycle paths
- Missing dependency detection and referential integrity verification
- Resource budget verification enforcing hard recursion ceilings (N <= 10)
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set

from laris.core.errors import CycleDetectedError, ModuleContractViolationError
from laris.orchestration.schemas import BudgetLimits, PlanDAG, TaskNode


class DAGValidator:
    """Validates execution graphs, detect cycles, and enforces orchestration invariants."""

    def detect_cycles(self, nodes: Dict[str, TaskNode]) -> Optional[List[str]]:
        """Detects whether a set of TaskNodes contains a cycle, returning cycle path if found."""
        # Check direct self-loops first
        for node_id, node in nodes.items():
            if node_id in node.dependencies:
                return [node_id, node_id]

        # Use Depth-First Search with recursion stack tracking for cycle path extraction
        visited: Set[str] = set()
        rec_stack: List[str] = []
        rec_set: Set[str] = set()

        def dfs(curr: str) -> Optional[List[str]]:
            visited.add(curr)
            rec_stack.append(curr)
            rec_set.add(curr)

            node = nodes.get(curr)
            if node is not None:
                for dep in node.dependencies:
                    if dep not in nodes:
                        continue
                    if dep not in visited:
                        cycle = dfs(dep)
                        if cycle is not None:
                            return cycle
                    elif dep in rec_set:
                        # Cycle found: extract cycle path from rec_stack
                        idx = rec_stack.index(dep)
                        return rec_stack[idx:] + [dep]

            rec_stack.pop()
            rec_set.remove(curr)
            return None

        for nid in nodes:
            if nid not in visited:
                cycle_path = dfs(nid)
                if cycle_path is not None:
                    return cycle_path

        return None

    def find_missing_dependencies(self, nodes: Dict[str, TaskNode]) -> Dict[str, List[str]]:
        """Identifies any prerequisite nodes referenced in dependencies that are not in nodes."""
        missing: Dict[str, List[str]] = {}
        for node_id, node in nodes.items():
            unresolved = [dep for dep in node.dependencies if dep not in nodes]
            if unresolved:
                missing[node_id] = unresolved
        return missing

    def validate_budget_limits(self, budget: BudgetLimits) -> None:
        """Enforces that resource limits adhere strictly to Boundary H invariants."""
        if budget.max_steps > 10:
            raise ModuleContractViolationError(
                f"BudgetLimits max_steps ({budget.max_steps}) exceeds hard recursion ceiling of 10."
            )
        if budget.max_steps <= 0:
            raise ModuleContractViolationError(
                f"BudgetLimits max_steps ({budget.max_steps}) must be positive."
            )

    def validate_nodes(self, nodes: Dict[str, TaskNode]) -> None:
        """Validates node dictionary for emptiness, key consistency, missing deps, and cycles."""
        if not nodes:
            raise ModuleContractViolationError("TaskNode collection must not be empty.")

        for key, node in nodes.items():
            if key != node.node_id:
                raise ModuleContractViolationError(
                    f"Dictionary key '{key}' does not match TaskNode.node_id '{node.node_id}'."
                )

        missing = self.find_missing_dependencies(nodes)
        if missing:
            details = [f"Node '{nid}' references missing {deps}" for nid, deps in missing.items()]
            raise ModuleContractViolationError(
                f"Referential integrity failure: {'; '.join(details)}."
            )

        cycle = self.detect_cycles(nodes)
        if cycle:
            cycle_str = " -> ".join(cycle)
            raise CycleDetectedError(
                f"Execution graph contains a directed cycle: {cycle_str}."
            )

    def validate_dag(self, dag: PlanDAG) -> None:
        """Validates an existing PlanDAG instance."""
        self.validate_nodes(dag.nodes)
