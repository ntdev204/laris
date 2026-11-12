"""Headless mode: `laris -p` runs one task without the interface (SR-C4).

The prompt comes from the argument and/or standard input. Output formats: `text` (the final answer
on stdout), `json` (one object with the result) and `stream-json` (engine protocol E1: one JSON
message per line, the same messages the interactive front end receives). Nothing can be asked in
this mode, so a tool call that needs approval is refused unless a rule allows it
(`--allowed-tools`, `permissions.allow`, `--permission-mode`). Diagnostics go to standard error.

Exit codes:
  0    the task completed
  1    the task did not complete (blocked, out of steps, model or tool failure)
  2    bad usage or configuration (flag value, unknown session, key rejected, mode not allowed)
  3    the task stopped because a needed action was not permitted
  130  interrupted (Ctrl-C); the conversation is saved
"""

import json
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TextIO

from laris.client.engine.engine import map_event
from laris.client.input_forms import InputProcessor, kind_of
from laris.client.permissions import parse_rule
from laris.protocol import engine as e1

EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_DENIED, EXIT_INTERRUPTED = 0, 1, 2, 3, 130
FORMATS = ("text", "json", "stream-json")
EXIT_CODES_HELP = (
    "exit codes: 0 completed, 1 not completed, 2 bad usage or configuration, "
    "3 stopped because an action was not permitted, 130 interrupted"
)


@dataclass
class HeadlessOptions:
    prompt: str = ""
    stdin_text: str = ""
    output_format: str = "text"
    continue_last: bool = False
    resume: Optional[str] = None
    max_turns: Optional[int] = None
    permission_mode: Optional[str] = None
    allowed_tools: List[str] = field(default_factory=list)
    disallowed_tools: List[str] = field(default_factory=list)


def split_rules(values: Optional[List[str]]) -> List[str]:
    """`--allowed-tools "Read,Bash(git status:*)" Edit` -> rules; commas inside () stay."""
    out: List[str] = []
    for value in values or []:
        depth, current = 0, ""
        for char in value:
            depth += (char == "(") - (char == ")")
            if char in ", " and depth <= 0:
                if current.strip():
                    out.append(current.strip())
                current = ""
            else:
                current += char
        if current.strip():
            out.append(current.strip())
    return out


def _usage(message: str, err: TextIO) -> int:
    print(f"[ERROR] {message}", file=err)
    return EXIT_USAGE


def _conversation(chat: Any, options: HeadlessOptions, err: TextIO) -> Optional[Dict[str, Any]]:
    rows = chat.conversations.list()
    if options.resume:
        matches = [r["id"] for r in rows if str(r["id"]).startswith(options.resume)]
        if len(matches) != 1:
            _usage(f"no single session matches {options.resume!r}", err)
            return None
        return dict(chat.conversations.get(matches[0]))
    if options.continue_last:
        if not rows:
            _usage("no earlier session to continue", err)
            return None
        return dict(chat.conversations.get(rows[0]["id"]))
    return dict(chat.conversations.create())


def run_headless(
    chat: Any, options: HeadlessOptions, out: Optional[TextIO] = None, err: Optional[TextIO] = None
) -> int:
    out, err = out or sys.stdout, err or sys.stderr
    prompt = "\n\n".join(p for p in (options.prompt.strip(), options.stdin_text.strip()) if p)
    if not prompt:
        return _usage("nothing to do: give a prompt or pipe text on standard input", err)
    if options.output_format not in FORMATS:
        return _usage(f"--output-format must be one of {', '.join(FORMATS)}", err)
    if options.max_turns is not None:
        if not 1 <= options.max_turns <= 10:
            return _usage("--max-turns must be between 1 and 10", err)
        chat.overrides = {**(chat.overrides or {}), "agent.max_steps": options.max_turns}
    permissions = chat.permissions
    if options.permission_mode:
        try:
            permissions.mode = options.permission_mode
        except ValueError as exc:
            return _usage(str(exc), err)
    for rule in [*options.allowed_tools, *options.disallowed_tools]:
        if parse_rule(rule) is None:
            return _usage(f"not a tool rule: {rule!r}", err)
    permissions.session_allow += options.allowed_tools
    permissions.session_deny += options.disallowed_tools

    conversation = _conversation(chat, options, err)
    if conversation is None:
        return EXIT_USAGE
    form = kind_of(prompt)
    prepared = InputProcessor(chat).prepare(prompt if form == "message" else f" {prompt}")
    text = prepared.text if form == "message" else prompt  # `!` and `#` are plain text here
    for note in prepared.notes:
        print(f"[notice] {note}", file=err)

    chat.session_start(conversation["id"])
    for note in chat.hooks.drain():
        print(f"[hook] {note}", file=err)
    calls: Dict[str, List[str]] = {}
    counter = [0]
    denied: List[str] = []
    tool_calls = 0
    answer, status = "", "error"
    streaming = options.output_format == "stream-json"
    if streaming:
        out.write(
            e1.Ready(
                engine="headless",
                session=conversation["id"],
                cwd=str(chat.project_root),
                mode=str(permissions.mode),
                server=chat.runtime.config.model_api.base_url,
            ).model_dump_json()
            + "\n"
        )
    stream = chat.send(conversation["id"], text, lambda name, arguments: False)
    try:
        for event in stream:
            kind = event["type"]
            if kind == "hook" and not streaming:
                print(f"[hook] {event}", file=err)
            if kind == "tool_call":
                tool_calls += 1
            elif kind == "tool_result":
                error = event["result"].get("error") if isinstance(event["result"], dict) else None
                if isinstance(error, dict) and error.get("code") in ("approval_denied", "denied"):
                    denied.append(str(event["name"]))
            elif kind == "done":
                answer, status = str(event.get("answer", "")), str(event["status"])
            if streaming:
                for message in map_event(event, calls, counter):
                    out.write(message.model_dump_json() + "\n")
                out.flush()
    except KeyboardInterrupt:
        print("[interrupted]", file=err)
        return EXIT_INTERRUPTED
    except Exception as exc:  # the model or a tool broke: said on stderr, exit 1
        print(f"[ERROR] {type(exc).__name__}: {exc}", file=err)
        status = "error"
    finally:
        stream.close()  # saves the conversation
    if options.output_format == "json":
        result = {
            "type": "result",
            "status": status,
            "answer": answer,
            "session_id": conversation["id"],
            "tool_calls": tool_calls,
            "permission_denials": denied,
            "is_error": status != "completed",
        }
        out.write(json.dumps(result, ensure_ascii=False) + "\n")
    elif options.output_format == "text":
        out.write(answer + ("\n" if answer and not answer.endswith("\n") else ""))
    out.flush()
    if status == "completed":
        return EXIT_OK
    return EXIT_DENIED if denied else EXIT_FAILED
