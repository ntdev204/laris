"""Plain-text mode (`laris --plain`, D22, SR-C1): a front end of engine protocol E1 that uses only
`input` and `print`, so it works where the Ink front end cannot start.

It is a client like any other: the engine runs in this process on two in-memory pipes and the
client speaks the same JSON messages the Ink front end does (`ready`, `user_message`,
`permission_request` with its diff, `command`, `interrupt`, `shutdown`). The client holds no tool,
permission or storage logic. Ctrl+C during a turn sends `interrupt` and waits for the engine to
close the turn; at the prompt, Ctrl+C or Ctrl+D leaves. It imports no third-party package.
"""

import json
import queue
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, Optional

from laris.protocol import engine as e1

Reader = Callable[[str], str]
Writer = Callable[..., None]

_SCOPES = {"a": "session", "p": "project", "e": "everywhere"}
# Errors that answer a command and are not followed by a `done` event.
_ENDS_COMMAND = {"unknown_command", "command_failed", "bad_command", "bad_mode", "busy"}
_QUIET_STATUS = {"line", "learning", "mode", "session", "sandbox"}


class _Pipe:
    """One direction of the in-memory pipe: the engine writes lines, the client reads them."""

    def __init__(self) -> None:
        self.q: "queue.Queue[Optional[str]]" = queue.Queue()

    def write(self, text: str) -> int:
        self.q.put(text)
        return len(text)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        self.q.put(None)

    def __iter__(self) -> Iterator[str]:
        while True:
            item = self.q.get()
            if item is None:
                return
            yield item


class EngineLink:
    """The engine of this process on two pipes: `send(command)` and `events` (None at the end)."""

    def __init__(self, engine_factory: Callable[[Any, Any], Any]) -> None:
        self._to_engine, self._from_engine = _Pipe(), _Pipe()
        self.engine = engine_factory(self._to_engine, self._from_engine)
        self.code = 0
        self.events: "queue.Queue[Optional[Dict[str, Any]]]" = queue.Queue()
        self._thread = threading.Thread(target=self._run_engine, daemon=True, name="plain-engine")
        self._relay = threading.Thread(target=self._relay_events, daemon=True, name="plain-relay")
        self._thread.start()
        self._relay.start()

    def _run_engine(self) -> None:
        try:
            self.code = int(self.engine.run())
        finally:
            self._from_engine.close()

    def _relay_events(self) -> None:
        for line in self._from_engine:
            if line.strip():
                self.events.put(json.loads(line))
        self.events.put(None)

    def send(self, command: Dict[str, Any]) -> None:
        self._to_engine.write(json.dumps(command, ensure_ascii=False) + "\n")

    def close(self) -> int:
        self._to_engine.close()
        self._thread.join(timeout=30)
        return self.code


def summarise(result: Any) -> str:
    """One line for a tool result."""
    if isinstance(result, dict) and "error" in result:
        error = result["error"]
        return f"error {error.get('code', '?')}: {str(error.get('message', ''))[:160]}"
    if isinstance(result, dict) and "hits" in result:
        return f"{len(result['hits'])} passages"
    if isinstance(result, dict) and "text" in result:
        return f"{result.get('total_chars', len(result['text']))} chars"
    return json.dumps(result, ensure_ascii=False)[:160]


