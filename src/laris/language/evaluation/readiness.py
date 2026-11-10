"""Offline foundation-stage audit. Reads measurements; never loads or trains a model."""

import math
import re
from typing import Any


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _valid_metric(metric: str, value: Any) -> bool:
    if not _finite(value):
        return False
    if metric == "fertility":
        return bool(value > 0)
    return bool((-1 if metric == "spearman" else 0) <= value <= 1)


def assess_readiness(reports: list[dict], config: dict) -> dict:
    """Require every formal gate, test evidence, and consistent artifact identities.

    This verifies report contracts, not the authenticity of externally supplied
    measurements. Missing protocols or unsupported evaluators remain blockers.
    A report's baseline-relative `passed` flag is deliberately ignored.
    """
    if not isinstance(config, dict) or not reports or any(not isinstance(r, dict) for r in reports):
        raise ValueError("Reports/configuration must be objects")
    if not isinstance(config.get("gates"), list) or not config["gates"]:
        raise ValueError("Readiness requires reports and non-empty formal gates")
    expected_ids = {f"G{i:02d}" for i in range(1, 13)}
    if {g.get("id") for g in config["gates"] if isinstance(g, dict)} != expected_ids:
        raise ValueError("All twelve foundation gates are required; partial configs cannot qualify")
    if config.get("required_split") != "test" or config.get("stage") != "natural_language":
        raise ValueError(
            "Foundation qualification requires the test split and natural_language stage"
        )

    issues = []
    for key in ("model_sha256", "tokenizer_sha256"):
        values = [r.get(key) for r in reports]
        if any(not isinstance(v, str) or not re.fullmatch(r"[a-f0-9]{64}", v) for v in values):
            issues.append(f"Missing or invalid {key}")
        elif len(set(values)) != 1:
            issues.append(f"Reports refer to different {key} artifacts")
    for index, report in enumerate(reports):
        if report.get("split") != config["required_split"]:
            issues.append(f"Report {index}: {report.get('split')!r} is not held-out test evidence")
        digest = report.get("dataset_manifest_sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
            issues.append(f"Report {index}: missing dataset manifest identity")
        if report.get("split_isolation_checked") is not True:
            issues.append(f"Report {index}: split isolation was not recorded")
        rows = report.get("datasets")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError("Report datasets must be a list of measurement records")
        for row in rows:
            for key in ("metrics", "baseline", "metric_protocols"):
                if key in row and not isinstance(row[key], dict):
                    raise ValueError(f"Measurement {key} must be an object")
    records = [row for report in reports for row in report["datasets"]]
    gates, seen = [], set()
    for gate in config["gates"]:
        if gate["id"] in seen or gate["operator"] not in {"ge", "le"}:
            raise ValueError("Formal gate IDs must be unique and operators must be ge/le")
        if not _finite(gate["threshold"]):
            raise ValueError("Formal thresholds must be finite numbers")
        seen.add(gate["id"])
        matches = [
            r
            for r in records
            if r.get("dataset") == gate["dataset"] and r.get("language") == gate["language"]
        ]
        result = {**gate, "status": "MISSING", "value": None, "reason": "No measurement"}
        if len(matches) > 1:
            result.update(status="UNVERIFIED", reason="Ambiguous duplicate measurements")
        elif matches:
            record = matches[0]
            value = record.get("metrics", {}).get(gate["metric"])
            result["value"] = value if _finite(value) else None
            if not _finite(value):
                result.update(reason="Metric is missing or non-finite")
            elif not _valid_metric(gate["metric"], value):
                result.update(status="UNVERIFIED", reason="Metric lies outside its valid range")
            elif (
                not isinstance(record.get("samples"), int)
                or isinstance(record["samples"], bool)
                or record["samples"] <= 0
            ):
                result.update(status="UNVERIFIED", reason="No positive measured sample count")
            elif gate.get("protocol") and (
                record.get("metric_protocols", {}).get(gate["metric"]) != gate["protocol"]
            ):
                result.update(status="UNVERIFIED", reason="Metric protocol is missing/incompatible")
            else:
                passed = (
                    value >= gate["threshold"]
                    if gate["operator"] == "ge"
                    else (value <= gate["threshold"])
                )
                baseline = record.get("baseline", {}).get(gate["metric"])
                if gate.get("must_beat_baseline") and not _valid_metric(gate["metric"], baseline):
                    result.update(status="UNVERIFIED", reason="Measured BM25 baseline is missing")
                else:
                    if gate.get("must_beat_baseline"):
                        passed = passed and value > baseline
                    result.update(
                        status="PASS" if passed else "FAIL",
                        reason="Meets formal gate" if passed else "Below formal gate",
                    )
        gates.append(result)
    return {
        "stage": config["stage"],
        "qualified": not issues and all(g["status"] == "PASS" for g in gates),
        "evidence_issues": issues,
        "gates": gates,
        "model_executed": False,
        "training_executed": False,
        "next_stage": "scientific_language",
    }
