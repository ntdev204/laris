"""Hooks (SR-C4, SR-C5): local commands the user runs at five points of a session.

Events: `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Stop`. Hooks are declared
only in `~/.laris/settings.json`: a project folder can never add one, so cloning a repository runs
nothing. Each hook is a command run in the sandbox environment (sandbox first on `PATH`), in the
project folder, with a JSON description of the event on standard input and a timeout after which its
process group is killed.

What a hook answers:
- exit code 0 and empty output: carry on;
- exit code 0 and a JSON object: `{"decision": "block", "reason": "..."}` blocks,
  `{"additionalContext": "..."}` adds text for the model, anything else in it is ignored;
- exit code 2: block, the reason is what the hook wrote on standard error;
- any other exit code, a timeout, a crash or output that is not a JSON object: a warning, and the
  event carries on (a broken hook never stops the session; a hook that must block uses exit code 2).

`PreToolUse` can only make things stricter (a hook cannot grant a permission). A blocked tool call
returns the reason to the model as the tool's error.
"""

import json
import os
import re
import shutil
import signal
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from laris.client.sandbox import SandboxManager, command_env
from laris.shared.config import settings as settings_mod

EVENTS = settings_mod.HOOK_EVENTS
TOOL_EVENTS = ("PreToolUse", "PostToolUse")
OUTPUT_CAP = 64_000
_CONTROL = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f]")  # all but tab and new line


def clean(text: str) -> str:
    """Text a hook wrote, made safe to show: no escape sequence can move the cursor, retitle the
    window, write to the clipboard or hide text on the user's terminal."""
    return _CONTROL.sub("", text)


def _drain(stream: Any, sink: bytearray, limit: int) -> None:
    """Read a pipe to its end, keeping the first `limit` bytes: a hook that floods its output
    cannot fill memory, and never blocks on a full pipe."""
    try:
        while True:
            chunk = stream.read(65536)
            if not chunk:
                return
            room = limit - len(sink)
            if room > 0:
                sink += chunk[:room]
    except (OSError, ValueError):
        return


@dataclass
class HookOutcome:
    blocked: bool = False
    reason: str = ""
    context: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    ran: int = 0


