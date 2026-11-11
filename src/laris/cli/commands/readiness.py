"""Audit existing report files against formal foundation gates without model execution."""

import argparse
import hashlib
import json
from pathlib import Path

import yaml

from laris.language.evaluation.readiness import assess_readiness


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--reports", nargs="+", required=True, help="Existing measurement JSON files"
    )
    parser.add_argument("--config", default="configs/evaluation/foundation.yaml")
    parser.add_argument("--output", default="artifacts/readiness/foundation.json")


def run(args: argparse.Namespace) -> int:
    try:
        reports = [json.loads(Path(path).read_text()) for path in args.reports]
        config = yaml.safe_load(Path(args.config).read_text())
        result = assess_readiness(reports, config)
        result["gate_config_sha256"] = hashlib.sha256(Path(args.config).read_bytes()).hexdigest()
        result["inputs"] = [
            {"path": path, "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()}
            for path in args.reports
        ]
        output = Path(args.output)
        if output.resolve() in {Path(path).resolve() for path in [*args.reports, args.config]}:
            raise ValueError("Readiness output must not overwrite source evidence/configuration")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"[ERROR] {exc}")
        return 2
    for gate in result["gates"]:
        print(
            f"{gate['id']} {gate['dataset']}/{gate['language']} {gate['metric']}: "
            f"{gate['status']} ({gate['reason']}; value={gate['value']})"
        )
    for issue in result["evidence_issues"]:
        print(f"[BLOCKER] {issue}")
    print(f"[{'QUALIFIED' if result['qualified'] else 'NOT QUALIFIED'}] no model/training executed")
    return 0 if result["qualified"] else 1