class PlainClient:
    def __init__(
        self,
        link: Any,
        read: Optional[Reader] = None,
        write: Optional[Writer] = None,
        prompt: str = "\n> ",
    ) -> None:
        self.link, self.prompt = link, prompt
        # looked up when used, so a terminal that replaces `input`/`print` is honoured
        self.read: Reader = read or (lambda text: input(text))
        self.write: Writer = write or (lambda *a, **k: print(*a, **k))
        self._streaming = False
        self._interrupted = False

    # -- output ----------------------------------------------------------------------------
    def _say(self, text: str = "") -> None:
        if self._streaming:
            self.write()
            self._streaming = False
        self.write(text)

    # -- events ----------------------------------------------------------------------------
    def _approve(self, event: Dict[str, Any]) -> None:
        shown = json.dumps(event["arguments"], ensure_ascii=False)[:300]
        self._say(f"  Permission: {event['tool']} {shown}")
        if event.get("reason"):
            self.write(f"  Why: {event['reason']}")
        if event.get("diff"):
            self.write(event["diff"].rstrip("\n"))
        rule = event.get("rule", "")
        try:
            reply = (
                self.read(
                    "  Allow?  [y]es / [a]lways this session / always in this [p]roject / "
                    f"always [e]verywhere ({rule}) / [N]o "
                )
                .strip()
                .lower()
            )
        except (EOFError, KeyboardInterrupt):
            reply = "n"
            self._interrupt()
        scope = _SCOPES.get(reply[:1]) if reply not in ("y", "yes", "n", "no", "") else None
        allowed = scope is not None or reply in ("y", "yes")
        self.link.send(
            {
                "type": "permission_response",
                "id": event["id"],
                "decision": "allow" if allowed else "deny",
                "scope": scope or "once",
            }
        )

    def _interrupt(self) -> None:
        if not self._interrupted:
            self._interrupted = True
            self.link.send({"type": "interrupt"})

    def _show(self, event: Dict[str, Any]) -> Optional[bool]:
        """Draw one event. True: the turn is over. False: the engine ended."""
        kind = event["type"]
        if kind == "text":
            self._streaming = True
            self.write(event["delta"], end="", flush=True)
        elif kind == "tool_call":
            self._say(
                f"● {event['name']} {json.dumps(event['arguments'], ensure_ascii=False)[:110]}"
            )
        elif kind == "tool_result":
            self._say(f"  ⎿ {summarise(event['result'])}")
        elif kind == "plan":
            marks = {"pending": " ", "in_progress": "~", "done": "x", "failed": "!", "skipped": "-"}
            self._say(f"  ☰ plan ({event.get('source', '')}):")
            for number, step in enumerate(event["steps"], 1):
                mark = marks.get(step.get("status", ""), " ")
                self.write(f"    {number}. [{mark}] {step.get('text', '')}")
        elif kind == "permission_request":
            self._approve(event)
        elif kind == "usage" and event["window"]:
            self._say(f"  context ≈ {event['tokens']}/{event['window']} tokens")
        elif kind == "compact":
            moved = f"{event['before']} → {event['after']}"
            self._say(f"⟳ context compacted ({event['method']}): {moved} tokens")
        elif kind == "goal" and event.get("retry"):
            self._say("  ⚑ goal not finished: " + "; ".join(map(str, event["open"])))
        elif kind == "status":
            self._status(event)
        elif kind == "error":
            self._say(f"[error] {event['message']}")
            return event["code"] in _ENDS_COMMAND
        elif kind == "done":
            self._say()
            if event["status"] not in ("completed", "interrupted"):
                self.write(f"[{event['status']}] {event.get('answer', '')}")
            elif event["status"] == "interrupted":
                self.write("[interrupted]")
            return True
        return None

    def _status(self, event: Dict[str, Any]) -> None:
        kind, data = event["kind"], event.get("data", {})
        if kind in _QUIET_STATUS:
            return
        if kind == "notice":
            self._say(f"  {data.get('text', '')}")
        elif kind == "queued":
            self._say(f"  queued ({data.get('count', 0)} waiting)")
        elif kind == "hook":
            what = f"blocked: {data['blocked']}" if "blocked" in data else data.get("warning", "")
            self._say(f"  hook {data.get('event', '')}: {what}")
        elif kind == "brain":
            self._say("  ◈ brain: " + " → ".join(map(str, data.get("trace", []))))
        elif kind == "reflect":
            self._say("  ↺ " + "; ".join(map(str, data.get("issues", []))))
        elif kind == "verify":
            self._say("  ↻ checking citations, rewriting")

    def _wait_turn(self) -> bool:
        """Draw events until the turn ends. False when the engine itself has ended."""
        self._interrupted = False
        while True:
            try:
                event = self.link.events.get()
            except KeyboardInterrupt:
                self._interrupt()
                continue
            if event is None:
                self._say()
                return False
            try:
                if self._show(event):
                    return True
            except KeyboardInterrupt:
                self._interrupt()

    # -- session ---------------------------------------------------------------------------
    def run(self) -> int:
        ready = self.link.events.get()
        if ready is None or ready.get("type") != "ready":
            self.write("[error] the engine did not start", flush=True)
            return 2
        problem = e1.check_version(ready)
        if problem:
            self.write(f"[error] {problem}")
            self.link.close()
            return 2
        self.write(f"LARIS  session {ready['session']}  ·  {ready['cwd']}  ·  mode {ready['mode']}")
        self.write("Type a task. /help lists commands. Ctrl+D exits.")
        while True:
            try:
                line = self.read(self.prompt).strip()
            except (EOFError, KeyboardInterrupt):
                self.write()
                break
            if not line:
                continue
            if line.startswith("/"):
                name, _, args = line[1:].partition(" ")
                if not name:
                    self.write("Type /help for the list of commands.")
                    continue
                self.link.send({"type": "command", "name": name, "args": args.strip()})
            else:
                self.link.send({"type": "user_message", "text": line})
            if not self._wait_turn():
                break
        self.link.send({"type": "shutdown"})
        return int(self.link.close())


def run_plain(
    chat: Any,
    conversation: Optional[Dict[str, Any]],
    version: str,
    home: Path,
    sandbox: Optional[Any] = None,
    cwd: Optional[Path] = None,
) -> int:
    """`laris --plain`: the engine of this process with the plain-text client in front."""
    from laris.client.engine import Engine

    link = EngineLink(
        lambda reader, writer: Engine(
            chat,
            reader,
            writer,
            version,
            cwd=cwd,
            conversation=conversation,
            home=home,
            sandbox=sandbox,
        )
    )
    return PlainClient(link).run()
