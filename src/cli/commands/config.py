"""`laris config get|set|schema`: read and edit `~/.laris/settings.json` (SR-C2, SR-C6).

Values are JSON where they parse (`true`, `12`, `["a"]`) and text otherwise. A change is validated
against the whole schema before it is written; the error names the JSON path.
"""

import argparse
import json
from pathlib import Path

from laris.shared.config import settings

HOME = Path("~/.laris")


def settings_file() -> Path:
    return HOME.expanduser() / "settings.json"


class _Get:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("path", nargs="?", default="", help="Dotted path, e.g. server.url")

    def run(self, args: argparse.Namespace) -> int:
        data = settings.read_raw(settings_file())
        if not args.path:
            print(json.dumps(data, ensure_ascii=False, indent=2))
            return 0
        try:
            value = settings.get_path(data, args.path)
        except KeyError:
            print(f"[ERROR] {args.path} is not set")
            return 1
        print(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))
        return 0


class _Set:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("path", help="Dotted path, e.g. server.url or permissions.defaultMode")
        parser.add_argument("value", help="JSON value, or plain text")

    def run(self, args: argparse.Namespace) -> int:
        path = settings_file()
        try:
            changed = settings.set_path(
                settings.read_raw(path), args.path, settings.parse_value(args.value)
            )
            settings.write(path, changed)
        except settings.SettingsError as exc:
            print(f"[ERROR] {exc}")
            return 2
        print(
            f"{args.path} = {json.dumps(settings.get_path(changed, args.path), ensure_ascii=False)}"
        )
        return 0


class _Schema:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, args: argparse.Namespace) -> int:
        print(json.dumps(settings.json_schema(), indent=2))
        return 0


COMMANDS = {"get": _Get(), "set": _Set(), "schema": _Schema()}
