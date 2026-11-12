"""`laris agent ...`: tool-using assistant on the shared harness (terminal front end).

Every default (workspace, model API, limits, approval policy) comes from configuration; flags
only override it. Conversations and preferences are shared with the web UI.
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from cli.common import load_runtime, make_service
from laris.client.application.chat_app import ChatApp
from laris.client.engine.commands import BUILTIN, Context
from laris.client.headless import (
    EXIT_CODES_HELP,
    EXIT_USAGE,
    FORMATS,
    HeadlessOptions,
    run_headless,
    split_rules,
)
from laris.client.input_forms import InputProcessor, kind_of
from laris.client.sandbox import make_sandbox


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--workspace", default=None, help="Workspace folder (config: app.workspace)"
    )
    parser.add_argument("--chat-dir", default=None, help="Chat state folder (config: app.chat_dir)")
    parser.add_argument(
        "--model-api-url", default=None, help="Model API base URL (config: model_api.base_url)"
    )
    parser.add_argument("--model-name", default=None, help="Model name (config: model_api.model)")
    parser.add_argument(
        "--api-key-env", default=None, help="Environment variable holding the API key"
    )
    parser.add_argument(
        "--allow-write", action="store_true", help="Approve write tools automatically"
    )


def make_chat(args: argparse.Namespace, interactive: bool = True) -> ChatApp:
    """The chat for the signed-in user: the API key picks a private conversation space and is
    the credential sent to the model API."""
    import os

    from cli import credentials
    from cli.common import cli_overrides

    runtime = load_runtime(args)
    app = runtime.config.app
    key = credentials.resolve(app, interactive=interactive and sys.stdin.isatty())
    os.environ[app.key_env] = key  # the redactor hides it; the model client reads it
    if credentials.verify_with_server(runtime.config.model_api, key) == "rejected":
        raise credentials.CredentialError(
            "máy chủ từ chối API key; chạy `laris login` để nhập khóa đúng"
        )
    overrides = cli_overrides(args)
    overrides.setdefault("model_api.api_key_env", app.key_env)
    return ChatApp(
        make_service(args, runtime),
        runtime.root,
        overrides=overrides,
        user=credentials.fingerprint(key),
    )


class _Tools:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        _common(parser)

    def run(self, args: argparse.Namespace) -> int:
        for spec in make_chat(args).tool_specs():
            flag = " (writes, needs approval)" if spec.writes else ""
            print(f"{spec.name}{flag}: {spec.description}")
        return 0


class _Guide:
    """Print the prepared user guide (no model, no workspace)."""

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, args: argparse.Namespace) -> int:
        runtime = load_runtime(args)
        path = Path(runtime.config.prompts.help_file).expanduser()
        path = path if path.is_absolute() else runtime.root / path
        print(
            path.read_text(encoding="utf-8")
            if path.is_file()
            else runtime.strings.get("help.missing")
        )
        return 0


class _Run:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        _common(parser)
        parser.add_argument("--task", required=True)

    def run(self, args: argparse.Namespace) -> int:
        chat = make_chat(args)
        conversation = chat.conversations.create()
        always: set = {"write_file", "ingest_path", "save_memory"} if args.allow_write else set()
        return _turn(chat, conversation["id"], args.task, always, interactive=False)


_LAST: Dict[str, str] = {}  # id of the latest stored example, for /rate
_USE = "\033[1m"
_DIM = "\033[2m"
_ERR = "\033[31m"
_END = "\033[0m"


def _paint(code: str, text: str) -> str:
    return f"{code}{text}{_END}" if sys.stdout.isatty() else text


def _summarise(result: Any) -> str:
    if isinstance(result, dict) and "error" in result:
        return _paint(_ERR, f"error {result['error']['code']}: {result['error']['message'][:160]}")
    if isinstance(result, dict) and "hits" in result:
        return f"{len(result['hits'])} passages"
    if isinstance(result, dict) and "text" in result:
        return f"{result.get('total_chars', len(result['text']))} chars"
    return json.dumps(result, ensure_ascii=False)[:160]


_SCOPES = {"a": "session", "p": "project", "e": "everywhere"}


def _ask_permission(chat: Any, name: str, arguments: Dict[str, Any], always: set) -> bool:
    if name in always:
        return True
    shown = json.dumps(arguments, ensure_ascii=False)[:200]
    rule = chat.permissions.suggest(name, arguments)
    reply = (
        input(
            f"  Allow {name} {shown}?  [y]es / [a]lways this session / always in this [p]roject / "
            f"always [e]verywhere ({rule}) / [N]o "
        )
        .strip()
        .lower()
    )
    scope = _SCOPES.get(reply[:1]) if reply not in ("y", "yes", "n", "no", "") else None
    if scope:
        try:
            chat.permissions.remember(rule, scope)
        except (ValueError, OSError) as exc:
            print(_paint(_ERR, f"could not save the rule: {exc}"))
        return True
    return reply in ("y", "yes")


def _turn(chat: Any, conversation_id: str, text: str, always: set, interactive: bool = True) -> int:
    """Stream one user message: live text, tool calls with one-line results, final status."""
    streaming = False
    code = 0
    for event in chat.send(
        conversation_id,
        text,
        (lambda name, arguments: _ask_permission(chat, name, arguments, always))
        if interactive
        else (lambda name, arguments: name in always),
    ):
        kind = event["type"]
        if kind == "text":
            streaming = True
            print(event["delta"], end="", flush=True)
        elif kind == "tool_call":
            if streaming:
                print()
                streaming = False
            shown = json.dumps(event["arguments"], ensure_ascii=False)[:110]
            print(_paint(_USE, f"● {event['name']}") + _paint(_DIM, f" {shown}"))
        elif kind == "tool_result":
            print(_paint(_DIM, "  ⎿ ") + _summarise(event["result"]))
        elif kind == "hook":
            print(_paint(_DIM, _hook_line(event)))
        elif kind == "brain":
            print(_paint(_DIM, "  ◈ bộ não: " + " → ".join(event["trace"])))
        elif kind == "plan":
            if streaming:
                print()
                streaming = False
            marks = {"pending": " ", "in_progress": "~", "done": "x", "failed": "!", "skipped": "-"}
            head = {"auto": "kế hoạch (tự ghi)", "resumed": "kế hoạch đang dở"}.get(
                event["source"], "kế hoạch"
            )
            print(_paint(_DIM, f"  ☰ {head}:"))
            for number, step in enumerate(event["steps"], 1):
                print(_paint(_DIM, f"    {number}. [{marks[step['status']]}] {step['text']}"))
        elif kind == "reflect":
            what = "hết lượt lập lại kế hoạch" if event.get("budget_out") else "đổi cách"
            print(_paint(_DIM, f"  ↺ {what}: " + "; ".join(event["issues"])))
        elif kind == "goal" and event.get("retry"):
            print(_paint(_DIM, "  ⚑ mục tiêu chưa xong: " + "; ".join(event["open"])))
        elif kind == "compact":
            print(
                _paint(
                    _DIM,
                    f"⟳ Đã nén ngữ cảnh ({event['method']}): {event['before']} → "
                    f"{event['after']} token, {event['summarized']} tin nhắn được tóm tắt",
                )
            )
        elif kind == "verify":
            print(_paint(_DIM, "  ↻ kiểm tra trích dẫn, đang viết lại"))
        elif kind == "learning":
            if event.get("stored"):
                _LAST["example"] = event["example_id"]
        elif kind == "usage" and event["window"]:
            if streaming:
                print()
                streaming = False
            print(_paint(_DIM, f"  ngữ cảnh ≈ {event['tokens']}/{event['window']} token"))
        elif kind == "done":
            if streaming:
                print()
            if event["status"] != "completed":
                print(_paint(_ERR, f"[{event['status']}] {event['answer']}"))
                code = 1
    print()
    return code


def _input(chat: Any, conversation_id: str, line: str, always: set) -> int:
    """A typed line: `!command`, `# note`, or a message with `@path` mentions attached."""
    processor = InputProcessor(chat)
    form = kind_of(line)
    if form == "shell":
        result = processor.shell(
            conversation_id,
            processor.prepare(line).text,
            lambda name, arguments: _ask_permission(chat, name, arguments, always),
        )
        if "error" in result:
            print(_paint(_ERR, result["error"]["message"]))
            return 1
        print(result["output"], end="" if str(result["output"]).endswith("\n") else "\n")
        return 0 if result["exit_code"] == 0 else 1
    if form == "note":
        done = processor.note(processor.prepare(line).text)
        print(
            _paint(_ERR, done["error"]["message"])
            if "error" in done
            else f"noted in {done['path']}"
        )
        return 0
    prepared = processor.prepare(line)
    for note in prepared.notes:
        print(_paint(_DIM, note))
    return _turn(chat, conversation_id, prepared.text, always)


def _hook_line(note: Dict[str, Any]) -> str:
    if "blocked" in note:
        return f"  ⛔ hook {note['event']} blocked: {note['blocked']}"
    return f"  ⚠ hook {note['event']}: {note.get('warning', '')}"


def _piped_input() -> str:
    """Text piped on standard input (`cat file | laris -p "explain"`); nothing on a terminal."""
    try:
        return "" if sys.stdin.isatty() else sys.stdin.read()
    except (OSError, ValueError):  # no usable standard input
        return ""


class _Chat:
    """Claude-Code-style terminal session; conversations and settings are shared with the web UI."""

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        _common(parser)
        parser.add_argument(
            "-p",
            "--print",
            dest="print_text",
            nargs="?",
            const="",
            default=None,
            help="Run one prompt without the interface (text may also come from standard input)",
        )
        parser.add_argument(
            "--output-format",
            choices=FORMATS,
            default="text",
            help="With -p: text, json or stream-json",
        )
        parser.epilog = EXIT_CODES_HELP
        parser.add_argument(
            "-c", "--continue", dest="continue_last", action="store_true",
            help="Continue the most recent session",
        )  # fmt: skip
        parser.add_argument(
            "--max-turns", type=int, default=None, help="With -p: agent steps (1-10)"
        )
        parser.add_argument(
            "--permission-mode",
            choices=["default", "acceptEdits", "plan", "bypass"],
            default=None,
            help="Permission mode for this run (bypass only when the policy allows it)",
        )
        parser.add_argument(
            "--allowed-tools", action="append", default=None, metavar="RULES",
            help="Tool rules allowed without asking, e.g. 'Read,Bash(git status:*)'",
        )  # fmt: skip
        parser.add_argument(
            "--disallowed-tools", action="append", default=None, metavar="RULES",
            help="Tool rules refused for this run",
        )  # fmt: skip
        parser.add_argument(
            "--resume",
            nargs="?",
            const="pick",
            help="Resume a session by id (or unique prefix); without an id, choose from a list",
        )

    def run(self, args: argparse.Namespace) -> int:
        if args.print_text is not None:
            return self._headless(args)
        chat = make_chat(args)
        conversation = self._start(
            chat, "last" if args.continue_last and not args.resume else args.resume
        )
        home = Path("~/.laris").expanduser()
        manager = make_sandbox(home, chat.prefs.path, "plain")
        manager.start_background(lambda state: None)
        chat.sandbox_manager = manager
        chat.session_start(conversation["id"])
        for note in chat.hooks.drain():
            print(_paint(_DIM, _hook_line(note)), file=sys.stderr)
        always: set = {"write_file", "ingest_path", "save_memory"} if args.allow_write else set()
        print(
            _paint(_USE, "LARIS")
            + f"  session {conversation['id']}  ·  {chat.model_health()['detail']}"
        )
        print(_paint(_DIM, "Type a task. /help lists commands. Ctrl+D exits."))
        while True:
            try:
                line = input("\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if not line:
                continue
            if line.startswith("/"):
                updated = self._command(chat, conversation, line, always, manager)
                if updated is None:
                    return 0
                conversation = updated
                continue
            _input(chat, conversation["id"], line, always)

    @staticmethod
    def _headless(args: argparse.Namespace) -> int:
        """`laris -p`: one task, no interface, documented output formats and exit codes."""
        from cli.credentials import CredentialError
        from laris.shared.harness.integrity import IntegrityError
        from laris.shared.policy.prompts import PromptError

        try:
            chat = make_chat(args, interactive=False)
        except (CredentialError, IntegrityError, PromptError) as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return EXIT_USAGE
        allowed = split_rules(args.allowed_tools)
        if args.allow_write:
            allowed += ["write_file", "ingest_path", "save_memory", "Write", "Edit"]
        options = HeadlessOptions(
            prompt=args.print_text,
            stdin_text=_piped_input(),
            output_format=args.output_format,
            continue_last=args.continue_last,
            resume=None if args.resume in (None, "pick") else args.resume,
            max_turns=args.max_turns,
            permission_mode=args.permission_mode,
            allowed_tools=allowed,
            disallowed_tools=split_rules(args.disallowed_tools),
        )
        if args.resume == "pick":
            print("[ERROR] --resume needs a session id with -p", file=sys.stderr)
            return EXIT_USAGE
        return run_headless(chat, options)

    @staticmethod
    def _pick(rows: List[Dict[str, Any]]) -> Optional[str]:
        """Numbered list of saved sessions; Enter takes the newest, `n` starts a new one."""
        if not rows:
            print("Chưa có phiên nào; bắt đầu phiên mới.")
            return None
        shown = rows[:20]
        for number, row in enumerate(shown, 1):
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(row["updated"]))
            print(f"  {number:>2}. {row['id']}  {when}  {row['messages']:>3} tin  {row['title']}")
        try:
            choice = input("Chọn số hoặc id (Enter = mới nhất, n = phiên mới): ").strip()
        except (EOFError, KeyboardInterrupt):
            choice = ""
        if choice.lower() == "n":
            return None
        if choice.isdigit() and 1 <= int(choice) <= len(shown):
            return str(shown[int(choice) - 1]["id"])
        return choice or str(shown[0]["id"])

    @staticmethod
    def _start(chat: Any, resume: Optional[str]) -> Dict[str, Any]:
        if resume:
            rows = chat.conversations.list()
            target: Optional[str] = _Chat._pick(rows) if resume == "pick" else resume
            if target == "last" and rows:
                target = rows[0]["id"]
            if target:
                matches = [r["id"] for r in rows if str(r["id"]).startswith(target)]
                if len(matches) == 1:
                    target = matches[0]
                try:
                    return dict(chat.conversations.get(target))
                except KeyError:
                    print(f"Không có phiên {target}; bắt đầu phiên mới.")
        return dict(chat.conversations.create())

    @staticmethod
    def _command(
        chat: Any, conversation: Dict[str, Any], line: str, always: set, session: Any = None
    ) -> Optional[Dict[str, Any]]:
        """One slash command through the registry shared with the engine (SR-C2)."""
        if line.strip().lower() in chat.runtime.config.prompts.help_commands:
            print(chat.how_to_use())
            return conversation
        context = Context(
            chat, conversation, Path("~/.laris").expanduser(), Path.cwd(), session, BUILTIN
        )
        context.extras["last_example"] = _LAST.get("example", "")
        result = BUILTIN.dispatch(line, context)
        if result.exit:
            return None
        if result.text:
            print(_paint(_ERR, result.text) if result.error else result.text)
        if result.conversation is not None:
            conversation = result.conversation
        if result.turn is not None:
            _turn(chat, conversation["id"], result.turn, always)
            conversation = dict(chat.conversations.get(conversation["id"]))
        return conversation


COMMANDS = {"tools": _Tools(), "run": _Run(), "chat": _Chat(), "guide": _Guide()}
