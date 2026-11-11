"""`laris agent ...`: tool-using assistant (offline planner now, model API later)."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from laris.agent.builtin_tools import build_registry, default_sandbox
from laris.agent.loop import AgentSession
from laris.agent.provider import ChatProvider, HttpChatProvider, OfflinePlanner
from laris.application.service import SearchService
from laris.application.workspace import Workspace


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--workspace", default="artifacts/app/workspace")
    parser.add_argument("--checkpoint", help="Local checkpoint for dense search and QA tools")
    parser.add_argument("--tokenizer-model", help="SentencePiece .model for the checkpoint")
    parser.add_argument("--device", default=None)
    parser.add_argument("--provider", choices=["offline", "http"], default="offline")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/v1", help="Model API base URL")
    parser.add_argument("--model", default="laris-core", help="Model name sent to the API")
    parser.add_argument("--api-key-env", default=None, help="Environment variable with the API key")
    parser.add_argument("--read-root", action="append", help="Extra readable folder (repeatable)")
    parser.add_argument(
        "--output-dir", default="artifacts/agent/output", help="Where write_file writes"
    )
    parser.add_argument(
        "--allow-write", action="store_true", help="Approve write tools automatically"
    )


def make_service(args: argparse.Namespace) -> SearchService:
    return SearchService(
        Workspace(Path(args.workspace)),
        Path(args.checkpoint) if args.checkpoint else None,
        Path(args.tokenizer_model) if args.tokenizer_model else None,
        args.device,
    )


def make_provider(args: argparse.Namespace, service: SearchService) -> ChatProvider:
    if args.provider == "http":
        return HttpChatProvider(args.base_url, args.model, args.api_key_env)
    return OfflinePlanner(has_model=service.has_model)


def make_session(args: argparse.Namespace, interactive: bool = False) -> AgentSession:
    service = make_service(args)
    registry = build_registry(
        service,
        default_sandbox([Path(r) for r in (args.read_root or [])] or None, Path(args.output_dir)),
    )

    def approve(name: str, arguments: Dict[str, Any]) -> bool:
        if args.allow_write:
            return True
        if not interactive:
            return False
        reply = input(f"Allow {name} {json.dumps(arguments, ensure_ascii=False)[:200]}? [y/N] ")
        return reply.strip().lower() in ("y", "yes")

    return AgentSession(
        make_provider(args, service), registry, approve, Path("artifacts/agent/sessions")
    )


def print_result(result: Any) -> None:
    for step in result.steps:
        failed = "error" in step["result"] if isinstance(step["result"], dict) else False
        shown = json.dumps(step["arguments"], ensure_ascii=False)[:120]
        print(f"  [{'x' if failed else 'ok'}] {step['tool']} {shown}")
    print(f"\n{result.answer}\n(status: {result.status}; log: {result.log_path})")


class _Tools:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        _common(parser)

    def run(self, args: argparse.Namespace) -> int:
        session = make_session(args)
        for spec in session.registry.tools.values():
            flag = " (writes, needs approval)" if spec.writes else ""
            print(f"{spec.name}{flag}: {spec.description}")
        return 0


class _Run:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        _common(parser)
        parser.add_argument("--task", required=True)

    def run(self, args: argparse.Namespace) -> int:
        result = make_session(args).run(args.task)
        print_result(result)
        return 0 if result.status == "completed" else 1


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


def _turn(chat: Any, conversation_id: str, text: str, always: set) -> int:
    """Stream one user message: live text, tool calls with one-line results, final status."""
    streaming = False
    code = 0
    for event in chat.send(
        conversation_id, text, lambda name, arguments: _ask_permission(name, arguments, always)
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
        parser.add_argument("--chat-dir", default="artifacts/chat")
        parser.add_argument("-p", "--print", dest="print_text", help="Run one prompt and exit")
        parser.add_argument(
            "--resume", nargs="?", const="last", help="Resume a conversation id (or the last)"
        )

    def run(self, args: argparse.Namespace) -> int:
        from laris.application.chat_app import ChatApp

        chat = ChatApp(make_service(args), Path(args.chat_dir))
        changes: Dict[str, Any] = {}
        if args.provider == "http":
            changes.update(base_url=args.base_url, model=args.model)
        if args.allow_write:
            changes["allow_write"] = True
        if changes:
            chat.settings.update(changes)
        conversation = self._start(chat, args.resume)
        always: set = {"write_file", "ingest_path"} if args.allow_write else set()
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
        if name == "/help":
            print(
                "/new /sessions /resume ID /tools /status /model [URL [NAME]] /write on|off /exit"
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
            for spec in build_registry(chat.service, chat.sandbox).tools.values():
                print(f"  {spec.name}{' (asks)' if spec.writes else ''}: {spec.description}")
        elif name == "/status":
            print(json.dumps(chat.service.status(), indent=2, ensure_ascii=False))
        elif name == "/model":
            if rest:
                parts = rest.split()
                chat.settings.update(
                    {"base_url": parts[0], **({"model": parts[1]} if len(parts) > 1 else {})}
                )
            print(chat.model_health()["detail"])
        elif name == "/write":
            chat.settings.update({"allow_write": rest == "on"})
            print(f"write tools {'auto-approved' if rest == 'on' else 'ask permission'}")
        else:
            print(f"unknown command {name}; try /help")
        return conversation


def build_api_session(args: argparse.Namespace) -> Optional[AgentSession]:
    return make_session(args)


COMMANDS = {"tools": _Tools(), "run": _Run(), "chat": _Chat()}
