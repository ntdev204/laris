"""Layer 8 Multi-Agent Orchestration & Teaming Engine.

Adheres to DOC-SPEC-MOD-001 (Boundary H), ADR-006, and Issue #65:
- Dynamic DAG planning and execution topology validation
- The ten canonical specialist agent roles
- Hard recursion ceilings (N <= 10) and resource budget governors
- Deterministic execution traces and cycle detection
"""

from laris.layers.layer8_orchestration.dag_validator import DAGValidator
from laris.layers.layer8_orchestration.schemas import (
    AgentRole,
    AgentStep,
    BudgetLimits,
    OrchestrationResult,
    PlanDAG,
    ResearchGoal,
    ResourceUsage,
    TaskNode,
    TaskNodeStatus,
)

__all__ = [
    "AgentRole",
    "TaskNodeStatus",
    "BudgetLimits",
    "ResearchGoal",
    "TaskNode",
    "AgentStep",
    "ResourceUsage",
    "OrchestrationResult",
    "PlanDAG",
    "DAGValidator",
]
