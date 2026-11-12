"""`laris engine --stdio`: the agent session behind engine protocol E1.

A reader thread parses commands (JSON lines) and queues them; the main loop handles them one at a
time; a turn runs in its own thread so `permission_response` and `interrupt` are heard while the
agent works. The engine owns every behaviour: the session, tools, approvals, settings and storage.
Whatever ends the front end (a `shutdown` command, end of input, a kill) the running turn is closed,
which saves the conversation, so the stored state is always consistent.
"""

import json
import queue
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, TextIO

from laris.protocol import engine as e1


def map_event(event: Dict[str, Any], calls: Dict[str, List[str]], counter: List[int]) -> List[Any]:
    """One agent-session event as E1 messages. `calls` pairs each tool_result with its call."""
    kind = event.get("type")
    rest = {k: v for k, v in event.items() if k != "type"}
    if kind == "text":
        return [e1.Text(delta=str(event["delta"]))]
    if kind == "tool_call":
        counter[0] += 1
        call_id = f"call_{counter[0]}"
        calls.setdefault(str(event["name"]), []).append(call_id)
        return [e1.ToolCall(id=call_id, name=str(event["name"]), arguments=event["arguments"])]
    if kind == "tool_result":
        waiting = calls.get(str(event["name"]))
        if waiting:
            call_id = waiting.pop(0)
        else:
            counter[0] += 1
            call_id = f"call_{counter[0]}"
        return [e1.ToolResult(id=call_id, name=str(event["name"]), result=event["result"])]
    if kind == "plan":
        return [e1.PlanEvent(source=str(event.get("source", "")), steps=event.get("steps", []))]
    if kind == "usage":
        return [e1.Usage(tokens=int(event["tokens"]), window=int(event["window"]))]
    if kind == "compact":
        return [
            e1.Compact(
                before=int(event["before"]),
                after=int(event["after"]),
                summarized=int(event.get("summarized", 0)),
                method=str(event.get("method", "")),
            )
        ]
    if kind == "goal":
        return [
            e1.Goal(
                complete=bool(event["complete"]),
                open=list(event.get("open") or []),
                failed=list(event.get("failed") or []),
                retry=bool(event.get("retry", False)),
            )
        ]
    if kind == "done":
        return [e1.Done(status=str(event["status"]), answer=str(event.get("answer", "")))]
    return [e1.Status(kind=str(kind), data=json.loads(json.dumps(rest, default=str)))]


class _Pending:
    def __init__(self) -> None:
        self.done = threading.Event()
        self.allowed = False


