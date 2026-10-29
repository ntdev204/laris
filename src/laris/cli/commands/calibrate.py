"""`laris evaluate calibrate`: tighten acceptance thresholds from measured val reports."""

import argparse
import json
from pathlib import Path

import yaml

from laris.language.evaluation.calibration import DEFAULT_HEADROOM, calibrate_thresholds
from laris.language.evaluation.evaluator import load_thresholds
from laris.language.evaluation.runner import EXIT_USAGE

HEADER = (
    "# Acceptance thresholds for `laris evaluate language-encoder` (ADR-008).\n"
    "# A task/language group passes when  primary metric >= baseline + min_margin  and\n"
    "# primary metric >= min_absolute. Tighten only with `laris evaluate calibrate`, which\n"
    "# ratchets values up from passing `val` reports and never lowers them.\n"
)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--reports", nargs="+", required=True, help="JSON reports from --split val")
    parser.add_argument("--config", default="configs/evaluation/language_encoder.yaml")
    parser.add_argument("--output", default=None, help="Write here (default: print only)")
    parser.add_argument("--headroom", type=float, default=DEFAULT_HEADROOM)


def run(args: argparse.Namespace) -> int:
    try:
        thresholds = load_thresholds(Path(args.config))
        reports = [json.loads(Path(p).read_text(encoding="utf-8")) for p in args.reports]
        updated, changes = calibrate_thresholds(thresholds, reports, args.headroom)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"[ERROR] {exc}")
        return EXIT_USAGE
    print("\n".join(changes) if changes else "No threshold can be tightened from these reports.")
    if args.output and changes:
        body = yaml.safe_dump(updated, sort_keys=False, default_flow_style=None)
        Path(args.output).write_text(HEADER + body, encoding="utf-8")
        print(f"Wrote {args.output}")
    return 0
