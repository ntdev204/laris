"""Layer 9 Adaptive Model Execution & Resource Orchestrator.

Adheres to DOC-SPEC-MOD-001 (Boundary I), ADR-001, ADR-005, and Issue #68:
- Real-time hardware telemetry and sub-millisecond memory sampling
- Strict enforcement of the RTX 5070 Ti allocation safety threshold (<= 14.5 GB)
- Pre-flight headroom checks and dynamic activation memory scaling
- Safe fallback evaluations preventing Out-Of-Memory system crashes
"""

from laris.core.errors import HardwareBudgetExceededError
from laris.layers.layer9_adaptive_execution.headroom_governor import (
    HeadroomBudgetGovernor,
)
from laris.layers.layer9_adaptive_execution.schemas import (
    HardwareTarget,
    SpecialistExecutionRequest,
    SpecialistExecutionResult,
    TelemetrySnapshot,
    TelemetryStatus,
)
from laris.layers.layer9_adaptive_execution.telemetry import (
    HardwareTelemetryEngine,
    MockHardwareTelemetrySampler,
    PyTorchCudaSampler,
    TelemetrySampler,
)

__all__ = [
    "HardwareBudgetExceededError",
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
]
