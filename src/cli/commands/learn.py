"""`laris learn stats|export|purge`: inspect, export and delete locally collected fine-tune data.

Nothing here trains a model. Export writes JSONL plus a manifest for the owner to use later.
"""

import argparse
import json
from pathlib import Path
from typing import Any

from cli.common import load_runtime
from learning.collector import KINDS, Collector


def _collector(args: argparse.Namespace) -> Collector:
    runtime = load_runtime(args)
    folder = Path(runtime.config.learning.dir)
    return Collector(
        runtime.config.learning, folder if folder.is_absolute() else runtime.root / folder
    )


class _Stats:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, args: argparse.Namespace) -> int:
        print(json.dumps(_collector(args).stats(), indent=2))
        return 0


class _Export:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--kind", choices=KINDS, required=True)
        parser.add_argument("--out", required=True, help="Output JSONL file")
        parser.add_argument(
            "--min-rating",
            choices=["none", "up"],
            default=None,
            help="Default: learning.export_min_rating",
        )

    def run(self, args: argparse.Namespace) -> int:
        manifest = _collector(args).export(args.kind, Path(args.out), args.min_rating)
        print(json.dumps(manifest, indent=2))
        return 0


class _Purge:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--yes", action="store_true", help="Confirm deleting all data")

    def run(self, args: argparse.Namespace) -> int:
        if not args.yes:
            print("Refusing to delete collected data without --yes.")
            return 2
        print(f"removed {_collector(args).purge()} files")
        return 0


COMMANDS: dict[str, Any] = {"stats": _Stats(), "export": _Export(), "purge": _Purge()}
