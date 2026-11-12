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
from collections import deque
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TextIO

import laris.client.engine.statusline as statusline
from laris.client.engine.commands import BUILTIN, Context
from laris.client.input_forms import InputProcessor, kind_of
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
        self.scope = "once"


class Engine:
    def __init__(
        self,
        chat: Any,
        reader: TextIO,
        writer: TextIO,
        version: str,
        cwd: Optional[Path] = None,
        conversation: Optional[Dict[str, Any]] = None,
        home: Optional[Path] = None,
        sandbox: Optional[Any] = None,
    ) -> None:
        self.chat = chat
        self.reader, self.writer = reader, writer
        self.version = version
        self.cwd = Path(cwd or Path.cwd())
        self.conversation = conversation or chat.conversations.create()
        self.home = Path(home or Path.home() / ".laris")
        self.sandbox = sandbox
        chat.sandbox_manager = sandbox
        self.registry = BUILTIN
        self._out = threading.Lock()
        self._inbox: "queue.Queue[Optional[Dict[str, Any]]]" = queue.Queue()
        self._pending: Dict[str, _Pending] = {}
        self._pending_lock = threading.Lock()
        self._interrupted = threading.Event()
        self._turn: Optional[threading.Thread] = None
        self._permission_count = 0
        self._queued: "deque[Dict[str, Any]]" = deque()  # messages typed while a turn runs
        self.account = statusline.Account(chat)
        self._sandbox_state = "unknown"
        self._working = False

    # -- output ----------------------------------------------------------------------------
    def emit(self, message: Any) -> None:
        line = json.dumps(message.model_dump(mode="json"), ensure_ascii=False)
        with self._out:
            try:
                self.writer.write(line + "\n")
                self.writer.flush()
            except (ValueError, OSError):  # the front end is gone: nobody is left to tell
                return

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
        pending.scope = (
            "session" if response.remember and response.scope == "once" else response.scope
        )
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
        permissions = self.chat.permissions
        rule = permissions.suggest(name, arguments)
        why = permissions.decide(name, arguments, True).reason
        self._permission_count += 1
        request_id = f"perm_{self._permission_count}"
        pending = _Pending()
        with self._pending_lock:
            self._pending[request_id] = pending
        self.emit(
            e1.PermissionRequest(
                id=request_id,
                tool=name,
                arguments=arguments,
                reason=why,
                rule=rule,
                diff=self.chat.preview(name, arguments),
            )
        )
        pending.done.wait()
        if pending.allowed and pending.scope != "once":
            try:
                permissions.remember(rule, pending.scope)
            except (ValueError, OSError) as exc:
                self._error("remember_failed", str(exc))
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
        self._start(self._run_turn, text)

    def _start(self, target: Callable[..., None], *args: Any) -> None:
        if self._busy():
            self._error("busy", "a turn is already running; send `interrupt` first")
            return
        self._interrupted.clear()
        self._working = True

        def work() -> None:
            try:
                target(*args)
            finally:
                self._working = False  # before the thread ends, so the next one can start
                # the main loop starts the next queued message and refreshes the status
                self._inbox.put({"type": "_idle"})

        self._turn = threading.Thread(target=work, daemon=True)
        self._turn.start()

    # -- input forms: @path, !command, # note, pasted text and images (SR-C2) --------------
    def _busy(self) -> bool:
        return self._working

    def _user_message(self, text: str, attachments: List[Dict[str, Any]]) -> None:
        if self._busy() or self._queued:  # typed while the agent works: it runs next, in order
            self._queued.append({"text": text, "attachments": attachments})
            self.emit(
                e1.Status(kind="queued", data={"count": len(self._queued), "text": text[:200]})
            )
            return
        self._submit(text, attachments)

    def _submit(self, text: str, attachments: List[Dict[str, Any]]) -> None:
        processor = InputProcessor(self.chat)
        form = kind_of(text)
        if form == "shell":
            self._start(self._run_shell, processor.prepare(text).text)
        elif form == "note":
            done = processor.note(processor.prepare(text).text)
            if "error" in done:
                self._error("note_failed", done["error"]["message"])
            else:
                self.emit(e1.Text(delta=f"noted in {done.get('path', 'memory')}\n"))
            self.emit(e1.Done(status="completed"))
        else:
            prepared = processor.prepare(text, [e1.Attachment(**a) for a in attachments])
            for note in prepared.notes:
                self.emit(e1.Status(kind="notice", data={"text": note}))
            self._start_turn(prepared.text)

    def _run_shell(self, command: str) -> None:
        try:
            result = InputProcessor(self.chat).shell(
                self.conversation["id"], command, self._approve
            )
        except Exception as exc:  # reported, and the engine stays up
            self._error("shell_failed", f"{type(exc).__name__}: {exc}")
            self.emit(e1.Done(status="error"))
            return
        if "error" in result:
            self._error(result["error"]["code"], result["error"]["message"])
            self.emit(e1.Done(status="error"))
            return
        self.emit(e1.Text(delta=str(result["output"]) + "\n"))
        self.emit(e1.Done(status="timed_out" if result["timed_out"] else "completed"))

    def _next_queued(self) -> None:
        if self._queued and not self._busy():
            item = self._queued.popleft()
            self.emit(
                e1.Status(
                    kind="queued", data={"count": len(self._queued), "started": item["text"][:200]}
                )
            )
            self._submit(item["text"], item["attachments"])

    # -- status line (SR-C1) ---------------------------------------------------------------
    def status_line(self, refresh_account: bool = False) -> None:
        """Send the values of the status line. The account (tokens left) is read off this thread
        so a slow server never delays the session."""

        def send(account: Optional[Dict[str, Any]]) -> None:
            self.emit(
                e1.Status(
                    kind="line",
                    data=statusline.collect(
                        self.chat,
                        self.conversation["id"],
                        self.cwd,
                        self._sandbox_state,
                        account,
                        len(self._queued),
                    ),
                )
            )

        send(self.account.value)

        def fetch() -> None:
            before = self.account.value
            after = self.account.refresh(force=refresh_account)
            if after is not None and after != before:
                send(after)

        threading.Thread(target=fetch, daemon=True, name="e1-account").start()

    def _sandbox_changed(self, state: Any) -> None:
        self._sandbox_state = state.state
        self.emit(e1.Status(kind="sandbox", data={"state": state.state, "hint": state.hint()}))
        self.status_line()

    def _join_turn(self) -> None:
        if self._turn is not None:
            self._turn.join(timeout=30)

    # -- slash commands and completion -----------------------------------------------------
    def _context(self) -> Context:
        return Context(
            self.chat,
            self.conversation,
            self.home,
            self.cwd,
            self.sandbox,
            self.registry,
            {"account": self.account},
        )

    def _command(self, command: Dict[str, Any]) -> None:
        name = command["name"].lstrip("/").lower()
        line = f"{name} {command['args']}".strip()
        result = self.registry.dispatch(line, self._context())
        if result.error:
            code = (
                "unknown_command" if result.text.startswith("unknown command") else "command_failed"
            )
            self._error(code, result.text)
            return
        if result.conversation is not None:
            self.conversation = result.conversation
            self.emit(e1.Status(kind="session", data={"session": self.conversation["id"]}))
        if result.text:
            self.emit(e1.Text(delta=result.text + "\n"))
        if result.exit:
            self._inbox.put({"type": "shutdown"})
        elif result.turn is not None:
            self._start_turn(result.turn)
        else:
            self.emit(e1.Done(status="completed"))

    def _complete(self, request: Dict[str, Any]) -> None:
        text, items = request["text"], []
        if request["trigger"] == "/":
            for found in self.registry.complete(text, self._context()):
                items.append(e1.CompletionItem(value=found.name, description=found.summary))
        else:
            for value, is_dir in InputProcessor(self.chat).complete_files(text):
                items.append(e1.CompletionItem(value=value, description="folder" if is_dir else ""))
        self.emit(e1.Completion(id=request["id"], items=items))

    @property
    def mode(self) -> str:
        return str(self.chat.permissions.mode)

    def _set_mode(self, mode: str) -> None:
        try:
            if mode == "next":
                self.chat.permissions.cycle()
            else:
                self.chat.permissions.mode = mode
        except ValueError as exc:
            self._error("bad_mode", str(exc))
            return
        self.emit(e1.Status(kind="mode", data={"mode": self.mode}))
        self.status_line()

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
        started = self.chat.session_start(self.conversation["id"])
        for note in self.chat.hooks.drain():
            self.emit(e1.Status(kind="hook", data=note))
        if started.blocked:  # a SessionStart hook cannot stop a session; it is told to the user
            self._error("hook_blocked", started.reason)
        threading.Thread(target=self._read, daemon=True, name="e1-reader").start()
        if self.sandbox is not None:
            self.sandbox.start_background(self._sandbox_changed)  # build or repair while typing
        self.status_line()
        while True:
            command = self._inbox.get()
            if command is None or command["type"] == "shutdown":
                break
            kind = command["type"]
            if kind == "user_message":
                self._user_message(command["text"], command.get("attachments", []))
            elif kind == "command":
                self._command(command)
            elif kind == "set_mode":
                self._set_mode(command["mode"])
            elif kind == "complete":
                self._complete(command)
            elif kind == "_idle":
                self.status_line(refresh_account=True)  # the turn just spent tokens
                self._next_queued()
        self._queued.clear()
        self._interrupt()  # a running turn is stopped and its conversation saved
        self._join_turn()
        return 0
