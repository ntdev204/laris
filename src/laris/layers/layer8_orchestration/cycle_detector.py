"""Dynamic cycle detector preventing repeating agent sequences in Layer 8.

Adheres to DOC-SPEC-MOD-001 (Boundary H), DOC-SPEC-AGENT-001, ADR-006, and Issue #67:
- Detects duplicate agent tool/task dispatches with identical parameters
- Detects periodic repeating agent sequence cycles (e.g. A -> B -> A -> B)
- Halts execution immediately by raising CycleDetectedError
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from laris.core.errors import CycleDetectedError
from laris.layers.layer8_orchestration.schemas import AgentRole


class CycleDetector:
    """Detects cyclic loops and repeating agent invocation sequences."""

    def __init__(
        self,
        max_duplicate_calls: int = 2,
        min_cycle_length: int = 1,
        max_cycle_length: int = 5,
        default_repetition_threshold: int = 2,
    ) -> None:
        """Initializes CycleDetector with configurable repetition thresholds.

        Args:
            max_duplicate_calls: Max times an identical (role, args) pair may be dispatched.
            min_cycle_length: Minimum length of a repeating sequence pattern.
            max_cycle_length: Maximum length of a repeating sequence pattern.
            default_repetition_threshold: Repetition threshold for cycles of length >= 2.
        """
        self.max_duplicate_calls = max_duplicate_calls
        self.min_cycle_length = min_cycle_length
        self.max_cycle_length = max_cycle_length
        self.default_repetition_threshold = default_repetition_threshold
        self._history: List[Tuple[AgentRole, str, Optional[str], Optional[str]]] = []
        self._param_call_counts: Dict[Tuple[AgentRole, str], int] = {}
        self._desc_call_counts: Dict[Tuple[AgentRole, str, str], int] = {}

    def _canonicalize_parameters(self, parameters: Optional[Dict[str, Any]]) -> str:
        """Serializes parameter dictionary to deterministic canonical JSON string."""
        if not parameters:
            return "{}"
        try:
            return json.dumps(parameters, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError):
            return str(sorted(parameters.items()))

    def record_action(
        self,
        role: AgentRole,
        parameters: Optional[Dict[str, Any]] = None,
        task_id: Optional[str] = None,
        description: Optional[str] = None,
    ) -> None:
        """Records an agent action and checks for duplicate calls or periodic cycles.

        Args:
            role: The AgentRole dispatched.
            parameters: Dispatched arguments or parameters.
            task_id: Optional identifier of the task node.
            description: Optional task description.

        Raises:
            CycleDetectedError: If an identical call exceeds max_duplicate_calls
                or a periodic repeating agent sequence is detected.
        """
        canonical_params = self._canonicalize_parameters(parameters)

        # 1. Check duplicate calls with identical parameters if parameters provided
        if parameters:
            param_key = (role, canonical_params)
            param_count = self._param_call_counts.get(param_key, 0) + 1
            if param_count >= self.max_duplicate_calls:
                raise CycleDetectedError(
                    f"Cyclic execution detected: Agent '{role.value}' dispatched with identical "
                    f"arguments {param_count} times (max allowed: "
                    f"{self.max_duplicate_calls - 1})."
                )
            self._param_call_counts[param_key] = param_count

        # Check duplicate calls with identical description and parameters
        if description:
            desc_key = (role, description, canonical_params)
            desc_count = self._desc_call_counts.get(desc_key, 0) + 1
            if desc_count >= self.max_duplicate_calls:
                raise CycleDetectedError(
                    f"Cyclic execution detected: Task '{description}' for agent '{role.value}' "
                    f"dispatched {desc_count} times with identical configuration."
                )
            self._desc_call_counts[desc_key] = desc_count

        self._history.append((role, canonical_params, task_id, description))

        # 2. Check for repeating sequence cycles in agent roles
        self._detect_periodic_cycles()

    def _detect_periodic_cycles(self) -> None:
        """Scans the history tail for periodic repeating cycles of agent roles."""
        roles = [item[0] for item in self._history]
        total_len = len(roles)

        for cycle_len in range(self.min_cycle_length, self.max_cycle_length + 1):
            threshold = 3 if cycle_len == 1 else self.default_repetition_threshold
            required_len = cycle_len * threshold
            if total_len < required_len:
                continue

            tail = roles[-required_len:]
            pattern = tail[:cycle_len]
            is_repeating = True

            for rep_idx in range(1, threshold):
                segment = tail[rep_idx * cycle_len : (rep_idx + 1) * cycle_len]
                if segment != pattern:
                    is_repeating = False
                    break

            if is_repeating:
                pattern_str = " -> ".join([r.value for r in pattern])
                raise CycleDetectedError(
                    f"Repeating agent cycle detected: sequence [{pattern_str}] repeated "
                    f"{threshold} times in execution trace."
                )

    def get_history(self) -> List[Tuple[AgentRole, str, Optional[str], Optional[str]]]:
        """Returns the recorded action history tuples."""
        return list(self._history)

    def clear(self) -> None:
        """Resets the cycle detector state."""
        self._history.clear()
        self._param_call_counts.clear()
        self._desc_call_counts.clear()
