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
        parser.add_argument(
            "--continue", dest="continue_session", nargs="?", const="last", default=None,
            metavar="SESSION_ID", help="Continue the newest session, or the one named by id",
        )  # fmt: skip
        parser.add_argument("--workspace", default=None)
        parser.add_argument("--chat-dir", default=None)
        parser.add_argument("--model-api-url", default=None)
        parser.add_argument("--model-name", default=None)
        parser.add_argument("--api-key-env", default=None)
        parser.add_argument("--allow-write", action="store_true")

    def run(self, args: argparse.Namespace) -> int:
        from importlib import metadata

        from cli.common import load_runtime
        from laris.client.engine import Engine
        from laris.client.engine.login import LoginGate

        # No server, no key, a refused key or an unknown certificate: asked over E1, before `ready`.
        if not LoginGate(sys.stdin, sys.stdout, lambda: load_runtime(args)).run():
            return 0  # the front end left before the session started
        chat: Any = make_chat(args, interactive=False)  # never prompts: stdin carries commands
        conversation = None
        wanted = args.resume or args.continue_session
        if wanted:
            rows = chat.conversations.list()  # newest first
            if wanted == "last":
                wanted = str(rows[0]["id"]) if rows else None  # none saved: start a new one
            else:
                matches = [str(r["id"]) for r in rows if str(r["id"]).startswith(wanted)]
                if len(matches) != 1:  # an id, or a prefix that names exactly one session
                    print(f"[ERROR] no session {wanted}", file=sys.stderr)
                    return 2
                wanted = matches[0]
        if wanted:
            conversation = dict(chat.conversations.get(wanted))
        try:
            version = metadata.version("laris")
        except metadata.PackageNotFoundError:
            version = "unknown"
        home = Path("~/.laris").expanduser()
        manager = make_sandbox(home, chat.prefs.path, version)
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
