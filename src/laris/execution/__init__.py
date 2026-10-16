"""Layer 9 Adaptive Model Execution & Resource Orchestrator.

Adheres to DOC-SPEC-MOD-001 (Boundary I), ADR-001, ADR-005, and Issue #68:
- Real-time hardware telemetry and sub-millisecond memory sampling
- Strict enforcement of the RTX 5070 Ti allocation safety threshold (<= 14.5 GB)
- Pre-flight headroom checks and dynamic activation memory scaling
- Safe fallback evaluations preventing Out-Of-Memory system crashes
"""

from laris.core.errors import (
    HardwareBudgetExceededError,
    TaskRoutingError,
    WeightStagingError,
)
from laris.execution.headroom_governor import (
    HeadroomBudgetGovernor,
)
from laris.execution.schemas import (
    HardwareTarget,
    SpecialistExecutionRequest,
    SpecialistExecutionResult,
    TelemetrySnapshot,
    TelemetryStatus,
)
from laris.execution.task_router import (
    ExecutionTier,
    HardwareBenchmarkReport,
    HardwareStressProtocol,
    RoutingDecision,
    RoutingPolicy,
    TaskDomain,
    TaskRouter,
    TaskRoutingRequest,
)
from laris.execution.telemetry import (
    HardwareTelemetryEngine,
    MockHardwareTelemetrySampler,
    PyTorchCudaSampler,
    TelemetrySampler,
)
from laris.execution.weight_staging import (
    MockSpecialistWeightLoader,
    SpecialistLRUCache,
    SpecialistWeightDescriptor,
    SpecialistWeightLoader,
    StagingState,
    StorageTier,
    WeightTransferMetrics,
)

__all__ = [
    "HardwareBudgetExceededError",
    "TaskRoutingError",
    "WeightStagingError",
    "HardwareTarget",
    "TelemetryStatus",
    "TelemetrySnapshot",
    "SpecialistExecutionRequest",
    "SpecialistExecutionResult",
    "TelemetrySampler",
    "MockHardwareTelemetrySampler",
    "PyTorchCudaSampler",
    "HardwareTelemetryEngine",
    "HeadroomBudgetGovernor",
    "StorageTier",
    "StagingState",
    "SpecialistWeightDescriptor",
    "WeightTransferMetrics",
    "SpecialistWeightLoader",
    "MockSpecialistWeightLoader",
    "SpecialistLRUCache",
    "ExecutionTier",
    "TaskDomain",
    "RoutingPolicy",
    "TaskRoutingRequest",
    "RoutingDecision",
    "TaskRouter",
    "HardwareBenchmarkReport",
    "HardwareStressProtocol",
]

