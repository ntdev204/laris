"""`laris engine --stdio`: the engine of engine protocol E1 (JSON lines on stdin and stdout)."""

import argparse
import sys
from pathlib import Path
from typing import Any

from cli.commands.agent import make_chat
from laris.client.sandbox import make_sandbox


class _Engine:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--stdio", action="store_true", required=True, help="Speak E1 on stdio")
        parser.add_argument("--resume", default=None, help="Resume a session by id")
        parser.add_argument("--workspace", default=None)
        parser.add_argument("--chat-dir", default=None)
        parser.add_argument("--model-api-url", default=None)
        parser.add_argument("--model-name", default=None)
        parser.add_argument("--api-key-env", default=None)
        parser.add_argument("--allow-write", action="store_true")

    def run(self, args: argparse.Namespace) -> int:
        from importlib import metadata

        from laris.client.engine import Engine

        chat: Any = make_chat(args, interactive=False)  # never prompts: stdin carries commands
        conversation = None
        if args.resume:
            try:
                conversation = dict(chat.conversations.get(args.resume))
            except KeyError:
                print(f"[ERROR] no session {args.resume}", file=sys.stderr)
                return 2
        try:
            version = metadata.version("laris")
        except metadata.PackageNotFoundError:
            version = "unknown"
        home = Path("~/.laris").expanduser()
        manager = make_sandbox(home, chat.prefs.path, version)
        manager.start_background(lambda state: None)  # build or repair quietly while the user types
        return Engine(
            chat,
            sys.stdin,
            sys.stdout,
            version,
            conversation=conversation,
            home=home,
            sandbox=manager,
        ).run()


COMMANDS = {"engine": _Engine()}
