"""Conversation loop: multi-turn memory, streaming events, approvals, cycle detection, audit log."""

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional

from agent.provider import AssistantTurn, ChatProvider, Message, ProviderError
from agent.tools import ToolExecutionError, ToolRegistry, dumps

MAX_STEPS = 10  # hard recursion ceiling per user message (orchestration specification)
SYSTEM_PROMPT = (
    "You are LARIS, a local research assistant. Use the tools to read files, search the corpus "
    "and extract evidence. Cite the source of every statement, say when evidence is missing, "
    "and never claim more than the quoted passages support."
)

Approver = Callable[[str, Dict[str, Any]], bool]
Event = Dict[str, Any]


@dataclass
class AgentResult:
    session_id: str
    answer: str
    status: str  # completed | max_steps | cyclic | timeout | provider_error
    steps: List[Dict[str, Any]] = field(default_factory=list)
    log_path: Optional[str] = None


class AgentSession:
    """One conversation. `send()` streams events; `run()` is the blocking one-shot form."""

    def __init__(
        self,
        provider: ChatProvider,
        registry: ToolRegistry,
        approve: Optional[Approver] = None,
        log_dir: Optional[Path] = None,
        max_steps: int = MAX_STEPS,
        time_budget_s: float = 180.0,
        messages: Optional[List[Message]] = None,
        session_id: Optional[str] = None,
        system_prompt: str = SYSTEM_PROMPT,
    ) -> None:
        self.provider = provider
        self.registry = registry
        self.approve = approve
        self.log_dir = Path(log_dir) if log_dir else None
        self.max_steps = min(max_steps, MAX_STEPS)
        self.time_budget_s = time_budget_s
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self.messages: List[Message] = messages or [{"role": "system", "content": system_prompt}]

    # -- conversation ----------------------------------------------------------------------
    def send(self, user_text: str) -> Iterator[Event]:
        """Append a user message and stream events until the assistant gives a final answer.

        Events: text(delta), tool_call(name, arguments), tool_result(name, result),
        done(status, answer).
        """
        self.messages.append({"role": "user", "content": user_text})
        seen: set = set()
        started = time.monotonic()
        status, answer = "max_steps", ""
        for _ in range(self.max_steps):
            if time.monotonic() - started > self.time_budget_s:
                status = "timeout"
                break
            turn: Optional[AssistantTurn] = None
            try:
                for event in self.provider.stream(self.messages, self.registry.functions()):
                    if event["type"] == "turn":
                        turn = event["turn"]
                    else:
                        yield event
            except ProviderError as exc:
                status, answer = "provider_error", str(exc)
                break
            assert turn is not None
            if not turn.tool_calls:
                self.messages.append({"role": "assistant", "content": turn.content or ""})
                status, answer = "completed", turn.content or ""
                break
            self.messages.append(
                {
                    "role": "assistant",
                    "content": turn.content,
                    "tool_calls": [
                        {
                            "id": c.id,
                            "type": "function",
                            "function": {"name": c.name, "arguments": dumps(c.arguments)},
                        }
                        for c in turn.tool_calls
                    ],
                }
            )
            cyclic = False
            for call in turn.tool_calls:
                key = (call.name, json.dumps(call.arguments, sort_keys=True))
                yield {"type": "tool_call", "name": call.name, "arguments": call.arguments}
                if key in seen:  # an identical call twice in one task halts execution
                    cyclic = True
                    output: Any = ToolExecutionError(
                        "cyclic_call", f"repeated identical call to {call.name}"
                    ).to_dict()
                else:
                    seen.add(key)
                    output = self._execute(call.name, call.arguments)
                yield {"type": "tool_result", "name": call.name, "result": output}
                self.messages.append(
                    {"role": "tool", "tool_call_id": call.id, "content": dumps(output)}
                )
                if cyclic:
                    break
            if cyclic:
                status, answer = "cyclic", "Stopped: the same tool call was repeated."
                break
        if status == "max_steps":
            answer = "Stopped: step limit reached before a final answer."
        if status != "completed":
            self.messages.append({"role": "assistant", "content": answer})
        self._log()
        yield {"type": "done", "status": status, "answer": answer}

    def run(self, task: str) -> AgentResult:
        """Blocking one-shot form used by `laris agent run` and tests."""
        steps: List[Dict[str, Any]] = []
        status, answer = "max_steps", ""
        pending: Dict[str, Dict[str, Any]] = {}
        for event in self.send(task):
            if event["type"] == "tool_call":
                pending[event["name"]] = {"tool": event["name"], "arguments": event["arguments"]}
            elif event["type"] == "tool_result":
                step = pending.pop(event["name"], {"tool": event["name"], "arguments": {}})
                steps.append({**step, "result": event["result"]})
            elif event["type"] == "done":
                status, answer = event["status"], event["answer"]
        return AgentResult(self.session_id, answer, status, steps, self._log_path())

    # -- internals -------------------------------------------------------------------------
    def _execute(self, name: str, arguments: Dict[str, Any]) -> Any:
        spec = self.registry.tools.get(name)
        if spec and spec.writes and not (self.approve and self.approve(name, arguments)):
            return ToolExecutionError(
                "approval_denied", f"{name} needs approval and was not approved"
            ).to_dict()
        try:
            return self.registry.call(name, arguments)
        except ToolExecutionError as exc:
            return exc.to_dict()

    def _log_path(self) -> Optional[str]:
        if not self.log_dir:
            return None
        return str(self.log_dir / f"{self.session_id}.jsonl")

    def _log(self) -> None:
        path = self._log_path()
        if not path or not self.log_dir:
            return
        self.log_dir.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            for message in self.messages:
                handle.write(dumps(message) + "\n")
