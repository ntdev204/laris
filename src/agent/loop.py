"""The agent loop, driven entirely by the harness (configuration, guards, policies, audit).

One user message runs a bounded loop:

    BEGIN -> [COMPACT -> MODEL -> (TOOLS -> GUARD)* ] -> VERIFY -> DONE

- BEGIN composes the system prompt from the versioned modules and instruction files and primes the
  leak guard with it.
- COMPACT shrinks the context before every model call when it nears the limit (autocompact).
- MODEL streams text through the stream guard; a leak or secret never reaches the client.
- TOOLS apply the approval policy, the per-step call cap and repeat detection, then the guard marks
  untrusted data and redacts secrets and internal paths.
- VERIFY checks that grounded answers cite their sources and may ask the model to rewrite once.
Limits (steps, time, calls) come from `agent.*` configuration; the step ceiling is capped at 10.
"""

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from agent.context import CompactionResult, ContextManager, TokenEstimator
from agent.provider import AssistantTurn, ChatProvider, Message, ProviderError
from agent.tools import ToolExecutionError, ToolRegistry, dumps
from harness.runtime import HarnessRuntime, SessionHarness
from skills import SkillLibrary

Approver = Callable[[str, Dict[str, Any]], bool]
Event = Dict[str, Any]


@dataclass
class AgentResult:
    session_id: str
    answer: str
    status: str  # completed | max_steps | cyclic | timeout | provider_error | blocked
    steps: List[Dict[str, Any]] = field(default_factory=list)
    log_path: Optional[str] = None


