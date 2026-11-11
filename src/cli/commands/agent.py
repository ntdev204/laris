"""`laris agent ...`: tool-using assistant on the shared harness (terminal front end).

Every default (workspace, model API, limits, approval policy) comes from configuration; flags
only override it. Conversations and preferences are shared with the web UI.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from application.chat_app import ChatApp
from cli.common import load_runtime, make_service, model_flags


def _common(parser: argparse.ArgumentParser) -> None:
    model_flags(parser)
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


def make_chat(args: argparse.Namespace) -> ChatApp:
    from cli.common import cli_overrides

    runtime = load_runtime(args)
    return ChatApp(make_service(args, runtime), runtime.root, overrides=cli_overrides(args))


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


def _ask_permission(name: str, arguments: Dict[str, Any], always: set) -> bool:
    if name in always:
        return True
    shown = json.dumps(arguments, ensure_ascii=False)[:200]
    reply = input(f"  Allow {name} {shown}?  [y]es / [a]lways this session / [N]o ").strip().lower()
    if reply in ("a", "always"):
        always.add(name)
        return True
    return reply in ("y", "yes")


def _turn(chat: Any, conversation_id: str, text: str, always: set, interactive: bool = True) -> int:
    """Stream one user message: live text, tool calls with one-line results, final status."""
    streaming = False
    code = 0
    for event in chat.send(
        conversation_id,
        text,
        (lambda name, arguments: _ask_permission(name, arguments, always))
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


class _Chat:
    """Claude-Code-style terminal session; conversations and settings are shared with the web UI."""

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        _common(parser)
        parser.add_argument("-p", "--print", dest="print_text", help="Run one prompt and exit")
        parser.add_argument(
            "--resume", nargs="?", const="last", help="Resume a conversation id (or the last)"
        )

    def run(self, args: argparse.Namespace) -> int:
        chat = make_chat(args)
        conversation = self._start(chat, args.resume)
        always: set = {"write_file", "ingest_path", "save_memory"} if args.allow_write else set()
        if args.print_text:
            return _turn(chat, conversation["id"], args.print_text, always)
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
                updated = self._command(chat, conversation, line, always)
                if updated is None:
                    return 0
                conversation = updated
                continue
            _turn(chat, conversation["id"], line, always)

    @staticmethod
    def _start(chat: Any, resume: Optional[str]) -> Dict[str, Any]:
        if resume:
            rows = chat.conversations.list()
            target = rows[0]["id"] if resume == "last" and rows else resume
            try:
                return dict(chat.conversations.get(target))
            except KeyError:
                print(f"No conversation {resume}; starting a new one.")
        return dict(chat.conversations.create())

    @staticmethod
    def _command(
        chat: Any, conversation: Dict[str, Any], line: str, always: set
    ) -> Optional[Dict[str, Any]]:
        name, _, rest = line.partition(" ")
        rest = rest.strip()
        if name in ("/exit", "/quit"):
            return None
        if line.strip().lower() in chat.runtime.config.prompts.help_commands:
            print(chat.how_to_use())
        elif name == "/help":
            print(
                "/how-to-use /new /sessions /resume ID /tools /skills /<skill> <yêu cầu> "
                "/compact [ghi chú] "
                "/context /workflows /workflow NAME <yêu cầu> /status /model [URL [NAME]] "
                "/write on|off /learn on|off /rate up|down /exit"
            )
        elif name == "/new":
            conversation = dict(chat.conversations.create())
            print(f"new session {conversation['id']}")
        elif name == "/sessions":
            for row in chat.conversations.list()[:15]:
                print(f"  {row['id']}  {row['messages']:>3} msgs  {row['title']}")
        elif name == "/resume":
            try:
                conversation = dict(chat.conversations.get(rest))
                print(f"resumed {rest}: {conversation['title']}")
            except KeyError:
                print(f"no such session: {rest}")
        elif name == "/tools":
            for spec in chat.tool_specs():
                print(f"  {spec.name}{' (asks)' if spec.writes else ''}: {spec.description}")
        elif name == "/status":
            print(json.dumps(chat.service.status(), indent=2, ensure_ascii=False))
        elif name == "/model":
            if rest:
                parts = rest.split()
                try:
                    chat.update_settings(
                        {"base_url": parts[0], **({"model": parts[1]} if len(parts) > 1 else {})}
                    )
                except ValueError as exc:
                    print(_paint(_ERR, str(exc)))
            print(chat.model_health()["detail"])
        elif name == "/write":
            chat.update_settings({"allow_write": rest == "on"})
            print(f"write tools {'auto-approved' if rest == 'on' else 'ask permission'}")
        elif name == "/skills":
            library = chat.skills_for(chat.runtime)
            for skill_name in library.names():
                print(f"  /{skill_name}: {library.skills[skill_name].summary(110)}")
            for problem in library.problems:
                print(_paint(_ERR, f"  skill problem: {problem}"))
        elif name == "/rate":
            try:
                chat.rate(_LAST.get("example", ""), rest)
                print(f"đã ghi đánh giá: {rest}")
            except (KeyError, ValueError):
                print("dùng: /rate up|down sau một câu trả lời đã được lưu")
        elif name == "/learn":
            chat.update_settings({"learning_enabled": rest == "on"})
            print(f"lưu dữ liệu fine-tune cục bộ: {'bật' if rest == 'on' else 'tắt'}")
        elif name == "/workflows":
            for item in chat.runtime.workflows().summary():
                print(f"  /workflow {item['name']}: {item['description']}")
        elif name == "/workflow":
            _turn(chat, conversation["id"], line, always)
            conversation = dict(chat.conversations.get(conversation["id"]))
        elif name == "/compact":
            events = list(chat.compact(conversation["id"], rest))
            shown = [e for e in events if e["type"] == "compact"]
            for event in shown:
                print(f"nén {event['before']} → {event['after']} token ({event['method']})")
            if not shown:
                print("không có gì để nén")
            conversation = dict(chat.conversations.get(conversation["id"]))
        elif name == "/context":
            usage = chat.usage(conversation["id"])
            cfg = chat.settings()
            print(
                f"≈ {usage['tokens']}/{usage['window']} token; autocompact "
                f"{'bật' if cfg['auto_compact'] else 'tắt'} ở "
                f"{int(cfg['compact_threshold'] * 100)}%"
            )
        elif name[1:] in chat.skills_for(chat.runtime).skills:
            _turn(chat, conversation["id"], line, always)
            conversation = dict(chat.conversations.get(conversation["id"]))
        else:
            print(f"unknown command {name}; try /help")
        return conversation


COMMANDS = {"tools": _Tools(), "run": _Run(), "chat": _Chat(), "guide": _Guide()}
