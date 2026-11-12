"""`laris-server evaluate suite`: the model-free evaluation suites in one command."""

import argparse
from pathlib import Path

from laris.research.evaluation import suite


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--fast", action="store_true", help="Only the quick suites (CI)")
    parser.add_argument("--only", default="", help=f"Comma separated: {', '.join(suite.ALL)}")
    parser.add_argument("--fixtures", default="tests/fixtures", help="Fixture folder")
    parser.add_argument("--root", default=".", help="Folder holding the system .laris/")
    parser.add_argument("--out", default="", help="Write the JSON report here (e.g. reports/...)")


def run(args: argparse.Namespace) -> int:
    names = [n for n in args.only.split(",") if n] or list(suite.FAST if args.fast else suite.ALL)
    unknown = [n for n in names if n not in suite.SUITES]
    if unknown:
        print(f"[ERROR] unknown suite(s): {', '.join(unknown)}")
        return 2
    report = suite.run(Path(args.fixtures), Path(args.root).resolve(), names)
    text = suite.dumps(report)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    for name, result in report["suites"].items():
        print(f"{'PASS' if result['passed'] else 'FAIL'}  {name}")
    print("all suites passed" if report["passed"] else "some suites FAILED")
    return 0 if report["passed"] else 1
