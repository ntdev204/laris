"""Layer 8 Multi-Agent Orchestration & Teaming Engine.

Adheres to DOC-SPEC-MOD-001 (Boundary H), ADR-006, and Issue #65:
- Dynamic DAG planning and execution topology validation
- The ten canonical specialist agent roles
- Hard recursion ceilings (N <= 10) and resource budget governors
- Deterministic execution traces and cycle detection
"""

from laris.layers.layer8_orchestration.budget_governor import BudgetGovernor
from laris.layers.layer8_orchestration.cycle_detector import CycleDetector
from laris.layers.layer8_orchestration.dag_validator import DAGValidator
from laris.layers.layer8_orchestration.runtime import DAGScheduler, default_node_executor
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
from laris.layers.layer8_orchestration.specialists import (
    BaseSpecialistAgent,
    GenericSpecialistAgent,
    SpecialistInputPayload,
    SpecialistOutputPayload,
)
from laris.layers.layer8_orchestration.verifier_gate import (
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