class Engine:
    def __init__(
        self,
        chat: Any,
        reader: TextIO,
        writer: TextIO,
        version: str,
        cwd: Optional[Path] = None,
        conversation: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.chat = chat
        self.reader, self.writer = reader, writer
        self.version = version
        self.cwd = Path(cwd or Path.cwd())
        self.conversation = conversation or chat.conversations.create()
        self.mode = chat.runtime.config.agent.approval.mode
        self.commands: Dict[str, Callable[[str], Iterable[Any]]] = {
            "help": self._help,
            "compact": self._compact,
        }
        self._out = threading.Lock()
        self._inbox: "queue.Queue[Optional[Dict[str, Any]]]" = queue.Queue()
        self._pending: Dict[str, _Pending] = {}
        self._pending_lock = threading.Lock()
        self._allowed: set = set()  # tools approved "for this session"
        self._interrupted = threading.Event()
        self._turn: Optional[threading.Thread] = None
        self._permission_count = 0

    # -- output ----------------------------------------------------------------------------
    def emit(self, message: Any) -> None:
        line = json.dumps(message.model_dump(mode="json"), ensure_ascii=False)
        with self._out:
            self.writer.write(line + "\n")
            self.writer.flush()

    def _error(self, code: str, text: str) -> None:
        self.emit(e1.ErrorEvent(code=code, message=text))

    # -- input -----------------------------------------------------------------------------
    def _read(self) -> None:
        """Parse commands as they arrive. Permission answers and interrupts act at once, from
        here, because the turn thread may be waiting for them."""
        try:
            for line in self.reader:
                if not line.strip():
                    continue
                try:
                    command = e1.parse_command(json.loads(line))
                except (ValueError, e1.ProtocolError) as exc:
                    self._error("bad_command", str(exc))
                    continue
                if isinstance(command, e1.PermissionResponse):
                    self._answer(command)
                elif isinstance(command, e1.Interrupt):
                    self._interrupt()
                else:
                    self._inbox.put(command.model_dump())
        finally:
            self._inbox.put(None)  # end of input: the front end is gone

    def _answer(self, response: Any) -> None:
        with self._pending_lock:
            pending = self._pending.pop(response.id, None)
        if pending is None:
            self._error("unknown_permission", f"no pending permission request {response.id!r}")
            return
        pending.allowed = response.decision == "allow"
        pending.done.set()

    def _interrupt(self) -> None:
        self._interrupted.set()
        with self._pending_lock:
            waiting, self._pending = list(self._pending.values()), {}
        for pending in waiting:  # a request nobody can answer any more is a refusal
            pending.allowed = False
            pending.done.set()

    # -- permissions -----------------------------------------------------------------------
    def _approve(self, name: str, arguments: Dict[str, Any]) -> bool:
        if name in self._allowed:
            return True
        self._permission_count += 1
        request_id = f"perm_{self._permission_count}"
        pending = _Pending()
        with self._pending_lock:
            self._pending[request_id] = pending
        self.emit(
            e1.PermissionRequest(
                id=request_id, tool=name, arguments=arguments, reason="needs your approval"
            )
        )
        pending.done.wait()
        return pending.allowed

    # -- turns -----------------------------------------------------------------------------
    def _run_turn(self, text: str) -> None:
        calls: Dict[str, List[str]] = {}
        counter = [0]
        stream = self.chat.send(self.conversation["id"], text, self._approve)
        finished = False
        try:
            for event in stream:
                if self._interrupted.is_set():
                    break
                for message in map_event(event, calls, counter):
                    finished = finished or isinstance(message, e1.Done)
                    self.emit(message)
        except Exception as exc:  # the engine reports it and stays up for the next message
            self._error("turn_failed", f"{type(exc).__name__}: {exc}")
            finished = False
        finally:
            stream.close()  # saves the conversation even when interrupted
        if not finished:
            status = "interrupted" if self._interrupted.is_set() else "error"
            self.emit(e1.Done(status=status, answer=""))
        self._interrupted.clear()

    def _start_turn(self, text: str) -> None:
        if self._turn is not None and self._turn.is_alive():
            self._error("busy", "a turn is already running; send `interrupt` first")
            return
        self._interrupted.clear()
        self._turn = threading.Thread(target=self._run_turn, args=(text,), daemon=True)
        self._turn.start()

    def _join_turn(self) -> None:
        if self._turn is not None:
            self._turn.join(timeout=30)

    # -- slash commands and completion -----------------------------------------------------
    def _help(self, args: str) -> Iterable[Any]:
        return [e1.Text(delta=self.chat.how_to_use() + "\n"), e1.Done(status="completed")]

    def _compact(self, args: str) -> Iterable[Any]:
        session = self.chat._session(self.chat.conversations.get(self.conversation["id"]))
        out: List[Any] = []
        for event in session.compact(args):
            out += map_event(event, {}, [0])
        out.append(e1.Done(status="completed"))
        return out

    def _command(self, command: Dict[str, Any]) -> None:
        name = command["name"].lstrip("/").lower()
        handler = self.commands.get(name)
        if handler is None:
            self._error("unknown_command", f"unknown command /{name}")
            return
        try:
            for message in handler(command["args"]):
                self.emit(message)
        except Exception as exc:
            self._error("command_failed", f"/{name}: {type(exc).__name__}: {exc}")

    def _complete(self, request: Dict[str, Any]) -> None:
        text, items = request["text"], []
        if request["trigger"] == "/":
            for name in sorted(self.commands):
                if name.startswith(text.lower()):
                    items.append(e1.CompletionItem(value=name))
        else:
            runtime = self.chat.runtime
            prefix = text.lower()
            for path in sorted(self.cwd.rglob("*")):
                if len(items) >= 20:
                    break
                rel = path.relative_to(self.cwd).as_posix()
                if (
                    path.is_file()
                    and rel.lower().startswith(prefix)
                    and not runtime.paths.denied(path)
                    and ".git/" not in rel
                ):
                    items.append(e1.CompletionItem(value=rel))
        self.emit(e1.Completion(id=request["id"], items=items))

    def _set_mode(self, mode: str) -> None:
        self.mode = mode
        overrides = dict(self.chat.overrides or {})
        overrides["agent.approval.mode"] = mode
        self.chat.overrides = overrides
        self.emit(e1.Status(kind="mode", data={"mode": mode}))

    # -- main loop -------------------------------------------------------------------------
    def run(self) -> int:
        self.emit(
            e1.Ready(
                engine=self.version,
                session=self.conversation["id"],
                cwd=str(self.cwd),
                mode=self.mode,
                server=self.chat.runtime.config.model_api.base_url,
            )
        )
        threading.Thread(target=self._read, daemon=True, name="e1-reader").start()
        while True:
            command = self._inbox.get()
            if command is None or command["type"] == "shutdown":
                break
            kind = command["type"]
            if kind == "user_message":
                self._start_turn(command["text"])
            elif kind == "command":
                self._command(command)
            elif kind == "set_mode":
                self._set_mode(command["mode"])
            elif kind == "complete":
                self._complete(command)
        self._interrupt()  # a running turn is stopped and its conversation saved
        self._join_turn()
        return 0
