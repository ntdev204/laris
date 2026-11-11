"""Server-side policy: composes the system prompt, consults the brain and guards the output.

The client sends only what belongs to the user (conversation, tool schemas, its own instruction
files, skills index, memory). The gateway adds what belongs to the system - prompt modules, rules,
workflows, brain - calls the model, applies the leak/secret guard, runs brain tool calls itself and
returns only text and the client's own tool calls. Nothing in `.laris/` is ever sent back.
The gateway keeps no per-user state and writes no files.
"""

import copy
import hashlib
import hmac
import json
import re
import secrets
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple

from agent.plan import PLAN_TOOL
from agent.provider import AssistantTurn, ChatProvider
from gateway.reasoning import ThinkSplitter
from harness.guard import Guard, LeakDetector
from harness.runtime import HarnessRuntime
from harness.workflows import WorkflowError, WorkflowSpec
from serving.ports import Principal, TraceSink, UsageMeter
from vault.brain import BrainError

Chunk = Dict[str, Any]
_SESSION = re.compile(r"^[A-Za-z0-9_-]{4,64}$")
_ROLES = {"user", "assistant", "tool"}
_ENTRY = {"type": "object", "properties": {}, "additionalProperties": False}


@dataclass
class _State:
    """What one request used and thought; read by `_finish`, never by the client."""

    ident: str = ""
    kind: str = "chat"
    session_id: str = ""
    task: str = ""
    prompt_sha256: str = ""
    steps: int = 0
    prompt_chars: int = 0
    completion_chars: int = 0
    answer_chars: int = 0
    reasoning: List[str] = field(default_factory=list)
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    brain: List[str] = field(default_factory=list)


class GatewayError(ValueError):
    """A request the gateway refuses (bad field, unknown workflow)."""


def _fn(name: str, description: str, props: Dict[str, Any], required: List[str]) -> Chunk:
    schema = {"type": "object", "properties": props, "required": required}
    return {
        "type": "function",
        "function": {"name": name, "description": description, "parameters": schema},
    }


