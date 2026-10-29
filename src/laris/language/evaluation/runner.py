"""Evaluates a checkpoint end to end: leakage check, scoring, report file and verdict."""

import json
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from laris.language.evaluation.evaluator import (
    LanguageEncoderEvaluator,
    assert_leakage_verified,
    load_thresholds,
    report_to_dict,
)
from laris.language.inference.loader import load_encoder
from laris.language.training.checkpoint import current_git_commit, file_sha256

EXIT_PASSED = 0
EXIT_BELOW_THRESHOLD = 1
EXIT_USAGE = 2


def evaluate_checkpoint(
    checkpoint: Path,
    data_dir: Path,
    split: str,
    config_path: Path,
    output: Optional[Path] = None,
    tokenizer_model: Optional[Path] = None,
    tokenizer: Any = None,
    max_samples: int = 2000,
    batch_size: int = 16,
    seed: int = 42,
    device: Optional[str] = None,
    log: Callable[[str], None] = print,
) -> Tuple[int, Dict[str, Any]]:
    """Returns (exit_code, report); exit 0 only if every task/language group beats its baseline."""
    assert_leakage_verified(data_dir)
    thresholds = load_thresholds(config_path)
    encoder = load_encoder(checkpoint, tokenizer_model, device=device, tokenizer=tokenizer)
    evaluator = LanguageEncoderEvaluator(
        encoder, data_dir, thresholds, max_samples=max_samples, batch_size=batch_size, seed=seed
    )
    report = evaluator.evaluate(split)
    extra = {
        "checkpoint": str(checkpoint),
        "model_sha256": encoder.manifest["model_sha256"],
        "tokenizer_sha256": encoder.manifest["provenance"].get("tokenizer_sha256"),
        "git_commit": current_git_commit(),
        "thresholds_sha256": file_sha256(config_path),
        "max_samples_per_dataset": max_samples,
    }
    body = report_to_dict(report, extra)

    log(f"\nEvaluation on split '{split}' ({sum(r.samples for r in report.results)} samples)")
    header = f"{'task':<11}{'lang':<5}{'metric':<16}{'value':>8}{'baseline':>10}{'required':>10}"
    log(f"{header}  result")
    for g in report.groups:
        log(
            f"{g['task']:<11}{g['language']:<5}{g['metric']:<16}{g['value']:>8.4f}"
            f"{g['baseline']:>10.4f}{g['required']:>10.4f}  {'PASS' if g['passed'] else 'FAIL'}"
        )
    if not report.groups:
        log(f"No '{split}' shards found under {data_dir}")
    log(f"Overall: {'PASSED' if report.passed else 'FAILED'}")

    if output is not None:
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        with open(output, "w", encoding="utf-8") as handle:
            json.dump(body, handle, indent=2, ensure_ascii=False)
        log(f"Report written to {output}")
    return (EXIT_PASSED if report.passed else EXIT_BELOW_THRESHOLD), body
