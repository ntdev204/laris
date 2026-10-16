"""Specialist agent contracts and base interfaces for Layer 8 Agent Orchestration.

Adheres to DOC-SPEC-MOD-001 (Boundary H), ADR-006, and Issue #66:
- Typed input/output contracts for specialist agents
  (SpecialistInputPayload, SpecialistOutputPayload)
- Bounded retries (0 <= max_retries <= 3) and execution timeout enforcement
- Abstract BaseSpecialistAgent contract and canonical specialist implementations
- Seamless integration with EvidenceCoordinate provenance tracking
"""

from __future__ import annotations

import math
import time
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional

from laris.core.errors import ModuleContractViolationError
from laris.core.schemas import EvidenceCoordinate
from laris.orchestration.schemas import AgentRole, TaskNodeStatus


class SpecialistInputPayload:
    """Typed input payload dispatched to a specialist agent."""

    def __init__(
        self,
        task_id: str,
        role: AgentRole,
        goal_statement: str,
        parameters: Optional[Dict[str, Any]] = None,
        upstream_artifacts: Optional[Dict[str, Any]] = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not task_id or not task_id.strip():
            raise ModuleContractViolationError("SpecialistInputPayload task_id must not be empty.")
        if not goal_statement or not goal_statement.strip():
            raise ModuleContractViolationError(
                "SpecialistInputPayload goal_statement must not be empty."
            )
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0.0:
            raise ModuleContractViolationError(
                "SpecialistInputPayload timeout_seconds must be a positive finite float."
            )

        self.task_id = task_id
        self.role = role
        self.goal_statement = goal_statement
        self.parameters = parameters or {}
        self.upstream_artifacts = upstream_artifacts or {}
        self.timeout_seconds = timeout_seconds


class SpecialistOutputPayload:
    """Typed output payload returned by a specialist agent."""

    def __init__(
        self,
        task_id: str,
        role: AgentRole,
        status: TaskNodeStatus,
        data: Optional[Dict[str, Any]] = None,
        evidence_citations: Optional[List[EvidenceCoordinate]] = None,
        tokens_used: int = 0,
        duration_ms: float = 0.0,
        error_message: Optional[str] = None,
        retry_count: int = 0,
    ) -> None:
        if not task_id or not task_id.strip():
            raise ModuleContractViolationError(
                "SpecialistOutputPayload task_id must not be empty."
            )
        if tokens_used < 0:
            raise ModuleContractViolationError(
                "SpecialistOutputPayload tokens_used must be non-negative."
            )
        if not math.isfinite(duration_ms) or duration_ms < 0.0:
            raise ModuleContractViolationError(
                "SpecialistOutputPayload duration_ms must be a non-negative finite float."
            )
        if retry_count < 0:
            raise ModuleContractViolationError(
                "SpecialistOutputPayload retry_count must be non-negative."
            )

        self.task_id = task_id
        self.role = role
        self.status = status
        self.data = data or {}
        self.evidence_citations = evidence_citations or []
        self.tokens_used = tokens_used
        self.duration_ms = duration_ms
        self.error_message = error_message
        self.retry_count = retry_count


class BaseSpecialistAgent(ABC):
    """Abstract base class defining interface contracts for Layer 8 specialist agents."""

    def __init__(
        self,
        role: AgentRole,
        max_retries: int = 2,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not (0 <= max_retries <= 3):
            raise ModuleContractViolationError(
                f"max_retries ({max_retries}) must be bounded within [0, 3]."
            )
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0.0:
            raise ModuleContractViolationError(
                "timeout_seconds must be a positive finite float."
            )

        self.role = role
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds

    @abstractmethod
    def execute(self, input_payload: SpecialistInputPayload) -> SpecialistOutputPayload:
        """Executes the specialized capability on the provided input payload."""
        raise NotImplementedError

    def execute_with_retry(
        self,
        input_payload: SpecialistInputPayload,
    ) -> SpecialistOutputPayload:
        """Executes agent task with bounded retry logic on failures."""
        if input_payload.role != self.role:
            raise ModuleContractViolationError(
                f"Payload role '{input_payload.role.value}' does not match specialist role "
                f"'{self.role.value}'."
            )

        attempts = 0
        last_output: Optional[SpecialistOutputPayload] = None

        while attempts <= self.max_retries:
            t0 = time.perf_counter()
            try:
                output = self.execute(input_payload)
            except Exception as exc:
                t1 = time.perf_counter()
                dur_ms = round((t1 - t0) * 1000.0, 2)
                output = SpecialistOutputPayload(
                    task_id=input_payload.task_id,
                    role=self.role,
                    status=TaskNodeStatus.FAILED,
                    error_message=f"Specialist execution exception: {exc}",
                    duration_ms=dur_ms,
                    retry_count=attempts,
                )

            last_output = output
            if output.status == TaskNodeStatus.COMPLETED:
                output.retry_count = attempts
                return output

            attempts += 1

        assert last_output is not None
        last_output.retry_count = self.max_retries
        return last_output


class GenericSpecialistAgent(BaseSpecialistAgent):
    """Standard configurable specialist agent executing user-supplied or synthetic logic."""

    def __init__(
        self,
        role: AgentRole,
        handler: Optional[
            Callable[[SpecialistInputPayload], SpecialistOutputPayload]
        ] = None,
        max_retries: int = 2,
        timeout_seconds: float = 30.0,
    ) -> None:
        super().__init__(role, max_retries=max_retries, timeout_seconds=timeout_seconds)
        self.handler = handler

    def execute(self, input_payload: SpecialistInputPayload) -> SpecialistOutputPayload:
        if self.handler is not None:
            return self.handler(input_payload)

        # Default synthetic success behavior
        return SpecialistOutputPayload(
            task_id=input_payload.task_id,
            role=self.role,
            status=TaskNodeStatus.COMPLETED,
            data={"result": f"Completed role {self.role.value}"},
            tokens_used=120,
            duration_ms=10.0,
        )