class AgentSession:
    """One conversation. `send()` streams events; `run()` is the blocking one-shot form."""

    def __init__(
        self,
        provider: ChatProvider,
        registry: ToolRegistry,
        harness: Optional[HarnessRuntime] = None,
        approve: Optional[Approver] = None,
        messages: Optional[List[Message]] = None,
        session_id: Optional[str] = None,
        skills: Optional[SkillLibrary] = None,
        extra_instructions: str = "",
        context: Optional[ContextManager] = None,
        on_compact: Optional[Callable[[CompactionResult], None]] = None,
        log_dir: Optional[Path] = None,
        audit_dir: Optional[Path] = None,
    ) -> None:
        self.provider = provider
        self.registry = registry
        self.harness = harness or HarnessRuntime()
        self.cfg = self.harness.config.agent
        self.approve = approve
        self.skills = skills
        self.extra_instructions = extra_instructions
        self.context = context
        self.on_compact = on_compact
        self.log_dir = Path(log_dir) if log_dir else None
        self.audit_dir = Path(audit_dir) if audit_dir else None
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self.estimate = context.estimate if context else TokenEstimator(self.harness.config.context)
        self.messages: List[Message] = [{"role": "system", "content": ""}, *(messages or [])]
        self.sh: Optional[SessionHarness] = None

    @property
    def history(self) -> List[Message]:
        """Messages without the system prompt: what is persisted and shown."""
        return self.messages[1:]

    # -- conversation ----------------------------------------------------------------------
    def _begin(self) -> SessionHarness:
        sh = self.harness.begin(
            self.session_id, self.skills, self.extra_instructions, self.audit_dir
        )
        self.messages[0] = {"role": "system", "content": sh.prompt.text}  # re-read every turn
        self.sh = sh
        return sh

    def send(self, user_text: str, skill: Optional[Tuple[str, str]] = None) -> Iterator[Event]:
        """Append a user message and stream events until a final answer.

        Events: text(delta), tool_call, tool_result, compact, verify, usage, done(status, answer).
        """
        sh = self._begin()
        guard, audit, strings = sh.guard, sh.audit, self.harness.strings
        audit.event(
            "turn_start",
            prompt_sha256=sh.prompt.sha256,
            prompt_version=sh.prompt.version,
            provider=self.provider.name,
        )
        self.messages.append({"role": "user", "content": user_text})
        seen: set = set()
        turn_results: List[Dict[str, Any]] = []
        started = time.monotonic()
        status, answer = "max_steps", ""
        retries, overflow_retried, steps = 0, False, 0
        if skill is not None:
            yield from self._preload_skill(skill[0], skill[1], seen, turn_results)
        for steps in range(1, self.cfg.max_steps + 1):
            if time.monotonic() - started > self.cfg.time_budget_s:
                status = "timeout"
                break
            yield from self._maybe_compact()
            audit.event("model_call", step=steps, est_tokens=self.estimate(self.messages))
            stream = guard.stream()
            pieces: List[str] = []
            turn: Optional[AssistantTurn] = None
            try:
                for event in self.provider.stream(self.messages, self.registry.functions()):
                    if event["type"] == "turn":
                        turn = event["turn"]
                    else:
                        for piece in stream.feed(event["delta"]):
                            pieces.append(piece)
                            yield {"type": "text", "delta": piece}
            except ProviderError as exc:
                if self.context and self.context.is_overflow(str(exc)) and not overflow_retried:
                    overflow_retried = True  # the model rejected the size: compact and retry once
                    yield from self._maybe_compact(force=True)
                    continue
                audit.event("provider_error", detail=str(exc))
                status, answer = "provider_error", strings.get("loop.provider_error")
                break
            for piece in stream.finish():
                pieces.append(piece)
                yield {"type": "text", "delta": piece}
            if stream.blocked:
                status, answer = "blocked", strings.get("guard.leak_blocked")
                audit.event("guard_block", rule="C-2", step=steps)
                self.messages.append({"role": "assistant", "content": answer})
                break
            assert turn is not None
            content = "".join(pieces)
            if not turn.tool_calls:
                verdict = self.harness.verifier.check(content, turn_results)
                audit.event("verify", ok=verdict.ok, reason=verdict.reason, retries=retries)
                if not verdict.ok and retries < self.harness.config.agent.verify.max_retries:
                    retries += 1
                    self.messages.append(
                        {"role": "assistant", "content": content, "superseded": True}
                    )
                    self.messages.append(
                        {"role": "user", "content": strings.get("verify.nudge"), "harness": True}
                    )
                    yield {"type": "verify", "ok": False, "retry": True}
                    continue
                if not verdict.ok:
                    warning = "\n\n" + strings.get("verify.uncited_warning")
                    content += warning
                    yield {"type": "text", "delta": warning}
                self.messages.append({"role": "assistant", "content": content})
                status, answer = "completed", content
                break
            self.messages.append(
                {
                    "role": "assistant",
                    "content": content or None,
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
            for index, call in enumerate(turn.tool_calls):
                yield {"type": "tool_call", "name": call.name, "arguments": call.arguments}
                key = (call.name, json.dumps(call.arguments, sort_keys=True))
                began = time.monotonic()
                if index >= self.cfg.max_tool_calls_per_step:
                    output: Any = ToolExecutionError(
                        "too_many_calls", "too many calls in a step"
                    ).to_dict()
                elif guard.leak.leaked(json.dumps(call.arguments, ensure_ascii=False)):
                    output = ToolExecutionError(
                        "blocked", "arguments contain internal data"
                    ).to_dict()
                    audit.event("guard_block", rule="C-2", tool=call.name)
                elif key in seen:  # an identical call twice in one task halts execution
                    cyclic = True
                    output = ToolExecutionError("cyclic_call", "repeated identical call").to_dict()
                else:
                    seen.add(key)
                    output = self._execute(call.name, call.arguments)
                spec = self.registry.tools.get(call.name)
                output = guard.tool_result(output, bool(spec and spec.untrusted))
                audit.event(
                    "tool_call",
                    tool=call.name,
                    ok="error" not in output if isinstance(output, dict) else True,
                    code=(output.get("error") or {}).get("code")
                    if isinstance(output, dict)
                    else None,
                    ms=int((time.monotonic() - began) * 1000),
                    bytes=len(dumps(output)),
                )
                turn_results.append({"tool": call.name, "result": output})
                yield {"type": "tool_result", "name": call.name, "result": output}
                self.messages.append(
                    {"role": "tool", "tool_call_id": call.id, "content": dumps(output)}
                )
                if cyclic:
                    break
            if cyclic:
                status, answer = "cyclic", strings.get("loop.cyclic")
                break
        if status in ("max_steps", "timeout"):
            answer = strings.get(f"loop.{status}")
        if status in ("cyclic", "max_steps", "timeout", "provider_error"):
            self.messages.append({"role": "assistant", "content": answer})
        audit.event("turn_end", status=status, steps=steps, guard=json.dumps(guard.hits))
        self._log()
        yield self.usage_event()
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

    # -- context ---------------------------------------------------------------------------
    def usage_event(self) -> Event:
        window = self.context.window if self.context else 0
        tokens = self.estimate(self.messages) + self.estimate(self.registry.functions())
        return {"type": "usage", "tokens": tokens, "window": window}

    def compact(self, instructions: str = "") -> Iterator[Event]:
        """Manual compaction (the /compact command)."""
        if self.sh is None:
            self._begin()
        yield from self._maybe_compact(force=True, instructions=instructions)
        yield self.usage_event()

    def _maybe_compact(self, force: bool = False, instructions: str = "") -> Iterator[Event]:
        if self.context is None or (not force and not self.context.enabled):
            return
        tools_tokens = self.estimate(self.registry.functions())
        if not force and not self.context.needs_compaction(self.messages, tools_tokens):
            return
        new_messages, result = self.context.compact(self.messages, instructions, force)
        if result is None:
            return
        self.messages[:] = new_messages
        if self.on_compact:
            self.on_compact(result)
        if self.sh:
            self.sh.audit.event(
                "compact", **{k: v for k, v in result.event().items() if k != "type"}
            )
        yield result.event()

    # -- tools -----------------------------------------------------------------------------
    def _preload_skill(
        self, name: str, arguments: str, seen: set, turn_results: List[Dict[str, Any]]
    ) -> Iterator[Event]:
        """A /skill command runs `use_skill` first so the model starts with its instructions."""
        assert self.sh is not None
        call_args = {"name": name, "arguments": arguments}
        call_id = f"skill_{uuid.uuid4().hex[:8]}"
        self.messages.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {"name": "use_skill", "arguments": dumps(call_args)},
                    }
                ],
            }
        )
        seen.add(("use_skill", json.dumps(call_args, sort_keys=True)))
        yield {"type": "tool_call", "name": "use_skill", "arguments": call_args}
        output = self.sh.guard.tool_result(self._execute("use_skill", call_args), False)
        turn_results.append({"tool": "use_skill", "result": output})
        yield {"type": "tool_result", "name": "use_skill", "result": output}
        self.messages.append({"role": "tool", "tool_call_id": call_id, "content": dumps(output)})

    def _execute(self, name: str, arguments: Dict[str, Any]) -> Any:
        spec = self.registry.tools.get(name)
        decision = self.harness.approval.decide(name, bool(spec and spec.writes))
        if decision == "deny" or (
            decision == "ask" and not (self.approve and self.approve(name, arguments))
        ):
            return ToolExecutionError("approval_denied", "this action was not approved").to_dict()
        try:
            return self.registry.call(name, arguments)
        except ToolExecutionError as exc:
            return exc.to_dict()

    # -- logs ------------------------------------------------------------------------------
    def _log_path(self) -> Optional[str]:
        return str(self.log_dir / f"{self.session_id}.jsonl") if self.log_dir else None

    def _log(self) -> None:
        path = self._log_path()
        if not path or not self.log_dir or self.sh is None:
            return
        self.log_dir.mkdir(parents=True, exist_ok=True)
        redact = self.harness.redactor.redact
        with open(path, "w", encoding="utf-8") as handle:
            for message in self.history:  # the system prompt is never written to disk
                handle.write(redact(dumps(message))[0] + "\n")