class HookRunner:
    def __init__(
        self,
        settings_file: Path,
        project_root: Path,
        sandbox: Optional[SandboxManager] = None,
        session_id: str = "",
    ) -> None:
        self.settings_file = Path(settings_file)
        self.project_root = Path(project_root)
        self.sandbox = sandbox
        self.session_id = session_id
        self._ready = False
        self._notices: List[Dict[str, Any]] = []

    # -- configuration (user settings only) --------------------------------------------------
    def configured(self) -> Dict[str, List[Any]]:
        try:
            return dict(settings_mod.validate(settings_mod.read_raw(self.settings_file)).hooks)
        except settings_mod.SettingsError:
            return {}

    def has(self, event: str) -> bool:
        return bool(self.configured().get(event))

    def drain(self) -> List[Dict[str, Any]]:
        """Warnings and blocks since the last call, for the front end to show."""
        notices, self._notices = self._notices, []
        return notices

    # -- running ---------------------------------------------------------------------------
    def _matches(self, matcher: str, tool: str) -> bool:
        if matcher in ("", "*"):
            return True
        try:
            return re.fullmatch(matcher, tool, re.I) is not None
        except re.error:
            return False

    def _environment(self, event: str) -> Dict[str, str]:
        if self.sandbox is not None:
            if not self._ready:
                self._ready = self.sandbox.ensure().state == "ready"
            env = command_env(self.sandbox, self._extra_env())
        else:
            env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home())}
        env.update(
            LARIS_HOOK_EVENT=event,
            LARIS_PROJECT_DIR=str(self.project_root),
            LARIS_SESSION_ID=self.session_id,
        )
        return env

    def _extra_env(self) -> Dict[str, str]:
        try:
            return dict(settings_mod.validate(settings_mod.read_raw(self.settings_file)).env)
        except settings_mod.SettingsError:
            return {}

    def _run_one(self, command: str, timeout: float, payload: str, event: str) -> HookOutcome:
        outcome = HookOutcome(ran=1)
        shell = shutil.which("bash") or "/bin/sh"
        try:
            proc = subprocess.Popen(
                [shell, "-c", command], cwd=self.project_root, env=self._environment(event),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                start_new_session=True,
            )  # fmt: skip
        except OSError as exc:
            outcome.warnings.append(f"hook could not start: {exc.strerror or exc}")
            return outcome
        out, err = bytearray(), bytearray()
        readers = [
            threading.Thread(target=_drain, args=(proc.stdout, out, OUTPUT_CAP * 4), daemon=True),
            threading.Thread(target=_drain, args=(proc.stderr, err, OUTPUT_CAP * 4), daemon=True),
        ]

        def feed() -> None:
            try:
                assert proc.stdin is not None
                proc.stdin.write(payload.encode("utf-8", errors="replace"))
                proc.stdin.close()
            except (OSError, ValueError):
                pass  # the hook did not read its input: fine

        readers.append(threading.Thread(target=feed, daemon=True))
        for thread in readers:
            thread.start()
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
            outcome.warnings.append(f"hook timed out after {timeout:g}s: {clean(command)[:80]}")
            return outcome
        finally:
            for thread in readers:  # a detached grandchild may hold a pipe open: do not wait on it
                thread.join(timeout=2)
            for stream in (proc.stdout, proc.stderr):
                try:
                    stream.close()  # type: ignore[union-attr]
                except (OSError, ValueError):
                    pass
        stdout = clean(bytes(out).decode("utf-8", errors="replace"))[:OUTPUT_CAP].strip()
        stderr = clean(bytes(err).decode("utf-8", errors="replace"))[:OUTPUT_CAP].strip()
        if proc.returncode == 2:
            outcome.blocked, outcome.reason = True, stderr or stdout or "blocked by a hook"
            return outcome
        if proc.returncode != 0:
            outcome.warnings.append(
                f"hook exited with code {proc.returncode}: {(stderr or stdout)[:200]}"
            )
            return outcome
        if not stdout:
            return outcome
        try:
            data = json.loads(stdout)
        except ValueError:
            data = None
        if not isinstance(data, dict):
            outcome.warnings.append(
                f"hook output is not a JSON object and was ignored: {stdout[:80]}"
            )
            return outcome
        special = data.get("hookSpecificOutput")
        extra = (special or {}).get("additionalContext") if isinstance(special, dict) else None
        context = data.get("additionalContext", extra)
        if isinstance(context, str) and context.strip():
            outcome.context.append(clean(context).strip())
        if data.get("decision") == "block":
            reason = data.get("reason")
            outcome.blocked = True
            outcome.reason = (
                clean(reason) if isinstance(reason, str) and reason else "blocked by a hook"
            )
        return outcome

    def run(
        self, event: str, payload: Optional[Dict[str, Any]] = None, tool: str = ""
    ) -> HookOutcome:
        """Run every hook of `event` (for tool events, those whose matcher fits `tool`) in order;
        the first block ends the run."""
        total = HookOutcome()
        body = json.dumps(
            {
                "hook_event_name": event,
                "session_id": self.session_id,
                "cwd": str(self.project_root),
                **(payload or {}),
            },
            ensure_ascii=False,
            default=str,
        )
        for matcher in self.configured().get(event, []):
            if event in TOOL_EVENTS and not self._matches(matcher.matcher, tool):
                continue
            for hook in matcher.hooks:
                one = self._run_one(hook.command, hook.timeout, body, event)
                total.ran += one.ran
                total.context += one.context
                total.warnings += one.warnings
                if one.blocked:
                    total.blocked, total.reason = True, one.reason
                    break
            if total.blocked:
                break
        for warning in total.warnings:
            self._notices.append({"event": event, "warning": warning})
        if total.blocked:
            self._notices.append({"event": event, "blocked": total.reason})
        return total
