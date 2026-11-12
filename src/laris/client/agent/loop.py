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

from laris.client.agent.context import CompactionResult, ContextManager, TokenEstimator
from laris.client.agent.provider import (
    AssistantTurn,
    AuthError,
    ChatProvider,
    Message,
    ProviderError,
    QuotaError,
)
from laris.client.agent.reflect import assess, describe
from laris.client.agent.tools import ToolExecutionError, ToolRegistry, dumps
from laris.shared.harness.runtime import HarnessRuntime, SessionHarness
from laris.shared.plan import PLAN_TOOL, Plan, PlanError
from laris.shared.policy.verifier import AnswerVerifier, Verdict
from laris.shared.policy.workflows import WorkflowSpec
from laris.shared.skills import SkillLibrary

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
        plan: Optional[List[Dict[str, str]]] = None,
        permissions: Optional[Any] = None,
        hooks: Optional[Any] = None,
    ) -> None:
        self.permissions = permissions
        self.hooks = hooks
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
        self.workflow: Optional[WorkflowSpec] = None
        self.last_turn: Dict[str, Any] = {}
        self._remote_workflow: Optional[Dict[str, str]] = None
        self.brain_trace: List[str] = []  # titles of the brain notes this turn used
        self.vault_used: List[str] = []  # project notes the brief pointed to
        self.plan = Plan(plan)  # the visible plan; kept in the conversation between turns

    @property
    def history(self) -> List[Message]:
        """Messages without the system prompt: what is persisted and shown."""
        return self.messages[1:]

    def seal_interrupted(self) -> int:
        """Make the conversation valid after a stream was closed early (Esc, SR-C1): every tool
        call that never got a result receives an `interrupted` one, so the next request to the
        model is well-formed. Returns how many results were added."""
        answered = {m.get("tool_call_id") for m in self.messages if m.get("role") == "tool"}
        added = 0
        for message in list(self.messages):
            for call in message.get("tool_calls") or []:
                if call["id"] in answered:
                    continue
                answered.add(call["id"])
                result = {"error": {"code": "interrupted", "message": "interrupted by the user"}}
                position = self.messages.index(message) + 1
                while (
                    position < len(self.messages) and self.messages[position].get("role") == "tool"
                ):
                    position += 1  # keep the results of one assistant message together
                self.messages.insert(
                    position, {"role": "tool", "tool_call_id": call["id"], "content": dumps(result)}
                )
                added += 1
        return added

    # -- conversation ----------------------------------------------------------------------
    # -- agentic planning ------------------------------------------------------------------
    def _plan_required(self, text: str, wf: Optional[WorkflowSpec]) -> bool:
        cfg = self.cfg.plan
        if cfg.mode == "off":
            return False
        if cfg.mode == "always" or wf is not None:
            return True
        return len(text.split()) >= cfg.min_request_words

    def _plan_event(self, source: str) -> Event:
        return {"type": "plan", "source": source, "steps": self.plan.to_list()}

    def _model_view(self, required: bool, leftover: bool) -> List[Message]:
        """What the model sees: the conversation plus, for this call only, the current plan."""
        if self.cfg.plan.mode == "off" or not (self.plan or required):
            return self.messages
        strings = self.harness.strings
        lines = [strings.get("plan.header")]
        if self.plan:
            lines.append(self.plan.render())
            if leftover and self.plan.open_steps():
                lines.append(strings.get("plan.resumed"))
        else:
            lines.append(strings.get("plan.required"))
        return [*self.messages, {"role": "user", "content": "\n".join(lines), "harness": True}]

    def _update_plan(self, arguments: Dict[str, Any]) -> Any:
        try:
            self.plan.update(arguments, self.cfg.plan)
        except PlanError as exc:
            reason = self.harness.strings.get("plan.invalid", reason=str(exc))
            return ToolExecutionError("invalid_plan", reason).to_dict()
        return {"plan": self.plan.to_list()}

    def _begin(self, workflow_text: str = "") -> SessionHarness:
        sh = self.harness.begin(
            self.session_id, self.skills, self.extra_instructions, self.audit_dir, workflow_text
        )
        system: Message = {"role": "system", "content": sh.prompt.text}  # re-read every turn
        if sh.prompt.remote is not None:  # policy server: it composes the prompt from these layers
            system["laris"] = {**sh.prompt.remote, "workflow": self._remote_workflow}
        self.messages[0] = system
        self.sh = sh
        return sh

    def send(
        self,
        user_text: str,
        skill: Optional[Tuple[str, str]] = None,
        workflow: Optional[Tuple[WorkflowSpec, str]] = None,
    ) -> Iterator[Event]:
        """Append a user message and stream events until a final answer.

        Events: text(delta), tool_call, tool_result, compact, verify, usage, done(status, answer).
        """
        wf = workflow[0] if workflow else None
        self._remote_workflow = (
            {"name": wf.name, "request": self.harness.redactor.redact_secrets(workflow[1])[0]}
            if wf and workflow and self.harness.remote
            else None
        )
        sh = self._begin(
            wf.render(workflow[1], self.harness.config.prompts.workflow_max_chars)
            if wf and workflow and not self.harness.remote
            else ""
        )
        self.workflow = wf
        max_steps = min(self.cfg.max_steps, wf.max_steps) if wf else self.cfg.max_steps
        verifier = self.harness.verifier
        if wf and wf.require_citations:
            stricter = self.harness.config.agent.verify.model_copy(
                update={"require_citations": True}
            )
            verifier = AnswerVerifier(stricter)
        allowed = set(wf.allowed_tools) if wf else None
        planning = self.cfg.plan.mode != "off"
        if allowed is not None and planning:
            allowed.add(PLAN_TOOL)  # planning is part of the harness, not of a workflow's toolset
        tools = [
            f
            for f in self.registry.functions()
            if (allowed is None or f["function"]["name"] in allowed)
            and (planning or f["function"]["name"] != PLAN_TOOL)
        ]
        guard, audit, strings = sh.guard, sh.audit, self.harness.strings
        audit.event(
            "turn_start",
            prompt_sha256=sh.prompt.sha256,
            prompt_version=sh.prompt.version,
            provider=self.provider.name,
            workflow=wf.name if wf else "",
        )
        verified = True
        user_text = self.harness.redactor.redact_secrets(user_text)[0]  # never store a typed key
        if sh.prompt.remote is not None:
            self.messages[0]["laris"]["task"] = user_text[:2000]
        self.messages.append({"role": "user", "content": user_text})
        seen: set = set()
        turn_results: List[Dict[str, Any]] = []
        started = time.monotonic()
        status, answer = "max_steps", ""
        retries, overflow_retried, steps = 0, False, 0
        plan_required = self._plan_required(user_text, wf)
        leftover = bool(self.plan.open_steps())  # a plan carried over from an earlier turn
        replans = completion_nudges = 0
        budget_told = False
        goal_open: List[str] = []
        auto_steps: Dict[str, int] = {}
        if leftover and planning:
            yield self._plan_event("resumed")
        if skill is not None:
            yield from self._preload_skill(skill[0], skill[1], seen, turn_results)
        yield from self._consult_brain(user_text, wf, allowed)
        for steps in range(1, max_steps + 1):
            if time.monotonic() - started > self.cfg.time_budget_s:
                status = "timeout"
                break
            yield from self._maybe_compact()
            audit.event("model_call", step=steps, est_tokens=self.estimate(self.messages))
            stream = guard.stream()
            pieces: List[str] = []
            turn: Optional[AssistantTurn] = None
            try:
                for event in self.provider.stream(self._model_view(plan_required, leftover), tools):
                    if event["type"] == "turn":
                        turn = event["turn"]
                    elif event["type"] == "reasoning":
                        continue  # a model's private reasoning is never shown, kept or logged here
                    elif event["type"] == "brain":
                        self.brain_trace = [str(t) for t in event.get("trace", [])]
                        yield event
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
                status = "provider_error"
                answer = self._provider_failure_text(exc, strings)
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
                verdict = verifier.check(content, turn_results)
                if verdict.ok and wf and wf.output_sections:
                    missing = [s for s in wf.output_sections if s.lower() not in content.lower()]
                    if missing:
                        verdict = Verdict(False, "sections:" + ", ".join(missing))
                audit.event("verify", ok=verdict.ok, reason=verdict.reason, retries=retries)
                if not verdict.ok and retries < self.harness.config.agent.verify.max_retries:
                    retries += 1
                    self.messages.append(
                        {"role": "assistant", "content": content, "superseded": True}
                    )
                    self.messages.append(
                        {
                            "role": "user",
                            "content": self._nudge(verdict.reason, strings),
                            "harness": True,
                        }
                    )
                    yield {"type": "verify", "ok": False, "retry": True}
                    continue
                goal_open = self.plan.open_steps() if planning and self.plan else []
                if goal_open and self.cfg.reflect.enabled:
                    if completion_nudges < self.cfg.reflect.completion_retries:
                        completion_nudges += 1  # the goal is not done: ask for the rest
                        self.messages.append(
                            {"role": "assistant", "content": content, "superseded": True}
                        )
                        text = strings.get("plan.incomplete", open="; ".join(goal_open))
                        self.messages.append({"role": "user", "content": text, "harness": True})
                        audit.event("goal_open", open=len(goal_open), nudges=completion_nudges)
                        yield {"type": "goal", "complete": False, "open": goal_open, "retry": True}
                        continue
                    warning = "\n\n" + strings.get(
                        "plan.incomplete_warning", open="; ".join(goal_open)
                    )
                    content += warning
                    yield {"type": "text", "delta": warning}
                if not verdict.ok:
                    verified = False
                    warning = "\n\n" + self._warning(verdict.reason, strings)
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
            issues: List[str] = []
            acting = [c for c in turn.tool_calls if c.name != PLAN_TOOL]
            if planning and plan_required and not self.plan and acting:
                # the model started acting without a plan: the harness records one, visibly
                for call in acting:
                    text = strings.get("plan.auto_step", tool=call.name)
                    auto_steps[call.id] = self.plan.add_auto(text, self.cfg.plan)
                yield self._plan_event("auto")
            for index, call in enumerate(turn.tool_calls):
                yield {"type": "tool_call", "name": call.name, "arguments": call.arguments}
                key = (call.name, json.dumps(call.arguments, sort_keys=True))
                began = time.monotonic()
                if call.name == PLAN_TOOL and planning:
                    output: Any = self._update_plan(call.arguments)
                    leftover = False
                elif index >= self.cfg.max_tool_calls_per_step:
                    output = ToolExecutionError(
                        "too_many_calls", "too many calls in a step"
                    ).to_dict()
                elif allowed is not None and call.name not in allowed:
                    output = ToolExecutionError(
                        "tool_not_allowed", strings.get("loop.tool_not_allowed")
                    ).to_dict()
                    audit.event("guard_block", rule="W-3", tool=call.name)
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
                if call.name == PLAN_TOOL:
                    if "error" not in output:
                        yield self._plan_event("model")
                else:
                    problem = assess(call.name, output, self.cfg.reflect.empty_keys)
                    if call.id in auto_steps:
                        self.plan.mark(auto_steps[call.id], "failed" if problem else "done")
                    if problem:
                        issues.append(describe(problem[0], problem[1], call.name, strings))
                if cyclic:
                    break
            if issues and self.cfg.reflect.enabled and not cyclic:
                # reflect: the step did not get anywhere; allow a bounded change of approach
                if replans < self.cfg.reflect.max_replans:
                    replans += 1
                    text = strings.get(
                        "reflect.step_failed",
                        issues="; ".join(issues),
                        left=self.cfg.reflect.max_replans - replans,
                    )
                    self.messages.append({"role": "user", "content": text, "harness": True})
                    audit.event("reflect", issues=len(issues), replans=replans)
                    yield {"type": "reflect", "issues": issues, "replans": replans}
                elif not budget_told:
                    budget_told = True
                    text = strings.get("reflect.budget_out")
                    self.messages.append({"role": "user", "content": text, "harness": True})
                    audit.event("reflect", issues=len(issues), budget_out=True)
                    yield {"type": "reflect", "issues": issues, "budget_out": True}
            if cyclic:
                status, answer = "cyclic", strings.get("loop.cyclic")
                break
        if status in ("max_steps", "timeout"):
            answer = strings.get(f"loop.{status}")
        if status in ("cyclic", "max_steps", "timeout", "provider_error"):
            self.messages.append({"role": "assistant", "content": answer})
        self.last_turn = {
            "status": status,
            "verified": verified,
            "guard_hits": dict(guard.hits),
            "workflow": wf.name if wf else "",
            "prompt_version": sh.prompt.version,
            "goal": (
                "none" if not (planning and self.plan) else "complete" if not goal_open else "open"
            ),
            "replans": replans,
            "brain_trace": list(self.brain_trace),
            "vault_notes": list(self.vault_used),
        }
        audit.event("turn_end", status=status, steps=steps, guard=json.dumps(guard.hits))
        self._log()
        if planning and self.plan:
            open_now = self.plan.open_steps()
            yield {
                "type": "goal",
                "complete": not open_now,
                "open": open_now,
                "failed": self.plan.failed_steps(),
            }
        yield self.usage_event()
        yield {"type": "done", "status": status, "answer": answer}

    @staticmethod
    def _provider_failure_text(exc: ProviderError, strings: Any) -> str:
        if isinstance(exc, QuotaError):
            try:
                return str(strings.get("loop.quota_exceeded"))
            except KeyError:
                return str(exc)
        return str(
            strings.get("loop.auth_error" if isinstance(exc, AuthError) else "loop.provider_error")
        )

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
    @staticmethod
    def _nudge(reason: str, strings: Any) -> str:
        if reason.startswith("sections:"):
            return str(strings.get("verify.sections_nudge", missing=reason[9:].strip()))
        return str(strings.get("verify.nudge"))

    @staticmethod
    def _warning(reason: str, strings: Any) -> str:
        if reason.startswith("sections:"):
            return str(strings.get("verify.sections_warning", missing=reason[9:].strip()))
        return str(strings.get("verify.uncited_warning"))

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

    def _consult_brain(
        self, task: str, wf: Optional[WorkflowSpec], allowed: Optional[set]
    ) -> Iterator[Event]:
        """Before answering, enter the brain at the hub that matches the task and add a short brief.

        The brief reaches the model as a hidden harness message; the user only sees the titles of
        the notes used (never their text). Skipped when disabled or when the workflow excludes it.
        """
        assert self.sh is not None
        self.brain_trace, self.vault_used = [], []
        cfg = self.harness.config.brain
        brain = self.harness.brain
        brain.begin_turn()
        if cfg.consult == "off" or not brain.available:
            return
        if "brain_consult" not in self.registry.tools:
            return
        if allowed is not None and "brain_consult" not in allowed:
            return
        found = brain.consult(task, wf.name if wf else "", cfg.consult == "always")
        if found is None:
            return
        text = self.sh.guard.tool_result({"brief": found.brief}, False)["brief"]
        header = self.harness.strings.get("brain.brief_header")
        self.messages.append({"role": "user", "content": f"{header}\n{text}", "harness": True})
        self.sh.audit.event("brain_consult", notes=json.dumps(found.trace))
        self.brain_trace, self.vault_used = list(found.trace), list(found.vault_notes)
        yield {"type": "brain", "trace": found.trace}

    def _execute(self, name: str, arguments: Dict[str, Any]) -> Any:
        spec = self.registry.tools.get(name)
        writes = bool(spec and spec.writes)
        if self.hooks is not None:  # a PreToolUse hook can only block, never grant
            pre = self.hooks.run(
                "PreToolUse", {"tool_name": name, "tool_input": arguments}, tool=name
            )
            if pre.blocked:
                return ToolExecutionError("hook_blocked", pre.reason).to_dict()
        if self.permissions is not None:  # modes and rules (SR-C3)
            decision = self.permissions.decide(name, arguments, writes).action
        else:
            decision = self.harness.approval.decide(name, writes)
        wf = getattr(self, "workflow", None)
        if wf is not None and writes:  # a workflow can only make approval stricter (W-1)
            if wf.approval == "deny":
                decision = "deny"
            elif wf.approval == "ask" and decision == "allow":
                decision = "ask"
        if decision == "deny" or (
            decision == "ask" and not (self.approve and self.approve(name, arguments))
        ):
            return ToolExecutionError("approval_denied", "this action was not approved").to_dict()
        try:
            result = self.registry.call(name, arguments)
        except ToolExecutionError as exc:
            return exc.to_dict()
        if self.hooks is not None:
            post = self.hooks.run(
                "PostToolUse",
                {"tool_name": name, "tool_input": arguments, "tool_response": result},
                tool=name,
            )
            feedback = "\n".join(([post.reason] if post.blocked else []) + post.context).strip()
            if feedback:
                result = (
                    {**result, "hook_feedback": feedback}
                    if isinstance(result, dict)
                    else {"result": result, "hook_feedback": feedback}
                )
        return result

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
