"""Drivers that run one scripted session through each front end and reduce it to a transcript.

The transcript is the part every front end must agree on: tool calls in order, tool results, the
answer and how the turn ended. Layout, colour and prompts differ by front end: not compared."""

import io
import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from laris.client.engine import Engine
from laris.client.headless import HeadlessOptions, run_headless
from laris.client.plain import EngineLink, PlainClient
from tests.unit.engine.conftest import Harness, wait_status

Transcript = List[Tuple[Any, ...]]


def reduce_events(events: List[Dict[str, Any]]) -> Transcript:
    """E1 events to the comparable transcript."""
    out: Transcript = []
    text = ""
    for event in events:
        kind = event["type"]
        if kind == "text":
            text += event["delta"]
        elif kind == "tool_call":
            out.append(("tool_call", event["name"], json.dumps(event["arguments"], sort_keys=True)))
        elif kind == "tool_result":
            result = event["result"]
            error = result.get("error") if isinstance(result, dict) else None
            out.append(
                ("tool_result", event["name"], error["code"] if isinstance(error, dict) else "ok")
            )
        elif kind == "done":
            out.append(("answer", text))
            out.append(("done", event["status"]))
    return out


def run_engine(chat, project, approvals: Optional[Dict[str, str]] = None, message: str = "go"):
    """Drive the real engine over its JSON lines; answer each permission request from `approvals`
    (tool name to decision, default allow). Returns the events, in order."""
    h = Harness(chat, project)
    h.out.wait("ready")
    h.feed.send({"type": "user_message", "text": message})
    seen = 0
    while True:
        events = h.out.events()
        requests = [e for e in events if e["type"] == "permission_request"]
        if len(requests) > seen:
            request = requests[seen]
            seen += 1
            decision = (approvals or {}).get(request["tool"], "allow")
            h.feed.send({"type": "permission_response", "id": request["id"], "decision": decision})
        if any(e["type"] == "done" for e in events):
            break
        time.sleep(0.01)
    wait_status(h.out, "line", 2)  # the status line the engine refreshes after the turn
    h.stop()
    return h.out.events()


def run_headless_stream(chat, **options):
    out, err = io.StringIO(), io.StringIO()
    code = run_headless(
        chat,
        HeadlessOptions(**{"prompt": "go", "output_format": "stream-json", **options}),
        out,
        err,
    )
    return (
        code,
        [json.loads(line) for line in out.getvalue().splitlines() if line.strip()],
        err.getvalue(),
    )


class Screen:
    def __init__(self, answers):
        self.answers = list(answers)
        self.prompts: List[str] = []
        self.lines: List[str] = []
        self._partial = ""

    def read(self, prompt=""):
        self.prompts.append(prompt)
        if not self.answers:
            raise EOFError
        return self.answers.pop(0)

    def write(self, text="", end="\n", flush=False):
        self._partial += str(text) + end
        *done, self._partial = self._partial.split("\n")
        self.lines.extend(done)

    @property
    def text(self):
        return "\n".join(self.lines) + self._partial


def run_plain(chat, project, answers):
    screen = Screen(answers)
    link = EngineLink(lambda r, w: Engine(chat, r, w, "2.0.0-test", cwd=project))
    code = PlainClient(link, read=screen.read, write=screen.write).run()
    return code, screen


def plain_tools(screen: Screen) -> List[str]:
    """The tool names plain mode printed, in order."""
    return [m.group(1) for line in screen.lines if (m := re.match(r"^● (\S+)", line))]
