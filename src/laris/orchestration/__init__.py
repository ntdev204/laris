"""Layer 8 Multi-Agent Orchestration & Teaming Engine.

Adheres to DOC-SPEC-MOD-001 (Boundary H), ADR-006, and Issue #65:
- Dynamic DAG planning and execution topology validation
- The ten canonical specialist agent roles
- Hard recursion ceilings (N <= 10) and resource budget governors
- Deterministic execution traces and cycle detection
"""

from laris.orchestration.budget_governor import BudgetGovernor
from laris.orchestration.cycle_detector import CycleDetector
from laris.orchestration.dag_validator import DAGValidator
from laris.orchestration.runtime import DAGScheduler, default_node_executor
from laris.orchestration.schemas import (
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
from laris.orchestration.specialists import (
    BaseSpecialistAgent,
    GenericSpecialistAgent,
    SpecialistInputPayload,
    SpecialistOutputPayload,
)
from laris.orchestration.verifier_gate import (
    VerificationResult,
    VerifierGate,
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
    "DAGScheduler",
    "default_node_executor",
    "SpecialistInputPayload",
    "SpecialistOutputPayload",
    "BaseSpecialistAgent",
    "GenericSpecialistAgent",
    "VerifierGate",
    "VerificationResult",
    "CycleDetector",
    "BudgetGovernor",
]