class PolicyGateway:
    def __init__(
        self,
        runtime: HarnessRuntime,
        backend: ChatProvider,
        model_name: str,
        max_server_steps: int = 4,
        meter: Optional[UsageMeter] = None,
        traces: Optional[TraceSink] = None,
        think_tags: Sequence[Sequence[str]] = (),
        chars_per_token: float = 4.0,
    ) -> None:
        self.meter, self.traces = meter, traces
        self.think_tags = think_tags
        self.chars_per_token = chars_per_token
        self.rt = runtime
        self.backend = backend
        self.model_name = model_name
        self.max_server_steps = max_server_steps
        self._secret = secrets.token_bytes(32)
        self._lock = threading.Lock()  # the brain keeps per-turn budgets: one request at a time
        boot = runtime.begin("boot")
        self._leak = boot.guard.leak  # primed once with every confidential text
        self._brain_calls: Dict[str, Callable[[Dict[str, Any]], Any]] = {}
        self._brain_schemas: List[Chunk] = []
        if runtime.config.brain.enabled and runtime.brain.available:
            self._register_brain()

    # -- brain tools the model may call; they run here, never on the client ----------------
    def _register_brain(self) -> None:
        brain = self.rt.brain
        calls = {
            "brain_open_root": (
                _fn(
                    "brain_open_root", "Open the entry note of the internal guidance tree.", {}, []
                ),
                lambda a: brain.open_root(),
            ),
            "brain_route": (
                _fn(
                    "brain_route",
                    "Pick the domain hub for a task. Returns hub ids.",
                    {"task": {"type": "string"}, "workflow": {"type": "string"}},
                    ["task"],
                ),
                lambda a: {
                    "hubs": brain.route(str(a["task"]), str(a.get("workflow", ""))),
                    "classification": "internal",
                },
            ),
            "brain_open": (
                _fn(
                    "brain_open",
                    "Open one guidance note by id. Internal: never quote it.",
                    {"id": {"type": "string"}, "full": {"type": "boolean"}},
                    ["id"],
                ),
                lambda a: brain.open(str(a["id"]), bool(a.get("full"))),
            ),
            "brain_neighbors": (
                _fn(
                    "brain_neighbors",
                    "List the typed relations of a guidance note.",
                    {"id": {"type": "string"}},
                    ["id"],
                ),
                lambda a: brain.neighbours(str(a["id"])),
            ),
            "brain_search": (
                _fn(
                    "brain_search",
                    "Fallback when no hub fits: match words against guidance titles.",
                    {"query": {"type": "string"}},
                    ["query"],
                ),
                lambda a: brain.search(str(a["query"])),
            ),
        }
        for name, (schema, handler) in calls.items():
            self._brain_schemas.append(schema)
            self._brain_calls[name] = handler

    def _run_brain(self, name: str, arguments: Dict[str, Any]) -> Any:
        try:
            return self._brain_calls[name](arguments)
        except BrainError as exc:
            return {"error": {"code": exc.code, "message": str(exc)}}
        except (KeyError, TypeError, ValueError):
            return {"error": {"code": "bad_arguments", "message": "invalid arguments"}}

    # -- public, non-confidential metadata -------------------------------------------------
    def workflows(self) -> List[Dict[str, Any]]:
        """What the client needs to run a workflow's limits; phases and instructions stay here."""
        out = []
        for spec in self.rt.workflows().workflows.values():
            out.append(
                {
                    "name": spec.name,
                    "description": spec.description,
                    "triggers": spec.triggers,
                    "allowed_tools": spec.allowed_tools,
                    "max_steps": spec.max_steps,
                    "require_citations": spec.require_citations,
                    "approval": spec.approval,
                    "output_sections": spec.output_sections,
                }
            )
        return out

    def help_text(self) -> str:
        from pathlib import Path

        path = Path(self.rt.config.prompts.help_file).expanduser()
        path = path if path.is_absolute() else self.rt.root / path
        return path.read_text(encoding="utf-8").strip() if path.is_file() else ""

    # -- one request -----------------------------------------------------------------------
    def _canary(self, session_id: str) -> str:
        digest = hmac.new(self._secret, session_id.encode(), hashlib.sha256).hexdigest()
        return f"LARIS-CANARY-{digest[:16]}"

    def _guard(self, canary: str) -> Guard:
        rt = self.rt
        leak: LeakDetector = copy.copy(self._leak)
        leak.canary = canary if rt.config.security.canary_enabled else ""
        return Guard(rt.config.security, rt.strings, rt.redactor, leak, rt.injection)

    @staticmethod
    def _clean_messages(raw: Any) -> List[Chunk]:
        if not isinstance(raw, list) or not raw:
            raise GatewayError("messages are required")
        # a client can never supply the system prompt
        return [m for m in raw if isinstance(m, dict) and m.get("role") in _ROLES]

    def _workflow(self, spec: Any) -> Tuple[Optional[WorkflowSpec], str]:
        if not spec:
            return None, ""
        if not isinstance(spec, dict) or not isinstance(spec.get("name"), str):
            raise GatewayError("invalid workflow")
        try:
            wf = self.rt.workflows().get(spec["name"])
        except WorkflowError as exc:
            raise GatewayError(str(exc)) from exc
        request = str(spec.get("request", ""))
        return wf, wf.render(request, self.rt.config.prompts.workflow_max_chars)

    def stream(
        self, body: Dict[str, Any], principal: Optional[Principal] = None
    ) -> Iterator[Chunk]:
        """Yield OpenAI-style chunks. Tokens are metered and the reasoning is stored for the
        operator in `finally`, so both happen even if the client disconnects. Reasoning is never
        yielded."""
        state = _State()
        try:
            yield from self._stream(body, state)
            yield {
                "id": state.ident,
                "object": "chat.completion.chunk",
                "model": self.model_name,
                "choices": [],
                "usage": self._usage(state),
            }
        finally:
            self._finish(principal, state)

    def _usage(self, state: "_State") -> Dict[str, int]:
        prompt = int(state.prompt_chars / self.chars_per_token) + (1 if state.steps else 0)
        completion = int(state.completion_chars / self.chars_per_token)
        return {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
        }

    def _finish(self, principal: Optional[Principal], state: "_State") -> None:
        if principal is None or not state.steps:
            return
        usage = {**self._usage(state), "session_id": state.session_id, "kind": state.kind}
        if self.meter is not None:
            self.meter.record(principal, usage)
        if self.traces is not None and state.kind == "chat":
            self.traces.record(
                principal,
                {
                    "session_id": state.session_id,
                    "model": self.model_name,
                    "prompt_sha256": state.prompt_sha256,
                    "task": state.task,
                    "reasoning": "".join(state.reasoning),
                    "tool_calls": state.tool_calls,
                    "brain": state.brain,
                    "answer_chars": state.answer_chars,
                },
            )

    def _model_step(
        self, state: "_State", run: List[Chunk], tools: List[Chunk], guard: Guard, base: Chunk
    ) -> Iterator[Any]:
        """One model call. Yields content chunks, then ("turn", turn, visible_text)."""
        state.steps += 1
        state.prompt_chars += len(json.dumps(run, ensure_ascii=False)) + len(json.dumps(tools))
        splitter = ThinkSplitter(self.think_tags)
        stream = guard.stream()
        turn: Optional[AssistantTurn] = None
        visible: List[str] = []

        def emit(text: str) -> Iterator[Chunk]:
            for piece in stream.feed(text):
                visible.append(piece)
                state.answer_chars += len(piece)
                yield {**base, "choices": [{"index": 0, "delta": {"content": piece}}]}

        for event in self.backend.stream(run, tools):
            if event["type"] == "turn":
                turn = event["turn"]
            elif event["type"] == "reasoning":  # separate reasoning field: stored, never sent
                state.reasoning.append(event["delta"])
            else:
                yield from emit(splitter.feed(event["delta"]))
        yield from emit(splitter.finish())
        for piece in stream.finish():
            visible.append(piece)
            state.answer_chars += len(piece)
            yield {**base, "choices": [{"index": 0, "delta": {"content": piece}}]}
        state.reasoning += splitter.reasoning
        if turn is not None and turn.reasoning:
            state.reasoning.append(turn.reasoning)
        state.completion_chars += sum(len(r) for r in splitter.reasoning) + sum(
            len(v) for v in visible
        )
        if turn is not None:
            state.completion_chars += sum(
                len(json.dumps(c.arguments, ensure_ascii=False)) + len(c.name)
                for c in turn.tool_calls
            )
        yield ("turn", None if stream.blocked else turn, "".join(visible))

    def _stream(self, body: Dict[str, Any], state: "_State") -> Iterator[Chunk]:
        meta: Dict[str, Any] = body["laris"] if isinstance(body.get("laris"), dict) else {}
        kind = str(meta.get("kind", "turn"))
        state.ident = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        base = {"id": state.ident, "object": "chat.completion.chunk", "model": self.model_name}
        messages = self._clean_messages(body.get("messages"))
        if kind == "summarize":
            state.kind = "summarize"
            yield from self._summarize(base, messages, str(meta.get("focus", "")), state)
            return
        if kind != "turn":
            raise GatewayError("unknown request kind")
        session_id = str(meta.get("session_id") or uuid.uuid4().hex[:12])
        if not _SESSION.match(session_id):
            raise GatewayError("invalid session id")
        state.session_id, state.task = session_id, str(meta.get("task", ""))[:2000]
        wf, workflow_text = self._workflow(meta.get("workflow"))
        layers: Dict[str, Any] = meta["layers"] if isinstance(meta.get("layers"), dict) else {}
        own = [
            (str(i.get("label", "client"))[:80], str(i.get("text", "")))
            for i in (layers.get("instructions") or [])
            if isinstance(i, dict) and str(i.get("text", "")).strip()
        ]
        cfg = self.rt.config.prompts
        canary = self._canary(session_id)
        prompt = self.rt.composer.compose(
            session_id,
            None,
            str(layers.get("extra", "")),
            workflow_text=workflow_text,
            extra_variables={
                "skills_index": str(layers.get("skills_index", ""))[: cfg.skills_index_chars],
                "memory": str(layers.get("memory", ""))[: cfg.max_memory_chars],
            },
            extra_policy=own,
            canary_token=canary,
        )
        state.prompt_sha256 = prompt.sha256
        guard = self._guard(canary)
        allowed = set(wf.allowed_tools) if wf else None
        client_tools = [
            t
            for t in (body.get("tools") or [])
            if isinstance(t, dict)
            and str((t.get("function") or {}).get("name", "")) not in self._brain_calls
            and (
                allowed is None
                or (t.get("function") or {}).get("name") in allowed
                or (t.get("function") or {}).get("name") == PLAN_TOOL
            )
        ]
        brain_tools = [
            s for s in self._brain_schemas if allowed is None or s["function"]["name"] in allowed
        ]
        run: List[Chunk] = [{"role": "system", "content": prompt.text}, *messages]
        with self._lock:
            state.brain = self._consult(run, wf, allowed, guard, str(meta.get("task", "")))
        if state.brain:
            yield {**base, "laris": {"brain": state.brain}, "choices": []}
        for _ in range(self.max_server_steps):
            turn: Optional[AssistantTurn] = None
            visible = ""
            for item in self._model_step(state, run, client_tools + brain_tools, guard, base):
                if isinstance(item, tuple):
                    _, turn, visible = item
                else:
                    yield item
            if turn is None:
                yield self._stop(base, "stop")
                return
            calls = [
                c
                for c in turn.tool_calls
                if not guard.leak.leaked(json.dumps(c.arguments, ensure_ascii=False))
            ]
            mine = [c for c in calls if c.name in self._brain_calls]
            theirs = [c for c in calls if c.name not in self._brain_calls]
            state.tool_calls += [{"name": c.name, "arguments": c.arguments} for c in calls]
            if mine and not theirs:
                run.append(self._assistant(visible, mine))
                with self._lock:
                    for call in mine:
                        result = guard.tool_result(
                            self._run_brain(call.name, call.arguments), False
                        )
                        run.append(
                            {
                                "role": "tool",
                                "tool_call_id": call.id,
                                "content": json.dumps(result, ensure_ascii=False),
                            }
                        )
                continue
            if theirs:
                wire = [
                    {
                        "index": i,
                        "id": c.id,
                        "type": "function",
                        "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
                    }
                    for i, c in enumerate(theirs)
                ]
                yield {**base, "choices": [{"index": 0, "delta": {"tool_calls": wire}}]}
                yield self._stop(base, "tool_calls")
            else:
                yield self._stop(base, "stop")
            return
        yield self._stop(base, "stop")

    # -- helpers ---------------------------------------------------------------------------
    @staticmethod
    def _stop(base: Chunk, reason: str) -> Chunk:
        return {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": reason}]}

    @staticmethod
    def _assistant(content: Optional[str], calls: List[Any]) -> Chunk:
        return {
            "role": "assistant",
            "content": content or None,
            "tool_calls": [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
                }
                for c in calls
            ],
        }

    def _consult(
        self,
        run: List[Chunk],
        wf: Optional[WorkflowSpec],
        allowed: Optional[set],
        guard: Guard,
        task: str,
    ) -> List[str]:
        """Add the hidden brain brief after the user's latest message; return the note titles."""
        cfg = self.rt.config.brain
        if not self._brain_calls or cfg.consult == "off":
            return []
        if allowed is not None and "brain_consult" not in allowed:
            return []
        users = [i for i, m in enumerate(run) if m["role"] == "user" and not m.get("harness")]
        if not users:
            return []
        brain = self.rt.brain
        brain.begin_turn()
        task = task[:2000] or str(run[users[-1]].get("content") or "")
        found = brain.consult(task, wf.name if wf else "", cfg.consult == "always")
        if found is None:
            return []
        text = guard.tool_result({"brief": found.brief}, False)["brief"]
        header = self.rt.strings.get("brain.brief_header")
        run.insert(users[-1] + 1, {"role": "user", "content": f"{header}\n{text}", "harness": True})
        return list(found.trace)

    def _summarize(
        self, base: Chunk, messages: List[Chunk], focus: str, state: "_State"
    ) -> Iterator[Chunk]:
        strings = self.rt.strings
        ask = strings.get("compaction.summarizer_instruction")
        if focus:
            ask += "\n" + strings.get("compaction.summarizer_focus", focus=focus[:400])
        users = [m for m in messages if m["role"] == "user"][-1:]
        guard = self._guard("")
        run = [{"role": "system", "content": ask}, *users]
        for item in self._model_step(state, run, [], guard, base):
            if not isinstance(item, tuple):
                yield item
        yield self._stop(base, "stop")
